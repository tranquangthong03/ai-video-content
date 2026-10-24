"""Two scenes that show the same part of the same page: swap the later one to a new section.

The writer is asked to avoid repeats (script/signature.py), but what is recorded can still land on
the same spot. After recording a scene the producer compares its signature with the earlier scenes:
a repeat is re-recorded on the next unused section (a heading) of the same page, or dropped when the
page has none left (never below the 3 scenes a script needs).
"""

from typing import Any

from app.schemas.generated.scene import Scene
from app.script.home import Section, section_actions, sections
from app.script.lite import PageIndex
from app.script.signature import norm_url

MIN_SCENES = 3


def used_texts(visual: dict[str, Any]) -> set[str]:
    """Headings (lower case) a scene's visual scrolled to or outlined."""
    texts = set()
    for a in visual.get("actions", []):
        loc = a.get("locator") or {}
        if a["do"] in ("scroll_to", "highlight") and loc.get("text"):
            texts.add(loc["text"].lower())
    return texts


def next_section(index: PageIndex | None, url: str | None, used: set[str]) -> Section | None:
    """The first heading of the page (in page order) nobody has shown yet."""
    if index is None or not url:
        return None
    return next((s for s in sections(index, url) if s.text.lower() not in used), None)


def page_of(visual: dict[str, Any]) -> str | None:
    for part in ("actions", "setup"):
        goto = next(
            (a["url"] for a in visual.get(part, []) if a["do"] == "goto" and a.get("url")), None
        )
        if goto:
            return goto
    return visual.get("page")


def swap_scene(
    scene: Scene, index: PageIndex | None, used: set[str]
) -> tuple[Scene, Section] | None:
    """The scene re-aimed at the next unused section of its own page, or None."""
    root = scene.root
    visual = root.visual.model_dump()
    section = next_section(index, page_of(visual), used)
    if section is None:
        return None
    data = root.model_dump()
    data["visual"] = {
        "mode": "recording",
        "page": section.url,
        "setup": [],
        "show_setup": False,
        "actions": section_actions(section),
    }
    return Scene.model_validate(data), section


def same_page(a: str | None, b: str | None) -> bool:
    return norm_url(a) == norm_url(b)
