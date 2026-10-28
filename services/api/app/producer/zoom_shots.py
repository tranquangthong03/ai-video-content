# ruff: noqa: E501
"""Zoom shots of the desktop_frame template: when the still camera leaves the full view.

The camera of desktop_frame stands still on the whole page. It zooms only for an EVENT - the
user clicks, double-clicks, types, selects or picks something, or the result of such an action
appears - and only while the voice-over says something about it. At most two zooms a scene (one in
a hook, none in a CTA), one level (SHOT_LEVEL), always on a whole UI block: the card, row, dialog
or field-with-label that holds the action, plus 10 % of padding. A block too big for the level is
shown at the zoom it needs; when that is below SHOT_MIN_LEVEL nothing is zoomed at all.

Pure function of the clip's data (frame_inventory, action_log, spoken phrases), all on the clip's
time axis (0 = first shown moment). The renderer plays the result (apps/render/src/camera/shot.ts).
"""

import unicodedata
from dataclasses import dataclass
from typing import Any

from app.core.textmatch import text_matches
from app.producer.focus_rules import (
    Box,
    area,
    contains,
    focus_box,
    gap,
    is_excluded,
    is_media,
    result_item,
    speech_between,
    union,
)

SHOT_LEVEL = 1.7  # the one zoom level (1.0 = the whole page)
SHOT_MIN_LEVEL = 1.3  # a block that needs less than this is not worth a zoom: stay on the full view
SHOT_PAD = 0.10  # padding around the block, each side, as a share of its size
IN_MS = 700  # move in (ease-in-out; 1.7x in 0.7 s peaks at ~4 % of the width per frame)
OUT_MS = 600  # move out (a little slower than the spec's 0.5 s: 0.5 s would peak at 5.3 %)
MIN_HOLD_MS = 1200  # perfectly still on the block at least this long
RESULT_HOLD_MS = 900  # and this long after the result is visible
NEAR_MS = 1500  # two events closer than this on the same block share one zoom
REST_MS = 300  # at least this long on the full view between two zooms
EDGE_MS = 300  # no zoom starts in the first moments of a scene
FRAME_RATIO = 9 / 16  # height / width of the media frame
BLOCK_KINDS = {"card", "list_item", "dialog"}
MAX_BLOCK_SHARE = 0.75  # a block bigger than this share of the page is the page, not a block
EVENT_DO = {"click", "dblclick", "right_click", "type", "select", "check", "pick_date", "upload"}
RESULT_NEAR_PX = 260  # a new item this close to the block is its result and joins it
RESOLVE_MS = 6000  # the snapshot that shows the item may be taken this long after the action
# what the voice-over says when it talks about doing this kind of thing (folded, no accents)
VERBS = {
    "type": ("nhap", "go ", "dien", "them", "tao", "viet", "type", "enter", "fill", "add", "write"),
    "click": (
        "bam",
        "nhan",
        "chon",
        "mo ",
        "click",
        "tap",
        "press",
        "open",
        "select",
        "luu",
        "save",
    ),
    "select": ("chon", "select", "choose", "pick"),
    "check": ("danh dau", "tick", "chon", "check", "hoan thanh", "complete", "mark"),
    "pick_date": ("ngay", "chon", "date", "pick"),
    "upload": ("tai", "keo", "upload", "drag", "anh", "image", "file"),
}


def fold(text: str) -> str:
    """Lower case without accents: how the verbs are looked up."""
    plain = unicodedata.normalize("NFD", text.lower().replace("\u0111", "d"))
    return "".join(c for c in plain if unicodedata.category(c) != "Mn")


def says_it_does(do: str, speech: str) -> bool:
    """The voice-over talks about doing this kind of thing (type, click, select ...)."""
    kind = "click" if do in ("dblclick", "right_click") else do
    words = fold(speech) + " "
    return any(v in words for v in VERBS.get(kind, ()))


def find_wide(inventory: list[dict[str, Any]], item_id: str | None, t_ms: float):  # type: ignore[no-untyped-def]
    """(item, snapshot) from the snapshot nearest in time that lists the item, up to RESOLVE_MS after
    (the picture is often taken once the action has settled, well after it started)."""
    best = None
    for snap in inventory:
        for it in snap["items"]:
            if it["id"] == item_id:
                d = snap["t_ms"] - t_ms
                if -RESOLVE_MS / 3 <= d <= RESOLVE_MS and (best is None or abs(d) < best[0]):
                    best = (abs(d), it, snap)
    return (best[1], best[2]) if best else None


