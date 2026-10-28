"""Site mapping: find links (nav, sitemap, SPA clicks), rank them, crawl by score.

Scope: a start URL with a real path (/examples/react/dist/) crawls only links under that path
unless scope="domain". Plain anchors (/#pricing) are sections of a page, never pages.
Template pages (/for-*, /vs-*, /blog/*) are visited at most twice per group, and at least
MIN_DEMO_PAGES slots go to the pages that look most like the product itself (demo/app/dashboard).
"""

import heapq
import itertools
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import BrowserContext, Page

from app.browser.auth_detect import LoginRequired, detect_login, is_login_path
from app.browser.blacklist import is_blocked, is_blocked_href
from app.browser.locate import Unsafe, check_clickable, resolve
from app.browser.page_utils import detect_blockers, dismiss_cookie_banner
from app.browser.urls import (
    anchor_of,
    in_scope,
    normalize_url,
    path_prefix,
    related_domain,
    same_site,
)
from app.core.subpages import is_sensitive, is_sensitive_text, is_subpage, is_subpage_text
from app.core.textmatch import description_words, words_match
from app.explorer.extract import extract_page, settle
from app.explorer.models import PageData
from app.explorer.report import Deadline, Report

__all__ = ["normalize_url", "same_site"]  # re-exported: tests and callers import them from here

MAX_DEPTH = 2
MAX_SITEMAP_URLS = 50
MAX_SPA_CLICKS_PER_PAGE = 12
MAX_PER_GROUP = 2
MIN_GROUP_SIZE = 3  # a "template group" needs at least this many known URLs
MIN_DEMO_PAGES = 3
MAX_OUT_OF_SCOPE_LISTED = 50
MAX_TARGETED_PAGES = 3  # pages looked at for one "explore more" request

POSITIVE_PATH = re.compile(
    r"features?|dashboard|create|new|editor|app|product|solutions?|use-?cases?|tools?|pricing", re.I
)
NEGATIVE_PATH = re.compile(
    r"blog|privacy|terms|careers?|jobs|log-?in|sign-?in|signin|logout|billing|payment|cookie|legal|press|changelog",
    re.I,
)
# Words on the link itself that point at the product: strongest signal for finding the real UI
DEMO_TEXT = re.compile(
    r"\b(demo|live demo|try|playground|get started|app|dashboard|dùng thử|trải nghiệm)\b", re.I
)
# Link text that points at the product itself: always kept, whatever region the link is in
KEEP_TEXT = re.compile(r"\b(demo|live demo|try|playground|dùng thử|trải nghiệm)\b", re.I)
# Login/registration pages are ordinary pages, never "demo" pages
AUTH_PATH = re.compile(r"/(log-?in|sign-?in|register|sign-?up|auth)(/|$)", re.I)
INFO_TEXT = re.compile(r"\b(pricing|features?|giá|bảng giá|tính năng)\b", re.I)

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
    demo: bool = False  # looks like the product itself (demo/app/dashboard link or path)


def is_auth_url(url: str) -> bool:
    return bool(AUTH_PATH.search(urlparse(url).path))


def is_demo_like(url: str, text: str) -> bool:
    path = urlparse(url).path
    if is_auth_url(url):
        return False
    return bool(
        DEMO_TEXT.search(text) or re.search(r"/(demo|app|dashboard|playground)\b", path, re.I)
    )


def score_candidate(
    url: str,
    region: str,
    depth: int,
    *,
    origin: str = "link",
    parent_interactive: int = 0,
    text: str = "",
) -> float:
    """Higher = visit sooner: region, path words, link text, depth, and parent interactivity."""
    score = {"nav": 3.0, "aside": 3.0, "header": 1.5, "footer": 0.2}.get(region, 0.0)
    path = urlparse(url).path + urlparse(url).fragment
    if POSITIVE_PATH.search(path):
        score += 2.0
    if NEGATIVE_PATH.search(path):
        score -= 4.0
    if DEMO_TEXT.search(text) and not is_auth_url(url):
        score += 4.0
    elif INFO_TEXT.search(text):
        score += 2.5
    score -= 0.5 * depth
    score += min(1.0, parent_interactive / 60)
    if origin == "sitemap":
        score += 0.5
    return round(score, 2)


def template_keys(url: str) -> list[str]:
    """Keys of the path templates a URL belongs to: /for-*, /*-web-analytics, /blog/*, /docs/*/*."""
    segments = [s for s in urlparse(url).path.split("/") if s]
    if not segments:
        return []
    if len(segments) >= 2:
        return ["/" + segments[0] + "/" + "/".join("*" for _ in segments[1:])]
    tokens = segments[0].split("-")
    keys = []
    if len(tokens) >= 2:
        keys.append(f"/{tokens[0]}-*")
    if len(tokens) >= 3:
        keys.append("/*-" + "-".join(tokens[-2:]))
    return keys


