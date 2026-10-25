from typing import Any

from app.core.textmatch import text_matches
from app.producer.focus_rules import (
    MIN_FOCUS_MS,
    Seg,
    build_focus_track,
    contains,
    find_item,
    focus_box,
    tidy,
)

CLIP = (1440, 900)


def item(
    id: str, kind: str, text: str, x: int, y: int, w: int, h: int,
    region: str = "main", is_new: bool = False,
) -> dict[str, Any]:  # fmt: skip
    return {
        "id": id, "role": kind, "tag": "div", "text": text, "kind": kind, "region": region,
        "is_new": is_new, "bbox": {"x": x, "y": y, "w": w, "h": h},
    }  # fmt: skip


# todomvc: a sidebar on the left, the app in the middle (the case that went wrong)
SIDEBAR = item("side", "sidebar", "React Official Resources", 0, 0, 300, 700, region="aside")
SIDE_TEXT = item("sidetxt", "paragraph", "Official Resources", 10, 600, 280, 40, region="aside")
TITLE = item("title", "heading", "todos", 600, 60, 240, 90)
INPUT = item("in", "input", "What needs to be done?", 480, 170, 480, 60)
TODO = item("li1", "list_item", "Mua sữa", 480, 240, 480, 56, is_new=True)
BASE_ITEMS = [SIDEBAR, SIDE_TEXT, TITLE, INPUT]


def snap(t: int, *items: dict[str, Any]) -> dict[str, Any]:
    return {"t_ms": t, "items": list(items)}


TYPE = {"t_ms": 1200, "end_ms": 2300, "do": "type", "target_text": "", "item_id": "in"}
INV = [
    snap(300, *BASE_ITEMS),
    snap(1250, *BASE_ITEMS),
    snap(2400, *BASE_ITEMS, TODO),
    snap(3400, *BASE_ITEMS, TODO),
]


def run(**kw: Any):  # type: ignore[no-untyped-def]
    args: dict[str, Any] = {
        "duration_ms": 5000, "clip": CLIP, "inventory": INV, "action_log": [TYPE],
        "phrases": [], "plan": None, "legacy_focus": [],
    }  # fmt: skip
    return build_focus_track(**{**args, **kw})


def test_while_typing_the_focus_is_the_input_even_against_a_plan() -> None:
    plan = [
        {"from_ms": 0, "to_ms": 1000, "item_id": None, "framing": "establish", "reason": "m"},
        {"from_ms": 1000, "to_ms": 5000, "item_id": "title", "framing": "medium", "reason": "x"},
    ]
    r = run(plan=plan)
    typing = next(t for t in r.track if t["item_id"] == "in")
    assert typing["source"] == "rule" and typing["framing"] == "tight"
    assert typing["t_ms"] <= 1200 < typing["t_ms"] + typing["hold_ms"]
    assert typing["hold_ms"] >= MIN_FOCUS_MS


def test_after_the_action_the_focus_is_the_new_item_not_the_sidebar() -> None:
    r = run()
    after = [t for t in r.track if t["t_ms"] >= 2300]
    assert after[0]["item_id"] == "li1" and after[0]["source"] == "rule"
    assert not any(t["region"] == "aside" for t in r.track)  # "React / Official Resources"


def test_a_sidebar_focus_from_the_plan_is_dropped_unless_the_voice_names_it() -> None:
    plan = [{"from_ms": 0, "to_ms": 5000, "item_id": "sidetxt", "framing": "medium", "reason": ""}]
    silent = run(
        plan=plan, action_log=[], phrases=[{"from_ms": 0, "to_ms": 5000, "text": "Gõ việc"}]
    )
    assert silent.metrics["replaced_side_focus"] == 1
    assert all(t["region"] != "aside" for t in silent.track)
    said = run(
        plan=plan, action_log=[],
        phrases=[{"from_ms": 0, "to_ms": 5000, "text": "Xem Official Resources của React"}],
    )  # fmt: skip
    assert said.metrics["replaced_side_focus"] == 0
    focus = next(t for t in said.track if t["framing"] != "establish")
    assert focus["item_id"] == "sidetxt" and focus["source"] == "plan"


