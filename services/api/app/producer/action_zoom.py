# ruff: noqa: E501
"""Action Zoom: every action the browser performed gets a zoom (desktop_frame template).

One rule, nothing else: for each recorded action (click, double click, type, select, check, pick a
date, upload - a click that opens another page included) the camera zooms onto the element that
was operated and its label, holds still while the action goes on and for 1.2 s after its result
shows, then goes back to the whole page. The voice-over, the Focus Planner and the page's
"blocks" play no part.

  * region = the element's box + its label (the text just above / to the left of a field) + 25 %
  * level  = the region fills about 55 % of the frame's width, kept between 1.6x and 2.6x, and never
             more than what keeps the whole region in view (the element and its label are never cut)
  * timing = in 400 ms before the action (500 ms, ease-in-out); hold; out 500 ms
  * the next action within 1.5 s and close by (centres closer than 40 % of the frame's width): the
    camera pans straight over (500 ms) instead of zooming out and in again
  * no box for the element: the click's own position, a region 25 % of the frame wide

Pure function of the clip's own data on the clip's time axis (0 = the first shown moment); the
renderer plays the result (apps/render/src/camera/shot.ts).
"""

import re
import unicodedata
from typing import Any

from app.producer.focus_rules import Box, label_of, union

SHARE = 0.55  # the region fills this much of the frame's width
MIN_ZOOM, MAX_ZOOM = 1.6, 2.6
MIN_USEFUL_ZOOM = 1.15  # a region that needs less than this to be whole is not worth a zoom
PAD = 0.25  # around the element + label, each side, as a share of their size
LEAD_MS = 400  # the zoom starts this long before the action
MOVE_MS = 500  # in, out and pan
AFTER_MS = 1200  # still, after the result of the action shows
CHAIN_GAP_MS = 1500  # the next action starts within this: pan over
CHAIN_NEAR = 0.4  # ... and its centre is closer than this share of the frame's width
FALLBACK_SHARE = 0.25  # no box: a region this wide (share of the frame) around the click
RESULT_WINDOW_MS = 3000
RESOLVE_MS = 6000  # the snapshot that shows an element may be taken this long after the action
KEY_GAP_MS = 500  # keystrokes closer than this belong to one typing
TYPING_FALLBACK_MS = 1500
TEXT_RATIO = (
    0.4  # height of typed text / height of its field (an estimate: the inventory has no font size)
)
FRAME_RATIO = 9 / 16
ACTION_DO = {"click", "dblclick", "right_click", "type", "select", "check", "pick_date", "upload"}
LABEL_WORDS = 6
TRAILING = {"vào", "để", "và", "của", "cho", "trên", "ở", "rồi", "thì", "là", "với", "the", "a", "to", "into", "on", "in", "of"}  # fmt: skip
VERB = {
    "type": "Nhập", "click": "Bấm", "dblclick": "Bấm đúp", "right_click": "Bấm chuột phải",
    "select": "Chọn", "check": "Đánh dấu", "pick_date": "Chọn ngày", "upload": "Tải lên",
}  # fmt: skip


def fold(text: str) -> str:
    plain = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(c for c in plain if unicodedata.category(c) != "Mn")


def full_width(clip: tuple[int, int]) -> float:
    """Width of the full view: the clip contained in the 16:9 frame (the page is never cut)."""
    return max(float(clip[0]), clip[1] / FRAME_RATIO)


def fit_zoom(box: Box, clip: tuple[int, int]) -> float:
    """Largest zoom (full view = 1) at which the window still holds the whole box."""
    w0 = full_width(clip)
    return float(min(w0 / box["w"], w0 * FRAME_RATIO / box["h"]))


def padded(box: Box, clip: tuple[int, int], share: float = PAD) -> Box:
    dx, dy = box["w"] * share, box["h"] * share
    x0, y0 = max(0.0, box["x"] - dx), max(0.0, box["y"] - dy)
    x1, y1 = (
        min(float(clip[0]), box["x"] + box["w"] + dx),
        min(float(clip[1]), box["y"] + box["h"] + dy),
    )
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def centre(box: Box) -> tuple[float, float]:
    return box["x"] + box["w"] / 2, box["y"] + box["h"] / 2


def short_label(note: str | None, do: str, target: str | None) -> str:
    """At most LABEL_WORDS words of the step's note (no model): «Nhập họ tên nhân viên»."""
    text = re.sub(r"\s+", " ", (note or "").strip()).rstrip(".;:,")
    if not text:
        word = (target or "").strip()
        text = f"{VERB.get(do, 'Thao tác')} {word}".strip()
    words = text.split(" ")[:LABEL_WORDS]
    while len(words) > 2 and words[-1].lower() in TRAILING:
        words.pop()
    return " ".join(words)


def labels_for(steps: list[Any], actions: list[dict[str, Any]]) -> list[str]:
    """One label per action: the note of the step that did it (steps and actions are matched in
    order by what they did), else the verb and the target."""
    pool = [s for s in steps if s.action.do in ACTION_DO]
    out: list[str] = []
    for a in sorted(actions, key=lambda a: a["t_ms"]):
        if a["do"] not in ACTION_DO:
            continue
        hit = next((s for s in pool if s.action.do == a["do"]), None)
        if hit is not None:
            pool.remove(hit)
        out.append(short_label(hit.note if hit else None, a["do"], a.get("target_text")))
    return out


