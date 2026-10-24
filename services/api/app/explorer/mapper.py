"""Site mapping: find links (nav, sitemap, SPA clicks), rank them, crawl by score."""

import heapq
import itertools
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urldefrag, urlencode, urljoin, urlparse, urlunparse

from playwright.sync_api import BrowserContext, Page

from app.core.safety import is_blocked, is_blocked_href
from app.explorer.browser import detect_blockers, dismiss_cookie_banner
from app.explorer.extract import extract_page, settle
from app.explorer.models import Element, PageData
from app.explorer.report import Deadline, Report

MAX_DEPTH = 2
MAX_SITEMAP_URLS = 50
MAX_SPA_CLICKS_PER_PAGE = 12
POSITIVE_PATH = re.compile(
    r"features?|dashboard|create|new|editor|app|product|solutions?|use-?cases?|tools?|pricing", re.I
)
NEGATIVE_PATH = re.compile(
    r"blog|privacy|terms|careers?|jobs|log-?in|sign-?in|signin|logout|billing|payment|cookie|legal|press|changelog",
    re.I,
)
SKIP_EXT = re.compile(
    r"\.(pdf|zip|png|jpe?g|gif|svg|webp|mp4|webm|mp3|css|js|json|xml|ico|woff2?|ttf)$", re.I
)
TRACKING = {"fbclid", "gclid", "ref", "source"}

LINKS_JS = r"""
() => [...document.querySelectorAll('a[href]')].map((a) => {
  const within = (s) => a.closest(s);
  const region = within('nav,[role=navigation]') ? 'nav'
    : within('aside,[role=complementary]') ? 'aside'
    : within('header,[role=banner]') ? 'header'
    : within('footer,[role=contentinfo]') ? 'footer' : 'main';
  const r = a.getBoundingClientRect();
  const label = a.innerText || a.getAttribute('aria-label') || '';
  return { href: a.href, text: label.replace(/\s+/g, ' ').trim().slice(0, 80),
           region, visible: r.width > 1 && r.height > 1 };
})
"""


class BlockedByChallenge(RuntimeError):
    """Cloudflare / CAPTCHA page: stop and report, never try to get around it."""


@dataclass
class Candidate:
    url: str
    text: str
    region: str
    depth: int
    score: float
    origin: str = "link"  # link | sitemap | spa_click | root | user


def normalize_url(url: str, base: str | None = None) -> str | None:
    """Absolute, fragment-less (hash routes `#/..` and `#!..` are kept), tracking params dropped."""
    absolute = urljoin(base, url) if base else url
    parsed = urlparse(absolute)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    if SKIP_EXT.search(parsed.path):
        return None
    _, fragment = urldefrag(absolute)
    keep_fragment = fragment if fragment.startswith(("/", "!")) else ""
    query = urlencode(
        [
            (k, v)
            for k, v in parse_qsl(parsed.query)
            if not k.startswith("utm_") and k not in TRACKING
        ]
    )
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", query, keep_fragment))


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").removeprefix("www.")


def same_site(url: str, root: str) -> bool:
    return _host(url) == _host(root)


def score_candidate(
    url: str, region: str, depth: int, *, origin: str = "link", parent_interactive: int = 0
) -> float:
    """Higher = visit sooner. Region/path bonuses and penalties as specified for the mapper."""
    score = {"nav": 3.0, "aside": 3.0, "header": 1.5, "footer": 0.2}.get(region, 0.0)
    path = urlparse(url).path + urlparse(url).fragment
    if POSITIVE_PATH.search(path):
        score += 2.0
    if NEGATIVE_PATH.search(path):
        score -= 4.0
    score -= 0.5 * depth
    score += min(1.0, parent_interactive / 60)
    if origin == "sitemap":
        score += 0.5
    return round(score, 2)