class Frontier:
    """Best-first queue that never returns a URL twice and limits pages per template group."""

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, Candidate]] = []
        self._demo_heap: list[tuple[float, int, Candidate]] = []
        self._counter = itertools.count()
        self.known: dict[str, Candidate] = {}
        self.visited: set[str] = set()
        self.group_visited: dict[str, int] = {}
        self.grouped_skips: dict[str, int] = {}

    def add(self, cand: Candidate) -> bool:
        existing = self.known.get(cand.url)
        if existing and existing.score >= cand.score:
            return False
        self.known[cand.url] = cand
        if cand.url not in self.visited:
            entry = (-cand.score, next(self._counter), cand)
            heapq.heappush(self._heap, entry)
            if cand.demo:
                heapq.heappush(self._demo_heap, entry)
        return True

    def _group_full(self, url: str) -> str | None:
        """The template key whose quota is used up for this URL, if any."""
        for key in template_keys(url):
            size = sum(1 for u in self.known if key in template_keys(u))
            if size >= MIN_GROUP_SIZE and self.group_visited.get(key, 0) >= MAX_PER_GROUP:
                return key
        return None

    def pop(self, *, prefer_demo: bool = False) -> Candidate | None:
        heaps = [self._demo_heap, self._heap] if prefer_demo else [self._heap]
        for heap in heaps:
            while heap:
                _, _, cand = heapq.heappop(heap)
                if cand.url in self.visited or self.known.get(cand.url) is not cand:
                    continue
                full = self._group_full(cand.url)
                if full:
                    self.visited.add(cand.url)  # skipped for good: the group has enough samples
                    self.grouped_skips[full] = self.grouped_skips.get(full, 0) + 1
                    continue
                self.visited.add(cand.url)
                for key in template_keys(cand.url):
                    self.group_visited[key] = self.group_visited.get(key, 0) + 1
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
    prefix: str | None = None,
) -> list[Candidate]:
    """Raw anchors -> scored candidates.

    Dropped: other sites, blacklisted links, links outside the path scope (listed in the report),
    and `#id` links to the same page (those are sections, recorded by the extractor).
    """
    nav_like = [lk for lk in raw_links if lk["region"] != "main"]
    # Pages without nav/header/footer links (single-page apps, tools): fall back to in-page links
    pool = nav_like if len(nav_like) >= 3 else raw_links
    # Links that point at the product itself (demo, try, playground...) are kept from any region
    kept = [
        lk for lk in raw_links if KEEP_TEXT.search(lk["text"]) and not any(lk is p for p in pool)
    ]
    out: dict[str, Candidate] = {}
    here = normalize_url(page_url)
    for link in [*pool, *kept]:
        url = normalize_url(link["href"], page_url)
        demo_text = bool(KEEP_TEXT.search(link["text"]))
        # a demo link may live on a subdomain of the root domain (demo.example.com)
        allowed_site = bool(url) and (
            same_site(url, root) or (demo_text and related_domain(url, root))  # type: ignore[arg-type]
        )
        if not url or not allowed_site:
            continue
        if anchor_of(link["href"]) and url == here:
            report.data["anchor_sections"] += 1
            continue
        if is_blocked(link["text"]) or is_blocked_href(url):
            report.skip(url, f"blacklist: {link['text']!r} -> {url}")
            continue
        subdomain_demo = demo_text and not same_site(url, root)
        if not subdomain_demo and not in_scope(url, root, prefix):
            listed = report.data["out_of_scope"]
            if len(listed) < MAX_OUT_OF_SCOPE_LISTED and not any(x["url"] == url for x in listed):
                listed.append({"url": url, "text": link["text"]})
            continue
        score = score_candidate(
            url, link["region"], depth, parent_interactive=parent_interactive, text=link["text"]
        )
        if url not in out or out[url].score < score:
            out[url] = Candidate(
                url,
                link["text"],
                link["region"],
                depth,
                score,
                demo=is_demo_like(url, link["text"]),
            )
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


