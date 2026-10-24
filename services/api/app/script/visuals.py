"""Scene visuals are never written by the LLM: they come from the verified data in the profile.

feature_demo with demo_kind
  interaction / navigation -> recording, actions = the feature's demo_steps (verified locators),
                              with the setup part (requires_setup) split into visual.setup;
  showcase                 -> recording: goto, scroll_to and highlight of the showcase target;
  failed / unverified      -> not demonstrable: a screenshot, with a warning.
hook -> screenshot of the home page; before_after and cta -> template (drawn by the renderer).
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.schemas.generated.product_profile import DemoStep, Feature, ProductProfile
from app.script.lite import (
    LiteContext,
    lite_actions,
    needs_data,
    own_pointing,
    pick_elements,
    pick_setup,
    retext,
)

HIGHLIGHT_MS = 1800
ZOOM_STEPS = ("click", "dblclick")
# what the viewer watches (goto and setup are not counted); each is followed by a 1.5 s hold
MAIN_ACTIONS = (
    "click",
    "dblclick",
    "right_click",
    "type",
    "hover",
    "upload",
    "scroll_to",
    "highlight",
)
MAX_MAIN_ACTIONS = 3


def main_count(actions: list[dict[str, Any]]) -> int:
    return sum(1 for a in actions if a["do"] in MAIN_ACTIONS)


def cap_main_actions(
    actions: list[dict[str, Any]], warnings: list[str], label: str
) -> list[dict[str, Any]]:
    """Keep the first MAX_MAIN_ACTIONS main actions of a scene (more would be rushed on screen)."""
    kept: list[dict[str, Any]] = []
    seen = dropped = 0
    for a in actions:
        if a["do"] in MAIN_ACTIONS:
            if seen >= MAX_MAIN_ACTIONS:
                dropped += 1
                continue
            seen += 1
        kept.append(a)
    if dropped:
        warnings.append(
            f"{label}: chỉ giữ {MAX_MAIN_ACTIONS} thao tác chính mỗi cảnh, bỏ {dropped}"
        )
    return kept


@dataclass
class VisualResult:
    visual: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def load_setup_counts(explore_dir: Path, profile: ProductProfile) -> dict[str, int]:
    """feature id -> number of leading demo_steps that only recreate a state.

    The stateful step of the explorer stores those steps on the page it found the feature on
    (pages/*.json -> setup_steps); the feature's demo_steps start with them. Verified by comparing
    the steps, so a mismatch yields no entry (the caller then treats every step as an action).
    """
    pages: list[dict[str, Any]] = []
    for file in sorted((explore_dir / "pages").glob("*.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("setup_steps"):
            pages.append(data)
    counts: dict[str, int] = {}
    for feature in profile.features:
        if not feature.requires_setup:
            continue
        for page in pages:
            setup = page["setup_steps"]
            head = feature.demo_steps[: len(setup)]
            if len(head) == len(setup) and all(
                _same(a, b) for a, b in zip(head, setup, strict=True)
            ):
                counts[feature.id] = len(setup)
                break
    return counts


def _same(step: DemoStep, raw: dict[str, Any]) -> bool:
    return (step.do, step.ref, step.text) == (raw.get("do"), raw.get("ref"), raw.get("text"))


def step_to_action(step: DemoStep) -> dict[str, Any] | None:
    """A verified DemoStep as a BrowserAction; None when it cannot be replayed (no locator)."""
    if step.do in ("goto",):
        return {"do": "goto", "url": step.url}
    if step.do == "wait":
        return {"do": "wait", "ms": 800}
    if step.do == "scroll" and step.locator is None:
        return {"do": "scroll", "ms": 700}
    if step.locator is None:
        return None
    action: dict[str, Any] = {
        "do": step.do,
        "url": step.url,
        "locator": step.locator.model_dump(),
        "target": step.locator.name or step.locator.text,
        "zoom": step.do in ZOOM_STEPS,
    }
    if step.text is not None:
        action["text"] = step.text
    if step.file is not None:
        action["file"] = step.file
    return action


def _actions(steps: list[DemoStep], warnings: list[str], feature: Feature) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for step in steps:
        action = step_to_action(step)
        if action is None:
            warnings.append(f"{feature.id}: bỏ qua một bước «{step.do}» vì thiếu locator")
            continue
        out.append(action)
    return out


def _interaction_visual(feature: Feature, setup_len: int | None, show_setup: bool) -> VisualResult:
    warnings: list[str] = []
    steps = list(feature.demo_steps)
    setup: list[dict[str, Any]] = []
    if feature.requires_setup:
        if setup_len and 0 < setup_len < len(steps):
            setup = _actions(steps[:setup_len], warnings, feature)
            steps = steps[setup_len:]
            # the own steps were recorded after a reload; replaying that goto would lose the setup
            if steps and steps[0].do == "goto" and steps[0].url == setup_goto_url(setup):
                steps = steps[1:]
        else:
            warnings.append(
                f"{feature.id}: không tách được phần chuẩn bị (setup), "
                "dùng toàn bộ bước làm thao tác"
            )
    actions = cap_main_actions(_actions(steps, warnings, feature), warnings, feature.id)
    visual: dict[str, Any] = {
        "mode": "recording",
        "page": next((s.url for s in feature.demo_steps if s.do == "goto" and s.url), None),
        "actions": actions,
        "setup": setup,
        "show_setup": bool(show_setup and setup),
    }
    return VisualResult(visual, warnings)


def setup_goto_url(setup: list[dict[str, Any]]) -> str | None:
    return next((a["url"] for a in setup if a["do"] == "goto"), None)


def _showcase_visual(feature: Feature) -> VisualResult | None:
    target = feature.showcase_target
    if target is None:
        return None
    locator = {"css": target.selector, "text": target.text_quote[:80]}
    return VisualResult(
        {
            "mode": "recording",
            "page": target.url,
            "actions": [
                {"do": "goto", "url": target.url},
                {
                    "do": "scroll_to",
                    "url": target.url,
                    "locator": locator,
                    "target": target.text_quote,
                },
                {
                    "do": "highlight",
                    "url": target.url,
                    "locator": locator,
                    "target": target.text_quote,
                    "ms": HIGHLIGHT_MS,
                },
            ],
        }
    )


def _lite_visual(feature: Feature, lite: LiteContext, scene_id: str) -> VisualResult | None:
    """showcase_lite: hover slowly over the feature's elements and outline them; never click."""
    elements, page_url = pick_elements(feature, lite)
    steps: list[DemoStep] | None = None
    if not any(e["ref"] for e in elements):  # nothing the explorer saw: use the steps it tried
        own = own_pointing(feature)
        if own is not None:
            elements, prep, own_page = own
            page_url = own_page or page_url
            steps = retext(prep, lite) if prep else None
    elif needs_data(elements) and page_url is not None:
        steps = pick_setup(page_url, lite)
    if not elements or page_url is None:
        return None
    warnings: list[str] = []
    setup: list[dict[str, Any]] = []
    if steps:
        setup = [a for a in (step_to_action(s) for s in steps) if a is not None]
    elif needs_data(elements):
        warnings.append(f"{scene_id}: «{feature.id}» cần dữ liệu nhưng không có setup cùng trang")
    visual = {
        "mode": "recording",
        "page": page_url,
        "setup": setup,
        "show_setup": False,
        "actions": lite_actions(elements, page_url, with_goto=not setup),
    }
    return VisualResult(visual, warnings)


def screenshot_visual(home_url: str) -> dict[str, Any]:
    return {"mode": "screenshot", "page": home_url, "actions": []}


def template_visual() -> dict[str, Any]:
    return {"mode": "template", "page": None, "actions": []}


def demo_visual(
    feature: Feature | None,
    home_url: str,
    *,
    setup_len: int | None,
    show_setup: bool,
    scene_id: str,
    lite: LiteContext | None = None,
) -> VisualResult:
    """Visual of a feature_demo scene, by the feature's verified demo_kind."""
    if feature is None:
        return VisualResult(
            screenshot_visual(home_url),
            [f"{scene_id}: tính năng không tồn tại, dùng ảnh trang chủ"],
        )
    if feature.demo_kind in ("interaction", "navigation"):
        result = _interaction_visual(feature, setup_len, show_setup)
        if result.visual["actions"] or result.visual["setup"]:
            return result
        result.warnings.append(f"{scene_id}: «{feature.id}» không có bước nào chạy lại được")
        return VisualResult(screenshot_visual(home_url), result.warnings)
    # showcase, failed or unverified: highlight the section when the page has one, else point at it
    showcase = _showcase_visual(feature)
    if showcase is not None:
        return showcase
    kind = feature.demo_kind or "chưa kiểm chứng"
    if lite is not None:
        found = _lite_visual(feature, lite, scene_id)
        if found is not None:
            return found
    return VisualResult(
        screenshot_visual(home_url),
        [f"{scene_id}: «{feature.id}» có demo_kind {kind}, không quay được nên dùng ảnh trang chủ"],
    )


def visual_for_scene(
    scene_type: str,
    feature: Feature | None,
    home_url: str,
    *,
    setup_len: int | None = None,
    show_setup: bool = False,
    scene_id: str = "",
    lite: LiteContext | None = None,
) -> VisualResult:
    if scene_type == "feature_demo":
        return demo_visual(
            feature,
            home_url,
            setup_len=setup_len,
            show_setup=show_setup,
            scene_id=scene_id,
            lite=lite,
        )
    if scene_type == "hook":
        return VisualResult(screenshot_visual(home_url))
    return VisualResult(template_visual())
