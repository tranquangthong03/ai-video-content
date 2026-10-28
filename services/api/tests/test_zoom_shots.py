"""Zoom shots of desktop_frame: events with a block, a voice-over about them, at most two a scene."""

from typing import Any

from app.producer.zoom_shots import (
    IN_MS,
    MIN_HOLD_MS,
    OUT_MS,
    SHOT_LEVEL,
    SHOT_MIN_LEVEL,
    fit_zoom,
    plan_zoom_shots,
)

CLIP = (1280, 720)


def item(
    id: str, kind: str, text: str, x: float, y: float, w: float, h: float, new: bool = False
) -> dict[str, Any]:
    return {
        "id": id, "kind": kind, "text": text, "region": "main", "is_new": new, "role": "", "tag": "",
        "bbox": {"x": x, "y": y, "w": w, "h": h},
    }  # fmt: skip


def snap(t: int, *items: dict[str, Any]) -> dict[str, Any]:
    return {"t_ms": t, "items": list(items)}


def act(do: str, item_id: str, t: int, end: int | None = None, text: str = "") -> dict[str, Any]:
    return {"do": do, "item_id": item_id, "t_ms": t, "end_ms": end or t, "target_text": text}


def say(a: int, b: int, text: str) -> dict[str, Any]:
    return {"from_ms": a, "to_ms": b, "text": text}


CARD = item("card1", "card", "New employee First name Save", 300, 150, 560, 330)
FIELD = item("f1", "input", "First name", 340, 200, 480, 48)
SAVE = item("b1", "button", "Save", 700, 420, 110, 40)
ROW = item("row1", "list_item", "Linda Anderson Added", 300, 520, 560, 60, new=True)


def plan(
    actions: list[dict[str, Any]], phrases: list[dict[str, Any]], *inv: dict[str, Any], **kw: Any
):
    return plan_zoom_shots(
        scene_type=kw.pop("scene_type", "feature_demo"), limit_ms=kw.pop("limit_ms", 9000), clip=CLIP,
        actions=actions, inventory=list(inv), phrases=phrases, **kw,
    )  # fmt: skip


def test_a_click_the_voice_over_talks_about_gets_one_zoom_on_its_whole_block() -> None:
    shots, summary = plan(
        [act("type", "f1", 2000, 2600, "First name")],
        [say(1500, 5000, "Nhập First name của nhân viên mới")],
        snap(2000, CARD, FIELD, SAVE),
    )
    assert len(shots) == 1 and summary["zoom_shots"] == 1
    s = shots[0]
    # the block is the card around the field, with 10 % of padding, held whole
    assert s["box"]["x"] <= CARD["bbox"]["x"] and s["box"]["y"] <= CARD["bbox"]["y"]
    assert s["box"]["x"] + s["box"]["w"] >= 300 + 560 and s["box"]["y"] + s["box"]["h"] >= 150 + 330
    assert SHOT_MIN_LEVEL <= s["zoom"] <= SHOT_LEVEL
    assert s["zoom"] <= fit_zoom(s["box"], CLIP) + 1e-6
    assert s["in_end_ms"] - s["in_start_ms"] == IN_MS
    assert s["out_end_ms"] - s["out_start_ms"] == OUT_MS
    assert s["out_start_ms"] - s["in_end_ms"] >= MIN_HOLD_MS


def test_nothing_is_zoomed_when_the_voice_over_says_nothing_about_the_event() -> None:
    shots, summary = plan(
        [act("click", "b1", 2000, text="Save")],
        [say(1500, 5000, "Chúc bạn một ngày vui vẻ")],
        snap(2000, CARD, FIELD, SAVE),
    )
    assert shots == [] and summary["dropped"]["speech_not_about_it"] == 1


