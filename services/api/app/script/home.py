"""The product's home page as footage: hero, CTA button and the sections of a page.

Everything is taken from what the explorer saw (pages/*.json, kept in lite.PageIndex), never
invented: the hero is the page's h1, the CTA button is a real link/button of the header or main
region, a section is a real heading. Elements are looked up again on the live page when recording.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from app.core.subpages import is_subpage
from app.script.lite import PageIndex

HIGHLIGHT_MS = 1800
CTA_WORDS = (
    "get started", "start", "try", "join", "book", "demo", "free", "buy now", "subscribe",
    "bắt đầu", "dùng thử", "thử", "tham gia", "đăng ký", "đặt lịch", "miễn phí", "liên hệ",
)  # fmt: skip
CTA_REGIONS = ("hero", "header", "nav", "main")
NAV_NOISE = ("log in", "login", "sign in", "đăng nhập", "privacy", "terms", "cookie")


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", _fold(text))}


def heading_locator(level: int, text: str) -> dict[str, Any]:
    """By role and exact name first (headings often share a tag, rarely a name), css/text after."""
    return {"role": "heading", "name": text[:80], "css": f"h{level}", "text": text[:80]}


@dataclass(frozen=True)
class Section:
    url: str
    text: str
    level: int

    @property
    def locator(self) -> dict[str, Any]:
        return heading_locator(self.level, self.text)


def home_page(index: PageIndex, home_url: str) -> dict[str, Any] | None:
    return index.pages.get(PageIndex.key(home_url)) or next(iter(index.pages.values()), None)


def hero_locator(index: PageIndex, home_url: str) -> dict[str, Any] | None:
    """The h1 of the home page (or, without one, its first heading)."""
    page = home_page(index, home_url)
    if page is None:
        return None
    heads = page.get("headings") or []
    pick = next((h for h in heads if h.get("level") == 1), heads[0] if heads else None)
    if pick is None or not pick.get("text"):
        return None
    return heading_locator(int(pick.get("level", 1)), pick["text"])


def cta_button(index: PageIndex, home_url: str, hint: str = "") -> dict[str, Any] | None:
    """The main call-to-action button: the CTA wording first, else the most prominent one."""
    page = home_page(index, home_url)
    if page is None:
        return None
    wanted = _words(hint)
    best: tuple[float, dict[str, Any]] | None = None
    for el in page.get("elements", []):
        name = (el.get("name") or el.get("text") or "").strip()
        if el.get("role") not in ("button", "link") or not 3 <= len(name) <= 40:
            continue
        folded = _fold(name)
        if any(n in folded for n in NAV_NOISE) or not el.get("locator"):
            continue
        score = 0.0
        score += 3.0 * len(wanted & _words(name))
        score += 2.0 if any(w in folded for w in CTA_WORDS) else 0.0
        score += 1.0 if el.get("tag") == "button" or el.get("role") == "button" else 0.0
        if el.get("region") in CTA_REGIONS:
            score += 0.5 - 0.1 * CTA_REGIONS.index(el["region"])
        if score >= 1.0 and (best is None or score > best[0]):  # a button, or CTA wording
            best = (score, el)
    return None if best is None else dict(best[1]["locator"])


def sections(index: PageIndex, url: str) -> list[Section]:
    """Headings of a page, in page order, without duplicates and without side pages."""
    page = index.pages.get(PageIndex.key(url))
    if page is None or is_subpage(page.get("url"), page.get("title")):
        return []
    seen: set[str] = set()
    out: list[Section] = []
    for h in page.get("headings") or []:
        text = (h.get("text") or "").strip()
        level = int(h.get("level") or 2)
        if level not in (1, 2, 3) or len(text) < 4 or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append(Section(page.get("url") or url, text, level))
    return out


def hook_actions(url: str, hero: dict[str, Any]) -> list[dict[str, Any]]:
    """goto the home page, then slowly to the hero block (the camera zooms there and holds)."""
    return [
        {"do": "goto", "url": url},
        {"do": "hover", "url": url, "locator": hero, "target": hero["text"]},
    ]


def cta_actions(url: str, button: dict[str, Any]) -> list[dict[str, Any]]:
    """Scroll to the CTA button and outline it. It is never clicked."""
    target = button.get("name") or button.get("text")
    return [
        {"do": "goto", "url": url},
        {"do": "scroll_to", "url": url, "locator": button, "target": target},
        {"do": "highlight", "url": url, "locator": button, "target": target, "ms": HIGHLIGHT_MS},
    ]


def section_actions(section: Section) -> list[dict[str, Any]]:
    """A tour stop: scroll to the section and outline it."""
    return [
        {"do": "goto", "url": section.url},
        {"do": "scroll_to", "url": section.url, "locator": section.locator, "target": section.text},
        {
            "do": "highlight",
            "url": section.url,
            "locator": section.locator,
            "target": section.text,
            "ms": HIGHLIGHT_MS,
        },
    ]
