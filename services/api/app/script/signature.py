"""A scene's "visual signature": which page and which part of it the viewer is looking at.

URL (query dropped, hash route kept) plus the cell of a 4x4 grid that holds the focus point.
Two scenes with the same signature show the same thing; the writer is asked to avoid that, and the
producer checks again from what was really recorded and swaps or drops the later scene.
"""

from typing import Any
from urllib.parse import urlparse

GRID = 4
EXPLORER_SIZE = (1920, 1080)  # coordinates in verified locators come from the explorer's viewport
MAIN = ("click", "dblclick", "right_click", "type", "hover", "upload", "scroll_to", "highlight")
MAIN_FOCUS = ("click", "dblclick", "type", "hover", "highlight", "section")


def norm_url(url: str | None) -> str:
    """scheme://host/path without query or trailing slash; a #/hash route is kept."""
    if not url:
        return ""
    p = urlparse(url)
    path = p.path.rstrip("/")
    return f"{p.scheme}://{p.netloc}{path}" + (f"#{p.fragment}" if p.fragment else "")


def cell(cx: float, cy: float, size: tuple[float, float]) -> str:
    col = min(GRID - 1, max(0, int(cx / size[0] * GRID)))
    row = min(GRID - 1, max(0, int(cy / size[1] * GRID)))
    return f"c{col}{row}"


def _page(visual: dict[str, Any]) -> str:
    for part in ("actions", "setup"):
        goto = next(
            (a["url"] for a in visual.get(part, []) if a["do"] == "goto" and a.get("url")), None
        )
        if goto:
            return norm_url(goto)
    return norm_url(visual.get("page"))


def visual_signature(visual: dict[str, Any]) -> str | None:
    """Signature planned from a scene's visual (None for photos and drawn scenes)."""
    if visual.get("mode") != "recording":
        return None
    url = _page(visual)
    # what the scene ends on is what it is about: the last main action (a result, not a first step
    # that several features share, like typing into the same field)
    main = next(
        (a for a in reversed(visual.get("actions", [])) if a["do"] in MAIN and a.get("locator")),
        None,
    )
    if main is None:
        return f"{url}|page"
    loc = main["locator"]
    bbox = loc.get("bbox")
    if bbox:
        return f"{url}|{cell(bbox['x'] + bbox['w'] / 2, bbox['y'] + bbox['h'] / 2, EXPLORER_SIZE)}"
    return (
        f"{url}|{(loc.get('css') or '')}:{(loc.get('text') or loc.get('name') or '').lower()[:40]}"
    )


def recorded_signature(
    visual: dict[str, Any], focus_log: list[dict[str, Any]], size: tuple[int, int]
) -> str | None:
    """Signature of what was really recorded: the last main focus box of the clip."""
    planned = visual_signature(visual)
    if planned is None:
        return None
    last = next((f for f in reversed(focus_log) if f.get("kind") in MAIN_FOCUS), None)
    if last is None:
        return planned
    b = last["bbox"]
    return f"{_page(visual)}|{cell(b['x'] + b['w'] / 2, b['y'] + b['h'] / 2, size)}"
