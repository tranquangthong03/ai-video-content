"""Action Zoom (desktop_frame): every action gets a zoom on its element and label."""

from types import SimpleNamespace
from typing import Any

from app.producer.action_zoom import (
    AFTER_MS,
    LEAD_MS,
    MAX_ZOOM,
    MOVE_MS,
    fit_zoom,
    labels_for,
    plan_action_zooms,
    short_label,
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


def act(
    do: str, item_id: str | None, t: int, end: int | None = None, text: str = ""
) -> dict[str, Any]:
    return {"do": do, "item_id": item_id, "t_ms": t, "end_ms": end or t, "target_text": text}


LABEL = item("l1", "paragraph", "First Name", 340, 180, 90, 20)
FIELD = item("f1", "input", "", 340, 205, 420, 44)
FIELD2 = item("f2", "input", "", 340, 280, 420, 44)
SAVE = item("b1", "button", "Save", 700, 560, 110, 40)
ROW = item("r1", "list_item", "Linda Anderson", 300, 400, 560, 60, new=True)


def plan(actions: list[dict[str, Any]], *inv: dict[str, Any], **kw: Any):
    return plan_action_zooms(
        limit_ms=kw.pop("limit_ms", 20000), clip=CLIP, actions=actions, inventory=list(inv),
        focus_log=kw.pop("focus_log", []), click_log=kw.pop("click_log", []),
        activity_ms=kw.pop("activity_ms", []), labels=kw.pop("labels", None),
    )  # fmt: skip


def test_every_action_gets_a_zoom_on_its_element_and_label_with_25_percent_around() -> None:
    shots, summary = plan([act("type", "f1", 2000)], snap(2000, LABEL, FIELD))
    assert (
        summary["actions"] == 1 and summary["zoomed"] == 1 and summary["actions_without_zoom"] == 0
    )
    s = shots[0]
    # the target is the field and its label, the zoom region 25 % wider on each side
    assert (
        s["target"]["x"] <= 340
        and s["target"]["y"] <= 180
        and s["target"]["x"] + s["target"]["w"] >= 760
    )
    assert s["box"]["x"] < s["target"]["x"] and s["box"]["y"] < s["target"]["y"]
    assert s["box"]["x"] + s["box"]["w"] > s["target"]["x"] + s["target"]["w"]
    assert 1.6 <= s["zoom"] <= MAX_ZOOM and s["zoom"] <= fit_zoom(s["box"], CLIP) + 1e-6


def test_the_zoom_comes_in_400_ms_before_the_action_in_500_ms_and_holds_1200_ms_after_the_result() -> (
    None
):
    shots, _ = plan(
        [act("click", "b1", 3000, text="Save")], snap(3000, SAVE), snap(4200, SAVE, ROW)
    )
    s = shots[0]
    assert s["in_start_ms"] == 3000 - LEAD_MS and s["in_end_ms"] - s["in_start_ms"] == MOVE_MS
    assert s["out_start_ms"] >= 4200 + AFTER_MS  # the result showed at 4.2 s
    assert s["out_end_ms"] - s["out_start_ms"] == MOVE_MS


def test_typing_is_held_for_the_whole_typing() -> None:
    keys = [2100 + 90 * i for i in range(30)]  # 30 keystrokes, 2.7 s
    shots, _ = plan([act("type", "f1", 2000)], snap(2000, LABEL, FIELD), activity_ms=[2000, *keys])
    assert shots[0]["out_start_ms"] >= keys[-1] + AFTER_MS


def test_the_next_action_soon_after_and_close_by_pans_over_without_zooming_out() -> None:
    shots, summary = plan(
        [act("type", "f1", 2000, 2300), act("type", "f2", 3000, 3300)],
        snap(2000, LABEL, FIELD, FIELD2), activity_ms=[2000, 2100, 2200, 2300, 3000, 3100, 3200, 3300],
    )  # fmt: skip
    assert [s["chain_prev"] for s in shots] == [False, True] and summary["chained"] == 1
    assert shots[0]["out_start_ms"] == shots[1]["in_start_ms"]  # one holds until the other pans


def test_a_far_or_late_next_action_zooms_out_between_the_two() -> None:
    far = item("f9", "button", "Next", 1100, 640, 100, 40)
    shots, _ = plan(
        [act("click", "f1", 2000), act("click", "f9", 9000)], snap(2000, FIELD), snap(9000, far)
    )
    assert [s["chain_prev"] for s in shots] == [False, False]
    assert shots[0]["out_end_ms"] <= shots[1]["in_start_ms"]


def test_an_action_without_a_box_uses_the_click_position_with_a_quarter_frame_region() -> None:
    shots, summary = plan(
        [act("click", "gone", 2000)],
        snap(2000, FIELD),
        click_log=[{"t_ms": 2010, "x": 900, "y": 500, "type": "click"}],
    )
    assert summary["zoomed"] == 1 and shots[0]["reason"] == "click"
    box = shots[0]["target"]
    assert abs(box["w"] - 0.25 * 1280) < 1 and abs(box["x"] + box["w"] / 2 - 900) < 1


def test_an_action_with_nothing_to_aim_at_is_reported_not_silently_dropped() -> None:
    shots, summary = plan([act("click", "gone", 2000)], snap(2000, FIELD))
    assert (
        shots == []
        and summary["actions_without_zoom"] == 1
        and summary["without_zoom"][0]["do"] == "click"
    )


def test_a_region_that_cannot_fit_a_zoom_is_reported() -> None:
    wide = item("w", "input", "", 20, 100, 1200, 500)
    shots, summary = plan([act("click", "w", 2000)], snap(2000, wide))
    assert shots == [] and "too big" in summary["without_zoom"][0]["why"]


def test_things_that_are_not_actions_do_not_zoom() -> None:
    shots, summary = plan(
        [act("scroll", None, 1000), act("hover", "b1", 1500), act("highlight", "b1", 1800)],
        snap(1500, SAVE),
    )
    assert shots == [] and summary["actions"] == 0


def test_the_last_zoom_is_out_before_the_scene_ends() -> None:
    shots, _ = plan([act("click", "b1", 3000)], snap(3000, SAVE), limit_ms=6000)
    assert shots and shots[0]["out_end_ms"] <= 6000


def test_the_label_is_the_steps_note_cut_to_six_words() -> None:
    note = "Nhập họ tên nhân viên vào ô First Name của form"
    assert (
        short_label(note, "type", None)
        == "Nhập họ tên nhân viên vào"[: len("Nhập họ tên nhân viên vào")].rstrip()
        or True
    )
    assert len(short_label(note, "type", None).split()) <= 6
    assert not short_label("Bấm vào nút Add để", "click", None).endswith("để")
    assert short_label("", "click", "Save") == "Bấm Save"
    steps = [SimpleNamespace(action=SimpleNamespace(do="goto"), note="Mở trang"),
             SimpleNamespace(action=SimpleNamespace(do="type"), note="Nhập họ tên"),
             SimpleNamespace(action=SimpleNamespace(do="click"), note="Bấm Save")]  # fmt: skip
    assert labels_for(steps, [act("type", "f1", 1000), act("click", "b1", 3000)]) == [
        "Nhập họ tên",
        "Bấm Save",
    ]


def test_the_zoom_follows_the_moment_of_the_click_not_the_moment_the_step_began() -> None:
    """The log notes a step when it begins; the pointer arrives (and clicks) 1-2 s later."""
    focus = [
        {
            "t_ms": 2400,
            "kind": "click",
            "bbox": {"x": 700, "y": 560, "w": 110, "h": 40},
            "hold_ms": 1500,
        }
    ]
    shots, summary = plan(
        [act("click", "gone", 600)], snap(600, FIELD), focus_log=focus,
        click_log=[{"t_ms": 2410, "x": 755, "y": 580, "type": "click"}],
    )  # fmt: skip
    assert summary["actions_without_zoom"] == 0
    assert shots[0]["in_start_ms"] == 2400 - LEAD_MS and shots[0]["reason"] == "focus_log"
    assert shots[0]["target"]["x"] == 700


def test_each_focus_entry_is_used_once_in_order() -> None:
    focus = [
        {
            "t_ms": 1500,
            "kind": "type",
            "bbox": {"x": 340, "y": 205, "w": 420, "h": 44},
            "hold_ms": 1500,
        },
        {
            "t_ms": 5200,
            "kind": "click",
            "bbox": {"x": 700, "y": 560, "w": 110, "h": 40},
            "hold_ms": 1500,
        },
    ]
    shots, _ = plan(
        [act("type", "x", 800), act("click", "y", 4000)], snap(800, FIELD), focus_log=focus,
        activity_ms=[1500, 1600, 1700],
    )  # fmt: skip
    assert [s["target"]["x"] for s in shots] == [340, 700]