def find_wide(inventory: list[dict[str, Any]], item_id: str | None, t_ms: float):  # type: ignore[no-untyped-def]
    """(item, snapshot) from the snapshot nearest in time that lists the item, up to RESOLVE_MS
    after (the picture is often taken once the action has settled)."""
    best = None
    for snap in inventory:
        for it in snap["items"]:
            if it["id"] == item_id:
                d = snap["t_ms"] - t_ms
                if -RESOLVE_MS / 3 <= d <= RESOLVE_MS and (best is None or abs(d) < best[0]):
                    best = (abs(d), it, snap)
    return (best[1], best[2]) if best else None


MATCH_BEFORE_MS = 300
MATCH_AFTER_MS = (
    6000  # the pointer takes a while to arrive: the click comes this long after the step began
)


def match_events(
    actions: list[dict[str, Any]], focus_log: list[dict[str, Any]], click_log: list[dict[str, Any]]
) -> list[tuple[float, dict[str, Any] | None, dict[str, Any] | None]]:
    """For every action, in order: (the moment it really happens, its focus entry, its click).

    The action log notes a step when it BEGINS; the pointer then travels to the element, and the
    click (and the focus entry with the element's box) comes a second or two later. That moment is
    when the camera has to be there. Entries are used once, in order."""
    foci = sorted(
        (f for f in focus_log if f.get("kind") in ("click", "dblclick", "type")),
        key=lambda f: f["t_ms"],
    )
    clicks = sorted(
        (c for c in click_log if c.get("type") in ("click", "dblclick")), key=lambda c: c["t_ms"]
    )
    out: list[tuple[float, dict[str, Any] | None, dict[str, Any] | None]] = []
    for n, a in enumerate(actions):
        ceiling = actions[n + 1]["t_ms"] if n + 1 < len(actions) else float("inf")
        lo, hi = (
            a["t_ms"] - MATCH_BEFORE_MS,
            min(a["t_ms"] + MATCH_AFTER_MS, ceiling + MATCH_BEFORE_MS),
        )
        f = next((x for x in foci if lo <= x["t_ms"] <= hi), None)
        if f is not None:
            foci.remove(f)
        c = next((x for x in clicks if lo <= x["t_ms"] <= hi), None)
        if c is not None:
            clicks.remove(c)
        t = f["t_ms"] if f is not None else c["t_ms"] if c is not None else a["t_ms"]
        out.append((float(t), f, c))
    return out


