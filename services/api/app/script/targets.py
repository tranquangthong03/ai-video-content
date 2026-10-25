"""Which element of the page shows a feature? Found in the page's own language, by whole phrases.

A feature that could not be demonstrated is pointed at (hover + outline) or reached through the
app's own menu. The element is looked up, in this order:
  a) the refs / locators the explorer verified (evidence, demo_steps)       -> lite.py
  b) text the PAGE uses for it: evidence quotes, claimed texts, names of the elements it refers
     to, a name in brackets - never the feature's name translated into another language
  c) a navigation / sidebar entry whose accessible name matches
  d) only then the feature's full name as one phrase
Matching is by whole phrase on word boundaries (accents and case ignored): a single word only when
it is the whole text of the element, no phrase under 4 characters otherwise. Only links, buttons,
tabs, menu items and headings qualify; text inside a paragraph never does.
"""

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from app.browser.auth_detect import is_logout_url
from app.browser.blacklist import is_blocked, is_blocked_href
from app.browser.urls import normalize_url
from app.core.features import fold
from app.core.subpages import is_sensitive, is_subpage
from app.schemas.generated.product_profile import Feature

INTERACTIVE = ("link", "button", "tab", "menuitem")
NAV_REGIONS = ("nav", "aside", "header")
MIN_PHRASE = 4
MAX_PHRASE = 80
BRACKETS = re.compile(r"[(\[]([^()\[\]]{3,60})[)\]]")


def norm(text: str) -> str:
    """Lower-case, accent-free, punctuation as single spaces."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", fold(text)).split())


def phrase_matches(phrase: str, text: str) -> bool:
    """The whole phrase, as whole words, is (part of) the text; short phrases must BE the text."""
    p, t = norm(phrase), norm(text)
    if not p or not t:
        return False
    if p == t:
        return True
    if len(p) < MIN_PHRASE or " " not in p:  # a single word must BE the text, never a part of it
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", t) is not None


def page_phrases(feature: Feature, pages: dict[str, dict[str, Any]]) -> list[str]:
    """What the page itself calls the feature, best first (never the translated name)."""
    phrases: list[str] = []

    def add(text: str | None) -> None:
        text = " ".join((text or "").split())
        if 0 < len(text) <= MAX_PHRASE and text.lower() not in (p.lower() for p in phrases):
            phrases.append(text)

    if feature.showcase_target is not None:
        add(feature.showcase_target.text_quote)
    for ev in feature.evidence:
        add(ev.quote)
        page = pages.get(normalize_url(ev.url) or ev.url)
        element = next(
            (e for e in (page or {}).get("elements", []) if e.get("ref") == ev.ref), None
        )
        if element is not None:
            add(element.get("name") or element.get("text"))
    for match in BRACKETS.findall(feature.name):  # "Tạo đơn xin nghỉ phép (Apply Leave)"
        add(match)
    return phrases


def pseudo_headings(page: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for h in page.get("headings", []):
        text = h.get("text") if isinstance(h, dict) else None
        if text:
            out.append(
                {
                    "ref": None,
                    "role": "heading",
                    "name": text,
                    "text": text,
                    "region": "main",
                    "href": None,
                    "locator": {"role": "heading", "name": text, "text": text},
                }  # fmt: skip
            )
    return out


def usable(element: dict[str, Any]) -> bool:
    """Interactive or a heading, with a name safe to hover (never a sign-out, a side page...)."""
    name = element.get("name") or element.get("text") or ""
    if element.get("role") not in (*INTERACTIVE, "heading") or not name.strip():
        return False
    href = element.get("href")
    if is_blocked(name, interactive=element.get("role") != "heading") or (
        href and (is_blocked_href(href) or is_logout_url(href))
    ):
        return False
    return not (href and (is_subpage(href) or is_sensitive(href)))


@dataclass
class Resolution:
    elements: list[dict[str, Any]]
    page_url: str
    source: str  # "text" (b) | "nav" (c) | "name" (d)


def resolve_by_text(
    feature: Feature, pages: dict[str, dict[str, Any]], home_url: str, page_url: str | None = None
) -> Resolution | None:
    """Steps (b), (c) and (d) of the module docstring over the page of the feature."""
    keys = [normalize_url(page_url or "") or ""] if page_url else []
    keys += [normalize_url(home_url) or home_url, *pages]
    ordered = [k for i, k in enumerate(keys) if k in pages and k not in keys[:i]]
    phrases = page_phrases(feature, pages)
    stages = (
        ("text", phrases, lambda e: e.get("region") not in NAV_REGIONS),
        ("nav", phrases, lambda e: e.get("region") in NAV_REGIONS),
        ("name", [feature.name], lambda e: True),
    )
    for source, wanted, region_ok in stages:
        for key in ordered:
            page = pages[key]
            candidates = [
                e for e in [*page.get("elements", []), *pseudo_headings(page)] if usable(e)
            ]
            hits = [
                e
                for phrase in wanted
                for e in candidates
                if region_ok(e) and phrase_matches(phrase, e.get("name") or e.get("text") or "")
            ]
            unique: list[dict[str, Any]] = []
            for e in hits:
                if not any(
                    u is e or (e.get("ref") and u.get("ref") == e.get("ref")) for u in unique
                ):
                    unique.append(e)
            if unique:
                return Resolution(unique, page.get("url") or key, source)
    return None


def nav_target(element: dict[str, Any], page_url: str, home_url: str) -> str | None:
    """The page an element leads to when it is a plain link to a DIFFERENT page of the app."""
    href = element.get("href")
    if element.get("role") != "link" or not href:
        return None
    target = normalize_url(href, page_url)
    here = normalize_url(page_url) or page_url
    if not target or urlparse(target).netloc.removeprefix("www.") != urlparse(
        here
    ).netloc.removeprefix("www."):
        return None
    if urlparse(target).path.rstrip("/") == urlparse(here).path.rstrip("/"):
        return None
    if (
        is_subpage(target)
        or is_sensitive(target)
        or is_logout_url(target)
        or is_blocked_href(target)
    ):
        return None
    return target