def test_the_focus_grows_to_the_whole_text_block_so_nothing_is_cut() -> None:
    card = item("card", "card", "", 400, 300, 640, 300)
    head = item("h", "heading", "Lộ trình học", 430, 320, 300, 40)
    para = item("p", "paragraph", "Chọn vai trò của bạn", 430, 370, 560, 80)
    overflow = item("p2", "paragraph", "để xem lộ trình", 430, 440, 600, 60)
    box = focus_box(head, [card, head, para, overflow], CLIP)
    assert contains(box, para["bbox"]) and contains(box, overflow["bbox"])
    assert contains(box, head["bbox"])


def test_an_image_is_shown_whole_with_its_label_and_never_zoomed_into() -> None:
    img = item("img", "image", "", 300, 200, 800, 500)
    label = item("lbl", "paragraph", "Large photo 2.8MB", 300, 710, 300, 30)
    far = item("far", "paragraph", "Footer text", 10, 880, 200, 20)
    inv = [snap(500, img, label, far)]
    track = run(
        inventory=inv,
        action_log=[{"t_ms": 400, "end_ms": 900, "do": "upload", "item_id": "img", "target_text": ""}],
        duration_ms=4000,
    )  # fmt: skip
    focus = next(t for t in track.track if t["item_id"] == "img")
    assert focus["framing"] == "wide"
    assert contains(focus["bbox"], img["bbox"]) and contains(focus["bbox"], label["bbox"])
    assert not contains(focus["bbox"], far["bbox"])


def test_no_focus_is_shorter_than_1500_ms_except_the_opening_shot() -> None:
    segs = [
        Seg(0, 1000, None, "establish"),
        Seg(1000, 1600, "a"),
        Seg(1600, 4000, "b"),
        Seg(4000, 4400, "c"),
        Seg(4400, 7000, "d"),
    ]
    out = tidy(segs, 7000)
    assert out[0].framing == "establish" and out[0].length == 1000
    assert all(s.length >= MIN_FOCUS_MS for s in out[1:])
    assert out[0].from_ms == 0 and out[-1].to_ms == 7000
    assert all(a.to_ms == b.from_ms for a, b in zip(out, out[1:], strict=False))


def test_the_track_covers_the_whole_clip_and_names_its_sources() -> None:
    r = run()
    assert r.track[0]["t_ms"] == 0 and r.track[0]["framing"] == "establish"
    ends = [t["t_ms"] + t["hold_ms"] for t in r.track]
    assert ends[-1] == 5000 and all(
        a["t_ms"] + a["hold_ms"] == b["t_ms"] for a, b in zip(r.track, r.track[1:], strict=False)
    )
    assert {t["source"] for t in r.track} <= {"plan", "rule", "fallback"}


def test_an_unknown_item_falls_back_to_the_old_focus_or_to_the_whole_page() -> None:
    plan = [{"from_ms": 0, "to_ms": 4000, "item_id": "gone", "framing": "tight", "reason": ""}]
    legacy = [{"t_ms": 0, "kind": "click", "bbox": {"x": 10, "y": 20, "w": 100, "h": 50}}]
    old = run(plan=plan, action_log=[], legacy_focus=legacy, duration_ms=4000)
    body = [t for t in old.track if t["framing"] != "establish"]
    assert body[0]["source"] == "fallback" and body[0]["bbox"]["x"] == 10
    none = run(plan=plan, action_log=[], legacy_focus=[], duration_ms=4000)
    assert none.track[-1]["bbox"] == {"x": 0, "y": 0, "w": 1440, "h": 900}
    assert none.metrics["unresolved"] == 1


def test_find_item_takes_the_snapshot_closest_in_time() -> None:
    moved = item("e", "button", "Go", 100, 100, 50, 20)
    later = item("e", "button", "Go", 100, 400, 50, 20)
    inv = [snap(0, moved), snap(3000, later)]
    assert find_item(inv, "e", 2500)[0]["bbox"]["y"] == 400  # type: ignore[index]
    assert find_item(inv, "zz", 0) is None


def test_speech_matching_ignores_accents_and_small_differences() -> None:
    assert text_matches("Official Resources", "xem official resource của React")
    assert text_matches("Lộ trình học", "lo trinh hoc theo vai tro")
    assert not text_matches("Official Resources", "gõ việc cần làm")
