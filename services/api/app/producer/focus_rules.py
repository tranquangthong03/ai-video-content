"""Focus rules: what the camera looks at, and for how long, as a pure function of the clip's data.

Inputs (all on the clip time axis, after dead time was cut): the frame_inventory (what was on
screen), the action_log (what was done to which item), the spoken phrases, optionally a plan from
the Focus Planner, and the old focus_log as a last resort. Output: the focus_track
[{t_ms, bbox, framing, hold_ms, source, ...}] that the renderer's camera follows.

The rules apply AFTER a plan and also when there is none:
  * while typing the focus is the input; after an action it is the item that is new next to it
  * a focus is widened to the whole block of text it belongs to, so no text is cut at the view's
    edge (the camera may then zoom out below "cover"); images are shown whole with the label next
    to them, never zoomed into
  * nav / aside / footer items are never the focus, unless the plan chose one AND the voice-over
    says what the item says
  * a focus lasts at least MIN_FOCUS_MS; shorter stretches are merged into a neighbour
"""

from dataclasses import dataclass, replace
from typing import Any

from app.core.textmatch import text_matches

ESTABLISH_MS = 1000  # the opening shot of the whole page
MIN_FOCUS_MS = 1500
HOLD_MS = 1500  # how long the result of an action is looked at
RESULT_WINDOW_MS = HOLD_MS + 500  # snapshots this long after an action show its result
NEARBY_PX = 220  # a label this close to an image belongs to it
MAX_BLOCK_SHARE = 0.85  # a text block may fill at most this share of the viewport
MAX_PARENT_SHARE = 0.6
RESOLVE_WINDOW_MS = 2500  # an item is looked up in the snapshot nearest in time, within this

EXCLUDED_REGIONS = {"nav", "aside", "footer"}
EXCLUDED_KINDS = {"sidebar", "nav", "footer"}
TEXT_KINDS = {"heading", "paragraph", "list_item", "button", "input"}
BLOCK_KINDS = {"card", "list_item", "paragraph", "heading"}
POINT_ACTIONS = {"click", "dblclick", "right_click", "hover", "upload"}
FRAMINGS = {"establish", "tight", "medium", "wide"}

Box = dict[str, float]


# --- geometry ------------------------------------------------------------------------------------


def area(b: Box) -> float:
    return max(0.0, b["w"]) * max(0.0, b["h"])


def union(boxes: list[Box]) -> Box:
    x0 = min(b["x"] for b in boxes)
    y0 = min(b["y"] for b in boxes)
    x1 = max(b["x"] + b["w"] for b in boxes)
    y1 = max(b["y"] + b["h"] for b in boxes)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def contains(outer: Box, inner: Box, tol: float = 2.0) -> bool:
    return (
        outer["x"] - tol <= inner["x"]
        and outer["y"] - tol <= inner["y"]
        and outer["x"] + outer["w"] + tol >= inner["x"] + inner["w"]
        and outer["y"] + outer["h"] + tol >= inner["y"] + inner["h"]
    )


def intersects(a: Box, b: Box) -> bool:
    return (
        a["x"] < b["x"] + b["w"]
        and b["x"] < a["x"] + a["w"]
        and a["y"] < b["y"] + b["h"]
        and b["y"] < a["y"] + a["h"]
    )


def gap(a: Box, b: Box) -> float:
    """Distance between two boxes (0 when they touch or overlap)."""
    dx = max(0.0, max(a["x"], b["x"]) - min(a["x"] + a["w"], b["x"] + b["w"]))
    dy = max(0.0, max(a["y"], b["y"]) - min(a["y"] + a["h"], b["y"] + b["h"]))
    return float((dx * dx + dy * dy) ** 0.5)


# --- inventory lookups ---------------------------------------------------------------------------