def full_width(clip: tuple[int, int]) -> float:
    """Width of the full view: the clip contained in the 16:9 frame (the page is never cut)."""
    return max(float(clip[0]), clip[1] / FRAME_RATIO)


def padded(box: Box, clip: tuple[int, int]) -> Box:
    dx, dy = box["w"] * SHOT_PAD, box["h"] * SHOT_PAD
    x0, y0 = max(0.0, box["x"] - dx), max(0.0, box["y"] - dy)
    x1, y1 = (
        min(float(clip[0]), box["x"] + box["w"] + dx),
        min(float(clip[1]), box["y"] + box["h"] + dy),
    )
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def fit_zoom(box: Box, clip: tuple[int, int]) -> float:
    """Largest zoom (full view = 1) at which the window still holds the whole box."""
    w0 = full_width(clip)
    return float(min(w0 / box["w"], w0 * FRAME_RATIO / box["h"]))


def block_of(
    item: dict[str, Any], items: list[dict[str, Any]], clip: tuple[int, int]
) -> Box | None:
    """The UI block an action works in: the smallest card / row / dialog around it, else the item
    itself with its label (a field) or with some air (a button). None when it is not a block."""
    page = float(clip[0] * clip[1])
    holders = [
        i
        for i in items
        if i["kind"] in BLOCK_KINDS
        and i["id"] != item["id"]
        and not is_excluded(i)
        and contains(i["bbox"], item["bbox"])
        and area(i["bbox"]) <= MAX_BLOCK_SHARE * page
    ]
    if holders:
        return dict(min(holders, key=lambda i: area(i["bbox"]))["bbox"])
    box = focus_box(item, items, clip)
    return box if area(box) <= MAX_BLOCK_SHARE * page else None


@dataclass
class Shot:
    in_start: float
    in_end: float
    hold_to: float
    box: Box
    zoom: float
    score: float
    item_id: str | None
    text: str
    reason: str
    is_result: bool


def events_of(
    actions: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    phrases: list[dict[str, Any]],
    clip: tuple[int, int],
    limit_ms: float,
    drops: dict[str, int],
) -> list[Shot]:
    """One candidate zoom per event that has a block, a voice-over that talks about it, and room."""
    found: list[Shot] = []
    ordered = sorted((a for a in actions if a["do"] in EVENT_DO), key=lambda a: a["t_ms"])
    for n, a in enumerate(ordered):
        hit = find_wide(inventory, a.get("item_id"), a["end_ms"])
        if hit is None:
            drops["no_item"] += 1
            continue
        item, snap = hit
        if is_media(item, clip):  # (a control the user operated is shown even in a footer)
            drops["not_a_block"] += 1
            continue
        block = block_of(item, snap["items"], clip)
        if block is None:
            drops["too_big"] += 1
            continue
        result = result_item(inventory, a)
        texts = [item.get("text") or "", a.get("target_text") or ""]
        if result is not None and gap(result["bbox"], block) <= RESULT_NEAR_PX:
            joined = union([block, result["bbox"]])
            if area(joined) <= MAX_BLOCK_SHARE * clip[0] * clip[1]:
                block = joined
            texts.append(result.get("text") or "")
        for holder in snap["items"]:  # the text of the card / row also counts as talked about
            if (
                holder["kind"] in BLOCK_KINDS
                and contains(block, holder["bbox"])
                and holder.get("text")
            ):
                texts.append(holder["text"])
        box = padded(block, clip)
        zoom = min(SHOT_LEVEL, fit_zoom(box, clip))
        if zoom < SHOT_MIN_LEVEL:
            drops["block_does_not_fit"] += 1
            continue
        in_end = a["t_ms"] + 100  # the picture is close when the click lands
        in_start = max(EDGE_MS, in_end - IN_MS)
        in_end = in_start + IN_MS
        nxt = ordered[n + 1]["t_ms"] if n + 1 < len(ordered) else limit_ms
        seen = a["end_ms"]
        if result is not None:  # the first snapshot that lists the result is when it can be seen
            seen = max(seen, min((x["t_ms"] for x in inventory if any(i["id"] == result["id"] for i in x["items"]) and x["t_ms"] >= a["end_ms"]), default=seen))  # fmt: skip
        hold_to = max(in_end + MIN_HOLD_MS, seen + RESULT_HOLD_MS)
        hold_to = min(hold_to, max(nxt - NEAR_MS / 3, in_end + MIN_HOLD_MS), limit_ms - OUT_MS - 50)
        if hold_to - in_end < MIN_HOLD_MS * 0.7:
            drops["no_room"] += 1
            continue
        speech = speech_between(phrases, in_start - 300, hold_to)
        about = any(t and text_matches(t, speech) for t in texts) or says_it_does(a["do"], speech)
        if not speech or not about:
            drops["speech_not_about_it"] += 1
            continue
        score = (3.0 if result is not None else 0.0) + (1.0 if a["do"] != "type" else 0.5)
        found.append(
            Shot(
                in_start, in_end, hold_to, box, zoom, score, item.get("id"),
                (item.get("text") or a.get("target_text") or "")[:60],
                f"{a['do']}{' + result' if result is not None else ''}", result is not None,
            )
        )  # fmt: skip
    return found