class Frontier:
    """Priority queue of candidates (highest score first) that never returns a URL twice."""

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, Candidate]] = []
        self._counter = itertools.count()
        self.known: dict[str, Candidate] = {}
        self.visited: set[str] = set()

    def add(self, cand: Candidate) -> bool:
        existing = self.known.get(cand.url)
        if existing and existing.score >= cand.score:
            return False
        self.known[cand.url] = cand
        if cand.url not in self.visited:
            heapq.heappush(self._heap, (-cand.score, next(self._counter), cand))
        return True

    def pop(self) -> Candidate | None:
        while self._heap:
            _, _, cand = heapq.heappop(self._heap)
            if cand.url not in self.visited and self.known.get(cand.url) is cand:
                self.visited.add(cand.url)
                return cand
        return None


def candidates_from_links(
    raw_links: list[dict[str, Any]],
    page_url: str,
    root: str,
    depth: int,
    report: Report,
    *,
    parent_interactive: int = 0,
) -> list[Candidate]:
    """Raw anchors -> scored candidates (same domain; blacklisted/bad paths dropped)."""
    nav_like = [lk for lk in raw_links if lk["region"] != "main"]
    # Pages without nav/header/footer links (single-page apps, tools): fall back to in-page links
    pool = nav_like if len(nav_like) >= 3 else raw_links
    out: dict[str, Candidate] = {}
    for link in pool:
        url = normalize_url(link["href"], page_url)
        if not url or not same_site(url, root):
            continue
        if is_blocked(link["text"]) or is_blocked_href(url):
            report.skip(url, f"blacklist: {link['text']!r} -> {url}")
            continue
        score = score_candidate(url, link["region"], depth, parent_interactive=parent_interactive)
        if url not in out or out[url].score < score:
            out[url] = Candidate(url, link["text"], link["region"], depth, score)
    return list(out.values())


def fetch_sitemap_urls(context: BrowserContext, root: str) -> list[str]:
    """Up to 50 same-site URLs from /sitemap.xml (one level of sitemap index followed)."""
    base = f"{urlparse(root).scheme}://{urlparse(root).netloc}"

    def locs(url: str) -> list[str]:
        try:
            res = context.request.get(url, timeout=8000)
            if not res.ok or "xml" not in (res.headers.get("content-type", "") + url):
                return []
            return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", res.text())
        except Exception:
            return []

    found = locs(base + "/sitemap.xml")
    urls: list[str] = []
    for loc in found:
        if loc.endswith(".xml") and len(urls) < MAX_SITEMAP_URLS:
            urls += locs(loc)[:MAX_SITEMAP_URLS]
        else:
            urls.append(loc)
    clean = [u for u in (normalize_url(x) for x in urls) if u and same_site(u, root)]
    return list(dict.fromkeys(clean))[:MAX_SITEMAP_URLS]


def _locate(page: Page, el: Element) -> Any:
    if el.selector:
        loc = page.locator(el.selector)
        if loc.count() == 1:
            return loc.first
    if el.locator_role and el.locator_name:
        loc = page.get_by_role(el.locator_role, name=el.locator_name, exact=True)  # type: ignore[arg-type]
        if loc.count() >= 1:
            return loc.first
    return None


def discover_spa_routes(
    page: Page, data: PageData, root: str, report: Report, deadline: Deadline
) -> list[Candidate]:
    """Click nav/aside items that are not plain links and record the URL they lead to."""
    found: list[Candidate] = []
    clickable = [
        e
        for e in data.elements
        if e.region in ("nav", "aside")
        and e.role in ("button", "tab", "menuitem", "link")
        and (
            not e.href
            or e.href.rstrip("/") in (data.url.rstrip("/"), "javascript:void(0)")
            or e.href.endswith("#")
        )
    ][:MAX_SPA_CLICKS_PER_PAGE]
    for el in clickable:
        if deadline.expired():
            break
        if is_blocked(el.name, el.selector, el.locator_name) or is_blocked_href(el.href):
            report.data["clicks_blocked"].append(
                {"phase": "map", "page": data.url, "name": el.name}
            )
            continue
        target = _locate(page, el)
        if target is None:
            continue
        try:
            before = page.url
            target.click(timeout=3000)
            report.data["clicks"].append(
                {"phase": "map", "page": data.url, "ref": el.ref, "name": el.name}
            )
            page.wait_for_timeout(500)
            after = normalize_url(page.url)
            if after and after != normalize_url(before) and same_site(after, root):
                found.append(
                    Candidate(after, el.name, el.region, data.depth + 1, 3.0, origin="spa_click")
                )
            page.goto(data.url)  # reset state; a back-navigation is unreliable in SPAs
            settle(page)
        except Exception as e:
            report.warn(f"spa click failed on {el.name!r}: {type(e).__name__}")
            try:
                page.goto(data.url)
            except Exception:
                break
    return found


