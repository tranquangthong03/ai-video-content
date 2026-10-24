"""Calm pacing, the focus log the camera follows, and the 1440x900 capture."""

import random
from pathlib import Path

from app.browser.session import BrowserSession
from app.recorder import motion
from app.script.visuals import cap_main_actions, main_count
from tests.test_recorder import goto, loc, probe, rec


def test_the_pace_is_calm() -> None:
    assert motion.move_duration_ms(0) == 700 and motion.move_duration_ms(5000) == 1000
    assert 700 <= motion.move_duration_ms(400) <= 1000
    delays = motion.typing_delays("xin chào các bạn", random.Random(3))
    assert all(90 <= d <= 130 for d in delays)


def test_main_actions_leave_a_focus_log_with_boxes_and_a_hold(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    visual = {
        "mode": "recording",
        "actions": [
            goto(site, "/todo.html"),
            {"do": "type", "locator": loc("#new"), "text": "Viết báo cáo tuần"},
            {"do": "hover", "locator": loc("#items")},
        ],
    }
    r = rec(browser_session, site, tmp_path, visual, speech_ms=1000)
    assert (r.width, r.height) == (1440, 900)
    assert [f["kind"] for f in r.focus_log] == ["type", "hover"]
    assert [f["hold_ms"] for f in r.focus_log] == [1500, 1500]
    assert [f["t_ms"] for f in r.focus_log] == sorted(f["t_ms"] for f in r.focus_log)
    for f in r.focus_log:
        b = f["bbox"]
        assert b["w"] > 0 and b["h"] > 0 and 0 <= b["x"] and b["x"] + b["w"] <= 1440
        assert 0 <= b["y"] and b["y"] + b["h"] <= 900
    assert r.focus_log[0]["bbox"]["w"] > 100  # the input box, not a point


def test_setup_steps_get_no_hold(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    visual = {
        "mode": "recording",
        "show_setup": True,
        "setup": [
            goto(site, "/todo.html"),
            {"do": "type", "locator": loc("#new"), "text": "Một việc"},
        ],
        "actions": [{"do": "hover", "locator": loc("#filters a:nth-of-type(2)"), "ms": 300}],
    }
    r = rec(browser_session, site, tmp_path, visual, speech_ms=1000)
    by_kind = {f["kind"]: f for f in r.focus_log}
    assert by_kind["type"]["hold_ms"] == 0  # setup: only the means
    assert by_kind["hover"]["hold_ms"] == 300  # a pointing hover holds for its own time


def test_scrolling_logs_the_block_in_the_middle_and_scroll_to_the_section(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    visual = {
        "mode": "recording",
        "actions": [
            goto(site, "/tall.html"),
            {"do": "scroll", "ms": 900},
            {"do": "scroll_to", "locator": loc("#target", text="Báo cáo tự động")},
        ],
    }
    r = rec(browser_session, site, tmp_path, visual, speech_ms=1000)
    kinds = [f["kind"] for f in r.focus_log]
    assert kinds.count("scroll") >= 2 and kinds[-1] == "section"
    section = r.focus_log[-1]
    assert section["hold_ms"] == 1500 and section["bbox"]["w"] > 0
    assert all(0 <= f["bbox"]["x"] and f["bbox"]["y"] + f["bbox"]["h"] <= 900 for f in r.focus_log)


def test_a_capture_size_other_than_the_default_is_honoured(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    visual = {"mode": "recording", "actions": [goto(site, "/todo.html"), {"do": "wait", "ms": 300}]}
    r = rec(browser_session, site, tmp_path, visual, viewport={"width": 800, "height": 600})
    assert r.clip_path is not None
    stream = probe(r.clip_path)["streams"][0]
    assert (stream["width"], stream["height"]) == (800, 600) and (r.width, r.height) == (800, 600)


def test_a_scene_keeps_at_most_three_main_actions_and_says_so() -> None:
    actions = [{"do": "goto"}, {"do": "click"}, {"do": "type"}, {"do": "wait"}, {"do": "click"}]
    actions += [{"do": "hover"}, {"do": "highlight"}]
    warnings: list[str] = []
    kept = cap_main_actions(actions, warnings, "f1")
    assert main_count(kept) == 3
    assert [a["do"] for a in kept] == ["goto", "click", "type", "wait", "click"]
    assert warnings == ["f1: chỉ giữ 3 thao tác chính mỗi cảnh, bỏ 2"]
    assert cap_main_actions(actions[:3], warnings, "f1") == actions[:3] and len(warnings) == 1
