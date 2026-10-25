"""showcase_lite: a short recording that only points at where a feature lives.

For a feature that could not be demonstrated (failed / unverified) the script still shows the
app: go to the page, optionally recreate the data that makes its controls appear (a hidden setup
taken from a verified feature on the same page, with different sample text), hover slowly over
one to three of the feature's elements and outline them. It never clicks the unverified feature.
Elements are located at recording time (app/browser/locate), not from stored coordinates.

Encoded with the existing action kinds: hover with `ms` (a slow hover) and one highlight whose
`text` is "group" (outline the boxes of the hovers just made).
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.browser.urls import normalize_url
from app.schemas.generated.product_profile import DemoStep, Feature, ProductProfile

HIGHLIGHT_MS = 1800
HOVER_DWELL_MS = 300
MAX_ELEMENTS = 2  # 1-3 allowed; two keeps the scene near 6 s of footage
MIN_WORDS = 10  # a pointing scene lasts about 5 s, so its voiceover cannot be much shorter
GROUP = "group"
ALT_TEXTS = (
    "Gọi điện cho khách hàng",
    "Nộp báo cáo tuần",
    "Đặt lịch họp nhóm",
    "Chuẩn bị tài liệu hướng dẫn",
    "Dọn dẹp bàn làm việc",
    "Lên kế hoạch cho tuần sau",
)
POINTABLE_ROLES = ("link", "button", "tab", "menuitem", "option", "switch", "checkbox", "radio")
STOP_WORDS = {"tính", "năng", "theo", "trạng", "thái", "việc", "cần", "làm", "the", "and", "for"}


@dataclass
class PageIndex:
    """What the explorer saw, indexed for lookups by (page url, ref)."""

    pages: dict[str, dict[str, Any]] = field(default_factory=dict)

    @staticmethod
    def key(url: str | None) -> str:
        return normalize_url(url or "") or (url or "")

    def element(self, url: str | None, ref: str | None) -> dict[str, Any] | None:
        page = self.pages.get(self.key(url))
        if page is None or not ref:
            return None
        return next((e for e in page.get("elements", []) if e.get("ref") == ref), None)


def load_page_index(explore_dir: Path) -> PageIndex:
    index = PageIndex()
    for file in sorted((explore_dir / "pages").glob("*.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        index.pages[PageIndex.key(data.get("url"))] = data
    return index


@dataclass
class LiteContext:
    profile: ProductProfile
    pages: PageIndex
    home_url: str
    used_texts: set[str] = field(
        default_factory=set
    )  # sample texts already typed by earlier scenes


def keywords(name: str) -> list[str]:
    """Main words of a feature name, longest first (to look an element up by its text)."""
    words = [w for w in re.findall(r"[\wÀ-ỹ]{4,}", name.lower()) if w not in STOP_WORDS]
    return sorted(dict.fromkeys(words), key=len, reverse=True)[:2]


def _pointable(element: dict[str, Any]) -> bool:
    return element.get("role") in POINTABLE_ROLES and bool(
        element.get("name") or element.get("text")
    )


def pick_elements(feature: Feature, ctx: LiteContext) -> tuple[list[dict[str, Any]], str | None]:
    """Up to three elements to point at (evidence first, else its name), and their page."""
    found: list[dict[str, Any]] = []
    page_url: str | None = None
    for ev in feature.evidence:
        element = ctx.pages.element(ev.url, ev.ref)
        if (
            element is None
            or not _pointable(element)
            or any(e["ref"] == element["ref"] for e in found)
        ):
            continue
        found.append(element)
        page_url = page_url or ev.url
    if found:
        return found[:MAX_ELEMENTS], page_url
    # nothing the explorer verified: the callers go on with the feature's own steps, then with the
    # words the page itself uses (script/targets.py) - never with loose words of its name
    page_url = next((e.url for e in feature.evidence if e.source == "app_action"), None) or (
        feature.evidence[0].url if feature.evidence else ctx.home_url
    )
    return [], page_url


POINT_STEPS = ("click", "dblclick", "hover")  # steps of a failed feature that name a control


def own_pointing(
    feature: Feature,
) -> tuple[list[dict[str, Any]], list[DemoStep], str | None] | None:
    """Controls and preparation from the feature's own recorded steps (hovered, never clicked).

    A failed feature often still has the steps the explorer tried: the control it clicked is exactly
    what to point at, and the typing before it is the data that makes the control appear.
    """
    steps = feature.demo_steps
    first = next((i for i, s in enumerate(steps) if s.do in POINT_STEPS and s.locator), None)
    if first is None:
        return None
    elements: list[dict[str, Any]] = []
    for s in steps[first:]:
        if s.do not in POINT_STEPS or s.locator is None:
            continue
        loc = s.locator.model_dump()
        if any(e["locator"] == loc for e in elements):
            continue
        name = s.locator.name or s.locator.text
        elements.append(
            {"ref": s.ref, "name": name, "text": name, "locator": loc, "role": s.locator.role}
        )
    prep = [s for s in steps[:first] if s.do in ("goto", "type") or (s.do == "click" and s.locator)]
    page = next((s.url for s in steps if s.do == "goto" and s.url), None)
    return elements[:MAX_ELEMENTS], prep, page


def retext(steps: list[DemoStep], ctx: LiteContext) -> list[DemoStep]:
    """Copies of the steps whose typed texts are new samples (not the ones earlier scenes typed)."""
    copies = [s.model_copy(deep=True) for s in steps]
    fresh = [t for t in ALT_TEXTS if t.lower() not in ctx.used_texts] or list(ALT_TEXTS)
    for step in copies:
        if step.do == "type":
            step.text = fresh[0]
            ctx.used_texts.add(fresh[0].lower())
            fresh = fresh[1:] or list(ALT_TEXTS)
    return copies


def needs_data(elements: list[dict[str, Any]]) -> bool:
    """Elements found only after the explorer's stateful step (refs like s1e3) need data first."""
    return any(str(e.get("ref") or "").startswith("s") for e in elements)


def pick_setup(page_url: str, ctx: LiteContext) -> list[DemoStep] | None:
    """Steps of a verified interaction feature on the same page that create sample data."""
    target = PageIndex.key(page_url)
    candidates = []
    for f in ctx.profile.features:
        if f.demo_kind != "interaction" or f.requires_setup:
            continue
        first = next((s.url for s in f.demo_steps if s.do == "goto" and s.url), None)
        has_type = any(s.do == "type" and s.locator is not None for s in f.demo_steps)
        if has_type and PageIndex.key(first) == target:
            candidates.append(f)
    if not candidates:
        return None
    best = max(candidates, key=lambda f: f.importance)
    return retext(best.demo_steps, ctx)


def lite_actions(
    elements: list[dict[str, Any]], page_url: str, with_goto: bool
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = [{"do": "goto", "url": page_url}] if with_goto else []
    for element in elements:
        actions.append(
            {
                "do": "hover",
                "url": page_url,
                "locator": element["locator"],
                "target": element.get("name") or element.get("text"),
                "ms": HOVER_DWELL_MS,
            }
        )
    last = elements[-1]
    actions.append(
        {
            "do": "highlight",
            "url": page_url,
            "locator": last["locator"],
            "target": last.get("name") or last.get("text"),
            "text": GROUP,
            "ms": HIGHLIGHT_MS,
        }
    )
    return actions


def is_lite(visual: Any) -> bool:
    """True for a visual built by this module (its highlight outlines the hovered group)."""
    return any(a.do == "highlight" and a.text == GROUP for a in visual.actions)