def merge(shots: list[Shot], clip: tuple[int, int]) -> list[Shot]:
    """Events close in time on the same block are one zoom (no going out and in again)."""
    out: list[Shot] = []
    for s in sorted(shots, key=lambda s: s.in_start):
        last = out[-1] if out else None
        if last and s.in_start - last.hold_to < NEAR_MS:
            joined = union([last.box, s.box])
            overlap = contains(joined, last.box) and (
                area(last.box) + area(s.box) > 0.5 * area(joined)
            )
            zoom = min(SHOT_LEVEL, fit_zoom(joined, clip))
            if overlap and zoom >= SHOT_MIN_LEVEL:
                out[-1] = Shot(
                    last.in_start, last.in_end, max(last.hold_to, s.hold_to), joined, zoom,
                    max(last.score, s.score) + 0.5, last.item_id, last.text,
                    f"{last.reason}; {s.reason}", last.is_result or s.is_result,
                )  # fmt: skip
                continue
        out.append(s)
    return out


def plan_zoom_shots(
    *,
    scene_type: str,
    limit_ms: float,
    clip: tuple[int, int],
    actions: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    phrases: list[dict[str, Any]],
    max_shots: int = 2,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(zoom shots, summary). `limit_ms`: clip time at which the scene ends (the last zoom is out by then)."""
    drops = {k: 0 for k in ("no_item", "not_a_block", "too_big", "block_does_not_fit", "no_room", "speech_not_about_it", "crowded")}  # fmt: skip
    cap = {"hook": 1, "cta": 0}.get(scene_type, max_shots)
    candidates = merge(events_of(actions, inventory, phrases, clip, limit_ms, drops), clip)
    if scene_type == "hook":
        candidates = [c for c in candidates if c.is_result]  # a hook zooms only into a result
    # the best ones first; a candidate that leaves no rest on the full view next to a kept one is dropped
    kept: list[Shot] = []
    for c in sorted(candidates, key=lambda c: (-c.score, c.in_start)):
        if len(kept) >= cap:
            drops["crowded"] += 1
            continue
        clash = any(
            c.in_start < k.hold_to + OUT_MS + REST_MS and k.in_start < c.hold_to + OUT_MS + REST_MS
            for k in kept
        )
        if clash:
            drops["crowded"] += 1
            continue
        kept.append(c)
    kept.sort(key=lambda k: k.in_start)
    shots = [
        {
            "in_start_ms": round(k.in_start),
            "in_end_ms": round(k.in_end),
            "out_start_ms": round(k.hold_to),
            "out_end_ms": round(k.hold_to + OUT_MS),
            "box": {key: round(v, 1) for key, v in k.box.items()},
            "zoom": round(k.zoom, 3),
            "item_id": k.item_id,
            "text": k.text,
            "reason": k.reason,
        }
        for k in kept
    ]
    summary = {
        "zoom_shots": len(shots),
        "events": sum(1 for a in actions if a["do"] in EVENT_DO),
        "dropped": {k: v for k, v in drops.items() if v},
        "scene_type": scene_type,
    }
    return shots, summary