def visit(
    page: Page, cand: Candidate, n: int, out_dir: Path, report: Report, root: str
) -> PageData | None:
    """Load and extract one candidate; None when it must be skipped."""
    try:
        response = page.goto(cand.url, wait_until="domcontentloaded")
    except Exception as e:
        report.skip(cand.url, f"load_error: {type(e).__name__}")
        return None
    dismiss_cookie_banner(page)
    blockers = detect_blockers(page, response.status if response else None)
    if blockers["captcha"]:
        report.data["blockers"].append({"url": cand.url, **blockers})
        raise BlockedByChallenge(f"CAPTCHA/Cloudflare challenge at {cand.url}")
    if blockers["http_error"]:
        report.data["blockers"].append({"url": cand.url, **blockers})
        report.skip(cand.url, f"http_error: {blockers['http_error']}")
        return None
    final = normalize_url(page.url)
    if not final or not same_site(final, root):
        report.skip(cand.url, f"redirected_off_site: {page.url}")
        return None
    if blockers["needs_login"]:
        report.data["blockers"].append({"url": cand.url, "needs_login": True})
    data = extract_page(page, n, out_dir, depth=cand.depth, score=cand.score)
    data.url = final if "#" in cand.url else data.url
    return data


def crawl(
    page: Page,
    context: BrowserContext,
    root_url: str,
    out_dir: Path,
    report: Report,
    deadline: Deadline,
    *,
    max_pages: int = 15,
    on_page: Any = None,
) -> tuple[list[PageData], Frontier]:
    """Best-first crawl from root_url: at most max_pages pages, depth <= 2, same domain."""
    root = normalize_url(root_url) or root_url
    frontier = Frontier()
    frontier.add(Candidate(root, "root", "main", 0, 100.0, origin="root"))
    for url in fetch_sitemap_urls(context, root):
        frontier.add(
            Candidate(
                url, "", "main", 1, score_candidate(url, "main", 1, origin="sitemap"), "sitemap"
            )
        )

    pages: list[PageData] = []
    while len(pages) < max_pages and not deadline.expired():
        cand = frontier.pop()
        if cand is None:
            break
        data = visit(page, cand, len(pages) + 1, out_dir, report, root)
        if data is None:
            continue
        pages.append(data)
        if on_page:
            on_page(len(pages), max_pages, data)
        if cand.depth < MAX_DEPTH:
            raw = page.evaluate(LINKS_JS)
            interactive = int(data.signals.get("interactive", 0))
            for found in candidates_from_links(
                raw, page.url, root, cand.depth + 1, report, parent_interactive=interactive
            ):
                frontier.add(found)
            for found in discover_spa_routes(page, data, root, report, deadline):
                frontier.add(found)
    skipped_limit = [u for u in frontier.known if u not in frontier.visited]
    if skipped_limit:
        report.skip(f"{len(skipped_limit)} urls", "not visited: max_pages/time limit")
    return pages, frontier


def save_map(path: Path, frontier: Frontier, pages: list[PageData]) -> None:
    payload = {
        "visited": [p.url for p in pages],
        "candidates": [asdict(c) for c in sorted(frontier.known.values(), key=lambda c: -c.score)],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def pick_candidates_by_description(
    candidates: list[dict[str, Any]], visited: list[str], description: str, limit: int = 2
) -> list[str]:
    """Unvisited known URLs whose text/path share the most words with a free-text description."""
    words = {w for w in re.findall(r"\w{3,}", description.lower())}
    scored = []
    for c in candidates:
        if c["url"] in visited:
            continue
        hay = set(re.findall(r"\w{3,}", (c["text"] + " " + urlparse(c["url"]).path).lower()))
        overlap = len(words & hay)
        if overlap:
            scored.append((overlap, c["score"], c["url"]))
    return [u for _, _, u in sorted(scored, reverse=True)[:limit]]