def test_a_block_too_big_for_the_minimum_zoom_is_not_zoomed_at_all() -> None:
    wide = item("w", "card", "Wide report Save", 40, 60, 1100, 560)
    btn = item("b", "button", "Save", 1000, 560, 100, 40)
    shots, summary = plan(
        [act("click", "b", 2000, text="Save")], [say(1500, 5000, "Bấm Save")], snap(2000, wide, btn)
    )
    assert shots == [] and summary["dropped"]["block_does_not_fit"] == 1


def test_the_result_that_appears_next_to_the_block_joins_it_and_holds_until_it_is_seen() -> None:
    shots, _ = plan(
        [act("click", "b1", 2000, text="Save")],
        [say(1500, 6500, "Bấm Save và nhân viên mới Linda Anderson xuất hiện trong danh sách")],
        snap(2000, CARD, FIELD, SAVE),
        snap(3200, CARD, ROW),
    )
    assert len(shots) == 1
    box = shots[0]["box"]
    assert box["y"] + box["h"] >= 520 + 60  # the new row is inside the zoom
    assert shots[0]["out_start_ms"] >= 3200 + 900


def test_two_events_close_together_on_one_block_share_one_zoom() -> None:
    shots, _ = plan(
        [act("type", "f1", 2000, 2400, "First name"), act("click", "b1", 3000, text="Save")],
        [say(1500, 6000, "Nhập First name rồi bấm Save")],
        snap(2000, CARD, FIELD, SAVE),
    )
    assert len(shots) == 1


def test_at_most_two_zooms_a_scene_and_one_in_a_hook_none_in_a_cta() -> None:
    a = item("a", "card", "Alpha card Open", 100, 100, 300, 200)
    ab = item("ab", "button", "Open Alpha", 200, 240, 100, 40)
    b = item("b", "card", "Beta card Open", 500, 100, 300, 200)
    bb = item("bb", "button", "Open Beta", 600, 240, 100, 40)
    c = item("c", "card", "Gamma card Open", 900, 100, 300, 200)
    cb = item("cb", "button", "Open Gamma", 1000, 240, 100, 40)
    inv = [snap(t, a, ab, b, bb, c, cb) for t in (1500, 5000, 8500)]
    actions = [act("click", "ab", 1500, text="Open Alpha"), act("click", "bb", 5000, text="Open Beta"),
               act("click", "cb", 8500, text="Open Gamma")]  # fmt: skip
    speech = [say(1000, 12000, "Open Alpha, open Beta, open Gamma card")]
    assert len(plan(actions, speech, *inv, limit_ms=13000)[0]) == 2
    assert plan(actions, speech, *inv, limit_ms=13000, scene_type="cta")[0] == []
    # a hook zooms only into a RESULT, and once
    assert plan(actions, speech, *inv, limit_ms=13000, scene_type="hook")[0] == []


def test_no_zoom_starts_in_the_first_moments_and_the_last_is_out_before_the_scene_ends() -> None:
    shots, _ = plan(
        [act("click", "b1", 100, text="Save")],
        [say(0, 3000, "Save")],
        snap(100, CARD, SAVE),
        limit_ms=4000,
    )
    assert shots == [] or shots[0]["in_start_ms"] >= 300
    late, summary = plan(
        [act("click", "b1", 3500, text="Save")],
        [say(0, 4000, "Save")],
        snap(3500, CARD, SAVE),
        limit_ms=4000,
    )
    assert late == [] and summary["dropped"]["no_room"] == 1
    ok, _ = plan(
        [act("click", "b1", 2000, text="Save")],
        [say(0, 9000, "Save")],
        snap(2000, CARD, SAVE),
        limit_ms=9000,
    )
    assert ok and ok[0]["out_end_ms"] <= 9000


def test_a_picture_is_looked_at_never_zoomed_into() -> None:
    big = item("img", "image", "Photo", 200, 100, 800, 500)
    shots, _ = plan(
        [act("click", "img", 2000, text="Photo")], [say(1000, 5000, "Photo")], snap(2000, big)
    )
    assert shots == []