def scope_question(context: BrowserContext, first: PageData, root: str, prefix: str) -> str | None:
    """If the domain's home page describes something else than the app at `prefix`, a question
    for the user (no LLM: word overlap of titles/descriptions)."""
    base = f"{urlparse(root).scheme}://{urlparse(root).netloc}/"
    try:
        res = context.request.get(base, timeout=8000)
        html = res.text() if res.ok else ""
    except Exception:
        return None
    title = (re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I) or [None, ""])[1].strip()
    meta = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)', html, re.I)
    home = f"{title} {meta.group(1) if meta else ''}"
    mine = f"{first.title} {first.meta_description} " + " ".join(h.text for h in first.headings[:5])

    def words(text: str) -> set[str]:
        return set(re.findall(r"\w{4,}", text.lower()))

    a, b = words(home), words(mine)
    if not a or not b or len(a & b) / len(a | b) >= 0.2:
        return None
    host = urlparse(root).hostname or "domain"
    return (
        f"Bạn muốn làm video cho ứng dụng tại {prefix} hay cho toàn bộ {host}? "
        f"(trang chủ {host} mô tả: «{title[:80]}»)"
    )


def discover_spa_routes(
    page: Page, data: PageData, root: str, report: Report, deadline: Deadline, prefix: str | None
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
        resolution = resolve(page, el.spec(), retry=False)
        report.record_locate(f"map:{el.name}", resolution.strategy, resolution.tried)
        if resolution.target is None:
            report.block("map", el.name, "not_found", "; ".join(resolution.tried), page=data.url)
            continue
        try:
            check_clickable(resolution.target.info(), root, scope_prefix=prefix, strict=False)
        except Unsafe as e:
            report.block("map", el.name, e.reason, e.detail, page=data.url)
            continue
        try:
            before = page.url
            resolution.target.click(timeout=3000)
            report.data["clicks"].append(
                {
                    "phase": "map",
                    "page": data.url,
                    "ref": el.ref,
                    "name": el.name,
                    "strategy": resolution.strategy,
                }
            )
            page.wait_for_timeout(500)
            after = normalize_url(page.url)
            if after and after != normalize_url(before) and in_scope(after, root, prefix):
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


def skip_sensitive(report: Report, url: str) -> None:
    """Note a page left unexplored because it is settings / billing / admin... (signed-in only)."""
    skipped = report.data.setdefault("sensitive_skipped", [])
    if url not in skipped:
        skipped.append(url)
    report.skip(url, "sensitive page (signed in)")


def drop_sensitive(
    candidates: list[Candidate], report: Report, authenticated: bool
) -> list[Candidate]:
    if not authenticated:
        return candidates
    keep = []
    for c in candidates:
        if is_sensitive(c.url) or is_sensitive_text(c.text):
            skip_sensitive(report, c.url)
        else:
            keep.append(c)
    return keep


def visit(
    page: Page,
    cand: Candidate,
    n: int,
    out_dir: Path,
    report: Report,
    root: str,
    *,
    authenticated: bool = False,
) -> PageData | None:
    """Load and extract one candidate; None when it must be skipped.

    Raises LoginRequired when the start page asks for a sign-in, or any page does while we hold a
    session (it has expired)."""
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
    signal = detect_login(page, cand.url, response.status if response else None)
    if signal is not None and authenticated and cand.origin != "root" and is_login_path(cand.url):
        # a link to the sign-in page ("Log in" in a header) is not a sign that the session is gone
        report.skip(cand.url, "login_page")
        return None
    if signal is not None and (cand.origin == "root" or authenticated):
        reason = "session_expired" if authenticated else signal.reason
        raise LoginRequired(signal.login_url, reason, target_url=cand.url)
    if blockers["http_error"]:
        report.data["blockers"].append({"url": cand.url, **blockers})
        report.skip(cand.url, f"http_error: {blockers['http_error']}")
        return None
    final = normalize_url(page.url)
    on_site = bool(final) and (
        same_site(final, root) or (cand.demo and related_domain(final, root))  # type: ignore[arg-type]
    )
    if not final or not on_site:
        report.skip(cand.url, f"redirected_off_site: {page.url}")
        return None
    if blockers["needs_login"]:
        report.data["blockers"].append({"url": cand.url, "needs_login": True})
    if authenticated and is_sensitive(final, page.title()):
        skip_sensitive(report, final)  # e.g. a redirect or a page whose title gives it away
        return None
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
    scope: str = "path",
    authenticated: bool = False,
) -> tuple[list[PageData], Frontier]:
    """Best-first crawl: at most max_pages pages, depth <= 2, same domain (and path if scoped)."""
    root = normalize_url(root_url) or root_url
    prefix = path_prefix(root) if scope == "path" else None
    report.data["scope"] = {"mode": scope, "path_prefix": prefix}
    frontier = Frontier()
    frontier.add(Candidate(root, "root", "main", 0, 100.0, origin="root"))
    for url in fetch_sitemap_urls(context, root):
        if not in_scope(url, root, prefix):
            continue
        frontier.add(
            Candidate(
                url, "", "main", 1, score_candidate(url, "main", 1, origin="sitemap"), "sitemap",
                demo=is_demo_like(url, ""),
            )
        )  # fmt: skip

    pages: list[PageData] = []
    demo_visited = 0
    while len(pages) < max_pages and not deadline.expired():
        remaining = max_pages - len(pages)
        # keep MIN_DEMO_PAGES slots for the pages that look most like the product itself
        need_demo = max(0, MIN_DEMO_PAGES - demo_visited)
        cand = frontier.pop(prefer_demo=need_demo >= remaining and need_demo > 0)
        if cand is None:
            break
        data = visit(page, cand, len(pages) + 1, out_dir, report, root, authenticated=authenticated)
        if data is None:
            continue
        pages.append(data)
        demo_visited += int(cand.demo)
        if on_page:
            on_page(len(pages), max_pages, data)
        if cand.depth < MAX_DEPTH:
            raw = page.evaluate(LINKS_JS)
            interactive = int(data.signals.get("interactive", 0))
            links = candidates_from_links(
                raw, page.url, root, cand.depth + 1, report,
                parent_interactive=interactive, prefix=prefix,
            )  # fmt: skip
            spa = discover_spa_routes(page, data, root, report, deadline, prefix)
            for found in drop_sensitive([*links, *spa], report, authenticated):
                frontier.add(found)
    report.data["grouped_pages"] = dict(frontier.grouped_skips)
    unvisited = [u for u in frontier.known if u not in frontier.visited]
    if unvisited:
        report.skip(f"{len(unvisited)} urls", "not visited: max_pages/time limit")
    if prefix and pages and report.data["out_of_scope"]:
        question = scope_question(context, pages[0], root, prefix)
        if question:
            report.data["scope_question"] = question
    return pages, frontier