def find_item(
    inventory: list[dict[str, Any]], item_id: str | None, t_ms: float
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """(item, its snapshot) from the snapshot closest in time that lists the item."""
    if item_id is None:
        return None
    best: tuple[float, dict[str, Any], dict[str, Any]] | None = None
    for snap in inventory:
        for it in snap["items"]:
            if it["id"] == item_id:
                d = abs(snap["t_ms"] - t_ms)
                if d <= RESOLVE_WINDOW_MS and (best is None or d < best[0]):
                    best = (d, it, snap)
    return (best[1], best[2]) if best else None


def snapshot_at(inventory: list[dict[str, Any]], t_ms: float) -> dict[str, Any] | None:
    """The snapshot closest in time (preferring one not later than t_ms)."""
    if not inventory:
        return None
    return min(inventory, key=lambda s: (abs(s["t_ms"] - t_ms), s["t_ms"] > t_ms))


def is_excluded(item: dict[str, Any]) -> bool:
    return item["region"] in EXCLUDED_REGIONS or item["kind"] in EXCLUDED_KINDS


def speech_between(phrases: list[dict[str, Any]], a: float, b: float) -> str:
    return " ".join(p["text"] for p in phrases if p["from_ms"] < b and p["to_ms"] > a)


def may_focus(item: dict[str, Any], source: str, speech: str) -> bool:
    """Side regions only when the plan chose the item and the voice-over names what it says."""
    if not is_excluded(item):
        return True
    return source == "plan" and bool(item["text"]) and text_matches(item["text"], speech)


# --- from one item to the box the camera must show ----------------------------------------------


def text_block(item: dict[str, Any], items: list[dict[str, Any]], view_area: float) -> Box:
    """The block of text the item belongs to: its smallest card/list item/paragraph parent, then
    every text item that touches it, so no line of text is cut off."""
    box: Box = dict(item["bbox"])
    parents = [
        i
        for i in items
        if i["id"] != item["id"]
        and i["kind"] in BLOCK_KINDS
        and i["region"] == item["region"]
        and contains(i["bbox"], box)
        and area(box) * 1.05 < area(i["bbox"]) <= MAX_PARENT_SHARE * view_area
    ]
    if parents:
        box = dict(min(parents, key=lambda i: area(i["bbox"]))["bbox"])
    for _ in range(2):
        touching = [
            i["bbox"]
            for i in items
            if i["text"]
            and i["kind"] in TEXT_KINDS
            and i["region"] == item["region"]
            and intersects(i["bbox"], box)
            and not contains(box, i["bbox"])
        ]
        if not touching:
            break
        grown = union([box, *touching])
        if area(grown) > MAX_BLOCK_SHARE * view_area:
            break
        box = grown
    return box


def image_block(item: dict[str, Any], items: list[dict[str, Any]]) -> Box:
    """The whole image plus the text item closest to it (a label, a size): never zoom inside."""
    labels = [
        i
        for i in items
        if i["id"] != item["id"]
        and i["text"]
        and i["kind"] in TEXT_KINDS
        and not is_excluded(i)
        and gap(i["bbox"], item["bbox"]) <= NEARBY_PX
    ]
    if not labels:
        return dict(item["bbox"])
    nearest = min(labels, key=lambda i: gap(i["bbox"], item["bbox"]))
    return union([item["bbox"], nearest["bbox"]])


def focus_box(item: dict[str, Any], items: list[dict[str, Any]], clip: tuple[int, int]) -> Box:
    view_area = float(clip[0] * clip[1])
    if item["kind"] in ("image", "media"):
        return image_block(item, items)
    if item["kind"] in ("input", "button"):
        return dict(item["bbox"])
    return text_block(item, items, view_area)


def framing_for(item: dict[str, Any], box: Box, clip: tuple[int, int]) -> str:
    """tight for a field/button/number, medium for a card or list item, wide for a big block."""
    if area(box) > 0.35 * clip[0] * clip[1] or item["kind"] in ("image", "media"):
        return "wide"
    if item["kind"] in ("input", "button"):
        return "tight"
    if item["kind"] in ("card", "list_item"):
        return "medium"
    return "medium" if box["w"] > 0.3 * clip[0] else "tight"


# --- segments ------------------------------------------------------------------------------------


@dataclass
class Seg:
    from_ms: float
    to_ms: float
    item_id: str | None
    framing: str = "medium"
    source: str = "rule"  # plan | rule | fallback
    reason: str = ""
    priority: int = 0  # 2 = typing: must not be merged away
    pick: str | None = None  # "center": no item, take the block in the middle of the screen

    @property
    def length(self) -> float:
        return self.to_ms - self.from_ms


def result_item(inventory: list[dict[str, Any]], action: dict[str, Any]) -> dict[str, Any] | None:
    """The item that is new right after an action, nearest to what was acted on."""
    target = find_item(inventory, action.get("item_id"), action["end_ms"])
    fresh: list[dict[str, Any]] = []
    for snap in inventory:
        if action["end_ms"] <= snap["t_ms"] <= action["end_ms"] + RESULT_WINDOW_MS:
            fresh += [
                i
                for i in snap["items"]
                if i["is_new"] and not is_excluded(i) and (i["text"] or i["kind"] == "image")
            ]
    if not fresh:
        return None
    if target is None:
        return fresh[0]
    return min(fresh, key=lambda i: gap(i["bbox"], target[0]["bbox"]))


def rule_segments(
    duration_ms: float, actions: list[dict[str, Any]], inventory: list[dict[str, Any]]
) -> list[Seg]:
    """What to look at when there is no plan: the thing acted on, then its result."""
    ordered = sorted(actions, key=lambda a: a["t_ms"])
    first = ordered[0]["t_ms"] if ordered else duration_ms
    segs = [Seg(0, min(ESTABLISH_MS, max(first, 1)), None, "establish")]
    for i, a in enumerate(ordered):
        nxt = ordered[i + 1]["t_ms"] if i + 1 < len(ordered) else duration_ms
        end = max(a["end_ms"], a["t_ms"])
        if a["do"] in ("scroll", "scroll_to"):
            segs.append(Seg(a["t_ms"], nxt, a.get("item_id"), "medium", pick="center"))
            continue
        segs.append(Seg(a["t_ms"], min(nxt, max(end, a["t_ms"] + 1)), a.get("item_id"), "tight"))
        if end < nxt:
            result = result_item(inventory, a) if a["do"] in POINT_ACTIONS | {"type"} else None
            segs.append(Seg(end, nxt, result["id"] if result else a.get("item_id"), "medium"))
    return segs


def plan_segments(plan: list[dict[str, Any]], duration_ms: float) -> list[Seg]:
    segs = []
    for p in sorted(plan, key=lambda p: p["from_ms"]):
        a, b = max(0.0, p["from_ms"]), min(duration_ms, p["to_ms"])
        if b > a:
            framing = p["framing"] if p["framing"] in FRAMINGS else "medium"
            segs.append(Seg(a, b, p.get("item_id"), framing, "plan", p.get("reason", "")))
    return segs


def typing_segments(actions: list[dict[str, Any]]) -> list[Seg]:
    return [
        Seg(a["t_ms"], a["end_ms"], a.get("item_id"), "tight", "rule", "đang gõ", priority=2)
        for a in actions
        if a["do"] == "type" and a.get("item_id") and a["end_ms"] > a["t_ms"]
    ]


def overlay(base: list[Seg], top: list[Seg], duration_ms: float) -> list[Seg]:
    """`top` segments replace whatever `base` had in their time range."""
    out: list[Seg] = []
    for seg in base:
        pieces = [seg]
        for t in top:
            nxt: list[Seg] = []
            for p in pieces:
                if t.to_ms <= p.from_ms or t.from_ms >= p.to_ms:
                    nxt.append(p)
                    continue
                if t.from_ms > p.from_ms:
                    nxt.append(replace(p, to_ms=t.from_ms))
                if t.to_ms < p.to_ms:
                    nxt.append(replace(p, from_ms=t.to_ms))
            pieces = nxt
        out += pieces
    out += [replace(t, to_ms=min(t.to_ms, duration_ms)) for t in top]
    return sorted(out, key=lambda s: s.from_ms)


def ensure_opening(segs: list[Seg]) -> list[Seg]:
    """Every track starts with the establishing shot (the first second shows the whole page)."""
    if not segs or segs[0].framing == "establish":
        return segs
    first = segs[0]
    if first.length <= ESTABLISH_MS + 200:  # too short to be a focus: it becomes the opening
        return [
            replace(first, item_id=None, framing="establish", source="rule", pick=None),
            *segs[1:],
        ]
    opening = Seg(first.from_ms, first.from_ms + ESTABLISH_MS, None, "establish", "rule")
    return [opening, replace(first, from_ms=opening.to_ms), *segs[1:]]


def tidy(segs: list[Seg], duration_ms: float) -> list[Seg]:
    """Contiguous from 0 to the end, and no focus shorter than MIN_FOCUS_MS (the opening shot
    excepted): a short one is merged into the one before, a short typing focus takes time from
    the one after instead."""
    if not segs:
        return [Seg(0, duration_ms, None, "establish")]
    segs = sorted(segs, key=lambda s: s.from_ms)
    segs[0] = replace(segs[0], from_ms=0)
    for i in range(len(segs) - 1):  # close gaps and overlaps
        segs[i] = replace(segs[i], to_ms=segs[i + 1].from_ms)
    segs[-1] = replace(segs[-1], to_ms=duration_ms)
    segs = [s for s in segs if s.length > 0]
    changed = True
    while changed and len(segs) > 1:
        changed = False
        for i, s in enumerate(segs):
            opening = i == 0 and s.item_id is None and s.framing == "establish"
            if s.length >= MIN_FOCUS_MS or opening:
                continue
            nxt = segs[i + 1] if i + 1 < len(segs) else None
            if s.priority >= 2 and nxt is not None and nxt.length - (MIN_FOCUS_MS - s.length) >= 0:
                need = MIN_FOCUS_MS - s.length
                segs[i] = replace(s, to_ms=s.to_ms + need)
                segs[i + 1] = replace(nxt, from_ms=nxt.from_ms + need)
                segs = [x for x in segs if x.length > 0]
            elif i > 0 and not (i == 1 and segs[0].framing == "establish" and nxt is not None):
                # (a short stretch right after the opening shot joins the next one instead)
                segs[i - 1] = replace(segs[i - 1], to_ms=s.to_ms)
                del segs[i]
            elif nxt is not None:
                segs[i + 1] = replace(
                    nxt, from_ms=s.from_ms, priority=max(nxt.priority, s.priority)
                )
                del segs[i]
            else:
                break
            changed = True
            break
    merged: list[Seg] = []
    for s in segs:  # the same thing looked at twice in a row is one focus
        last = merged[-1] if merged else None
        if last and last.item_id == s.item_id and last.pick == s.pick and s.item_id is not None:
            merged[-1] = replace(last, to_ms=s.to_ms)
        else:
            merged.append(s)
    return merged


# --- the track -----------------------------------------------------------------------------------


def center_block(items: list[dict[str, Any]], clip: tuple[int, int]) -> dict[str, Any] | None:
    """Scrolling without a plan: the heading (else card) of the main region nearest the middle."""
    pool = [i for i in items if not is_excluded(i) and i["kind"] in ("heading", "card")]
    if not pool:
        return None
    mid = clip[1] / 2
    return min(pool, key=lambda i: abs(i["bbox"]["y"] + i["bbox"]["h"] / 2 - mid))


def whole(clip: tuple[int, int]) -> Box:
    return {"x": 0, "y": 0, "w": clip[0], "h": clip[1]}


@dataclass
class TrackResult:
    track: list[dict[str, Any]]
    metrics: dict[str, Any]


def build_focus_track(
    *,
    duration_ms: float,
    clip: tuple[int, int],
    inventory: list[dict[str, Any]],
    action_log: list[dict[str, Any]],
    phrases: list[dict[str, Any]] | None = None,
    plan: list[dict[str, Any]] | None = None,
    legacy_focus: list[dict[str, Any]] | None = None,
) -> TrackResult:
    phrases = phrases or []
    legacy = [f for f in (legacy_focus or []) if f.get("kind") != "scroll"]
    typing = typing_segments(action_log)
    base = (
        plan_segments(plan, duration_ms)
        if plan
        else rule_segments(duration_ms, action_log, inventory)
    )
    segs = tidy(ensure_opening(overlay(base, typing, duration_ms)), duration_ms)

    track: list[dict[str, Any]] = []
    metrics = {
        "replaced_side_focus": 0,
        "unresolved": 0,
        "sources": {"plan": 0, "rule": 0, "fallback": 0},
    }
    for seg in segs:
        mid = (seg.from_ms + seg.to_ms) / 2
        snap = snapshot_at(inventory, mid)
        items = snap["items"] if snap else []
        speech = speech_between(phrases, seg.from_ms, seg.to_ms)
        source, item, framing, reason = seg.source, None, seg.framing, seg.reason
        if seg.item_id is not None or seg.pick:
            found = find_item(inventory, seg.item_id, mid)
            item = found[0] if found else None
            if found:
                items = found[1]["items"]
            if item is None and seg.pick == "center":
                item = center_block(items, clip)
            if item is not None and not may_focus(item, source, speech):
                metrics["replaced_side_focus"] += 1
                item, source = center_block(items, clip), "rule"
            if item is None:
                metrics["unresolved"] += 1
        if item is None and framing != "establish":
            old = [f for f in legacy if f["t_ms"] <= seg.from_ms + 1]
            if old and seg.item_id is not None:
                b = old[-1]["bbox"]
                box: Box = {"x": b["x"], "y": b["y"], "w": b["w"], "h": b["h"]}
                framing, source = "medium", "fallback"
            else:
                box, framing, source = whole(clip), "wide", "fallback"
            entry: dict[str, Any] = {"item_id": None, "text": "", "item_kind": None, "region": None}
        elif item is None:
            box = whole(clip)
            entry = {"item_id": None, "text": "", "item_kind": None, "region": None}
        else:
            box = focus_box(item, items, clip)
            if item["kind"] in ("image", "media"):
                framing = "wide"  # the whole image, never zoomed into
            elif source == "plan" and seg.framing != "establish":
                framing = seg.framing
            elif seg.framing == "tight":
                framing = "tight"
            else:
                framing = framing_for(item, box, clip)
            entry = {
                "item_id": item["id"],
                "text": item["text"],
                "item_kind": item["kind"],
                "region": item["region"],
            }
        metrics["sources"][source] += 1
        track.append(
            {
                "t_ms": round(seg.from_ms),
                "bbox": {k: round(v) for k, v in box.items()},
                "framing": framing,
                "hold_ms": round(seg.length),
                "source": source,
                "reason": reason,
                **entry,
            }
        )
    return TrackResult(track, metrics)