def item_at(box: Box, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The inventory item that is (nearly) the box: its overlap covers most of both."""
    best, best_share = None, 0.6
    for it in items:
        b = it["bbox"]
        w = min(box["x"] + box["w"], b["x"] + b["w"]) - max(box["x"], b["x"])
        h = min(box["y"] + box["h"], b["y"] + b["h"]) - max(box["y"], b["y"])
        if w <= 0 or h <= 0:
            continue
        share = w * h / max(1.0, min(box["w"] * box["h"], b["w"] * b["h"]))
        if share > best_share:
            best, best_share = it, share
    return best


def target_of(
    a: dict[str, Any],
    inventory: list[dict[str, Any]],
    focus: dict[str, Any] | None,
    click: dict[str, Any] | None,
    clip: tuple[int, int],
) -> tuple[Box | None, dict[str, Any] | None, str]:
    """(element + label box, the inventory item, where the box came from) of an action."""
    hit = find_wide(inventory, a.get("item_id"), a["end_ms"])
    item, items = (hit[0], hit[1]["items"]) if hit is not None else (None, [])
    if focus is not None:  # the box the pointer really went to
        box: Box = dict(focus["bbox"])
        if item is None:
            snap = min(inventory, key=lambda s: abs(s["t_ms"] - focus["t_ms"]), default=None)
            item = item_at(box, snap["items"]) if snap else None
            items = snap["items"] if snap else []
        source = "focus_log"
    elif item is not None:
        box = dict(item["bbox"])
        source = "inventory"
    elif click is not None:
        w = FALLBACK_SHARE * full_width(clip)
        h = w * FRAME_RATIO
        return {"x": click["x"] - w / 2, "y": click["y"] - h / 2, "w": w, "h": h}, None, "click"
    else:
        return None, None, "none"
    if item is not None and item["kind"] == "input":
        label = label_of(item, items)
        if label is not None:
            box = union([box, label["bbox"]])
    return box, item, source


def typing_end(t_ms: float, activity_ms: list[float]) -> float:
    """When the keystrokes that began at t_ms stop: the end of the run of activity with no gap of
    KEY_GAP_MS or more (the first key may come a little after the click)."""
    end, first = t_ms, True
    for t in sorted(x for x in activity_ms if x > t_ms):
        if t - end > (2 * KEY_GAP_MS if first else KEY_GAP_MS):
            break
        end, first = t, False
    return end if end > t_ms else t_ms + TYPING_FALLBACK_MS


def result_time(inventory: list[dict[str, Any]], after_ms: float) -> float | None:
    """The first snapshot after the action in which something new (text or picture) shows up."""
    for snap in sorted(inventory, key=lambda s: s["t_ms"]):
        if after_ms <= snap["t_ms"] <= after_ms + RESULT_WINDOW_MS and any(
            i.get("is_new") and (i.get("text") or i["kind"] in ("image", "media"))
            for i in snap["items"]
        ):
            return float(snap["t_ms"])
    return None


def plan_action_zooms(
    *,
    limit_ms: float,
    clip: tuple[int, int],
    actions: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    focus_log: list[dict[str, Any]],
    click_log: list[dict[str, Any]],
    activity_ms: list[float],
    labels: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(zoom shots, summary). `limit_ms`: clip time at which the scene ends."""
    ordered = sorted((a for a in actions if a["do"] in ACTION_DO), key=lambda a: a["t_ms"])
    w0 = full_width(clip)
    shots: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    moments = match_events(ordered, focus_log, click_log)
    for n, a0 in enumerate(ordered):
        when, focus, click = moments[n]
        a = {
            **a0,
            "t_ms": when,
            "end_ms": max(a0["end_ms"], when),
        }  # the moment of the click itself
        box, item, source = target_of(a, inventory, focus, click, clip)
        if box is None:
            missing.append(
                {"t_ms": round(a["t_ms"]), "do": a["do"], "why": "no box and no click position"}
            )
            continue
        region = padded(box, clip)
        zoom = min(max(SHARE * w0 / region["w"], MIN_ZOOM), MAX_ZOOM, fit_zoom(region, clip))
        if zoom < MIN_USEFUL_ZOOM:
            missing.append(
                {
                    "t_ms": round(a["t_ms"]),
                    "do": a["do"],
                    "why": f"region too big for a zoom ({zoom:.2f}x)",
                }
            )
            continue
        act_end = max(
            a["end_ms"], typing_end(a["t_ms"], activity_ms) if a["do"] == "type" else a["end_ms"]
        )
        seen = result_time(inventory, act_end)
        hold_to = max(act_end, seen or 0.0) + AFTER_MS
        in_start = max(0.0, a["t_ms"] - LEAD_MS)
        in_end = in_start + MOVE_MS
        hold_to = min(hold_to, limit_ms - MOVE_MS - 30)
        if hold_to < in_end + 300:
            missing.append(
                {
                    "t_ms": round(a["t_ms"]),
                    "do": a["do"],
                    "why": "too close to the end of the scene",
                }
            )
            continue
        shots.append(
            {
                "in_start_ms": in_start, "in_end_ms": in_end, "out_start_ms": hold_to,
                "out_end_ms": hold_to + MOVE_MS, "box": region, "zoom": zoom, "chain_prev": False,
                "label": labels[n] if labels and n < len(labels) else short_label(None, a["do"], a.get("target_text")),
                "target": box, "action": a["do"], "item_id": item.get("id") if item else None,
                "text": ((item or {}).get("text") or a.get("target_text") or "")[:60],
                "text_px": round(TEXT_RATIO * box["h"], 1) if a["do"] == "type" else None,
                "reason": source, "_t": a["t_ms"], "_end": act_end,
            }
        )  # fmt: skip
    for prev, cur in zip(shots, shots[1:], strict=False):
        px, py = centre(prev["box"])
        cx, cy = centre(cur["box"])
        near = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5 <= CHAIN_NEAR * w0
        soon = cur["_t"] - prev["_end"] <= CHAIN_GAP_MS
        room = cur["in_start_ms"] - MOVE_MS >= prev["in_end_ms"] + 300  # room to zoom out first
        if (soon and near) or not room:
            cur["chain_prev"] = True  # a pan straight over (the previous one does not zoom out)
            cur["in_start_ms"] = max(cur["in_start_ms"], prev["in_end_ms"])
            cur["in_end_ms"] = cur["in_start_ms"] + MOVE_MS
            prev["out_start_ms"] = cur["in_start_ms"]
            prev["out_end_ms"] = prev["out_start_ms"]
            cur["out_start_ms"] = max(cur["out_start_ms"], cur["in_end_ms"] + 300)
            cur["out_end_ms"] = cur["out_start_ms"] + MOVE_MS
        else:
            prev["out_start_ms"] = min(prev["out_start_ms"], cur["in_start_ms"] - MOVE_MS)
            prev["out_end_ms"] = prev["out_start_ms"] + MOVE_MS
    out = []
    for s in shots:
        s.pop("_t"), s.pop("_end")
        out.append(
            {
                k: (round(v) if k.endswith("_ms") else {kk: round(vv, 1) for kk, vv in v.items()} if isinstance(v, dict) else round(v, 3) if k == "zoom" else v)
                for k, v in s.items()
            }
        )  # fmt: skip
    summary = {
        "actions": len(ordered), "zoomed": len(out), "actions_without_zoom": len(ordered) - len(out),
        "without_zoom": missing, "chained": sum(1 for s in out if s["chain_prev"]),
    }  # fmt: skip
    return out, summary