def save_map(path: Path, frontier: Frontier, pages: list[PageData]) -> None:
    payload = {
        "visited": [p.url for p in pages],
        "candidates": [asdict(c) for c in sorted(frontier.known.values(), key=lambda c: -c.score)],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def relevance(description: str, text: str, url: str) -> int:
    """How many words of the description appear (fuzzily) in the link text or the URL path."""
    wanted = description_words(description)
    hay = description_words(text + " " + re.sub(r"[-_/.]+", " ", urlparse(url).path))
    return sum(1 for w in wanted if any(words_match(w, h) for h in hay))


def pick_candidates_by_description(
    candidates: list[dict[str, Any]],
    visited: list[str],
    description: str,
    limit: int = 3,
    *,
    authenticated: bool = False,
) -> list[str]:
    """Unvisited, non-side-page known URLs whose link text/path best match a description."""
    scored = []
    for c in candidates:
        if c["url"] in visited or is_auth_url(c["url"]):
            continue
        if is_subpage(c["url"]) or is_subpage_text(c["text"]):
            continue
        if authenticated and (is_sensitive(c["url"]) or is_sensitive_text(c["text"])):
            continue
        overlap = relevance(description, c["text"], c["url"])
        if overlap:
            scored.append((overlap, c["score"], c["url"]))
    return [u for _, _, u in sorted(scored, reverse=True)[:limit]]


def explore_targeted(
    page: Page,
    seeds: list[str],
    root: str,
    out_dir: Path,
    report: Report,
    *,
    first_n: int,
    description: str | None = None,
    visited: list[str] | None = None,
    max_pages: int = MAX_TARGETED_PAGES,
    authenticated: bool = False,
) -> list[PageData]:
    """Look at the pages a user asked for: the seeds first, then links next to them.

    At most max_pages pages in all, all under the path prefix of the first seed; side pages
    (sign in, checkout...) are never visited. With a description, follow-up links are ranked by
    how well they match it.
    """
    seen = set(visited or [])
    prefix = path_prefix(seeds[0]) if seeds else None
    queue = [Candidate(u, "", "main", 1, 5.0, "user") for u in seeds]
    pages: list[PageData] = []
    while queue and len(pages) < max_pages:
        cand = queue.pop(0)
        if cand.url in seen:
            continue
        seen.add(cand.url)
        data = visit(
            page, cand, first_n + len(pages), out_dir, report, root, authenticated=authenticated
        )
        if data is None:
            continue
        if is_subpage(data.url, data.title):
            report.skip(cand.url, "side page (sign in / checkout...)")
            continue
        pages.append(data)
        found = candidates_from_links(
            page.evaluate(LINKS_JS), page.url, root, 2, report, prefix=prefix
        )
        found = [
            c
            for c in found
            if c.url not in seen
            and not is_auth_url(c.url)
            and not is_subpage(c.url)
            and not is_subpage_text(c.text)
        ]
        found = drop_sensitive(found, report, authenticated)
        found.sort(
            key=lambda c: (-relevance(description or "", c.text, c.url), -c.score),
        )
        queue += found
    return pages
