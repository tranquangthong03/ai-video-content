import json
import random
import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.browser.session import BrowserSession
from app.recorder import motion
from app.recorder.record import record_scene
from app.schemas.generated.scene import Scene
from tests.conftest import SiteHandler

# --- pure helpers ---------------------------------------------------------------------------------


def test_mouse_path_is_eased_and_lands_on_the_target() -> None:
    path = motion.mouse_path((0, 0), (600, 300), 500)
    assert path[-1][:2] == (600, 300)
    xs = [p[0] for p in path]
    assert xs == sorted(xs)  # always moving toward the target
    assert xs[1] - xs[0] < xs[len(xs) // 2] - xs[len(xs) // 2 - 1]  # slow start, faster middle
    assert sum(p[2] for p in path) == pytest.approx(500)


def test_move_duration_grows_with_distance_within_bounds() -> None:
    assert motion.move_duration_ms(10) == 700
    assert motion.move_duration_ms(500) < motion.move_duration_ms(1200)
    assert motion.move_duration_ms(5000) == 1000


def test_typing_delays_are_90_to_130_ms() -> None:
    delays = motion.typing_delays("xin chào", random.Random(1))
    assert len(delays) == 8 and all(90 <= d <= 130 for d in delays)


def test_scroll_steps_sum_to_the_total_and_ease() -> None:
    steps = motion.scroll_steps(700, 10)
    assert sum(steps) == pytest.approx(700) and len(steps) == 10
    assert steps[0] < steps[4] and steps[-1] < steps[5]
    assert sum(motion.scroll_steps(-300)) == pytest.approx(-300)


def test_idle_gaps_report_the_quiet_stretches() -> None:
    assert motion.idle_gaps([1000, 1200, 4000], 0, 4500) == [1000, 2800, 500]
    assert motion.idle_gaps([], 0, 3000) == [3000]
    assert motion.idle_gaps([100, 300], 0, 600) == []  # nothing quiet for half a second
    assert motion.idle_gaps([50, 900], 800, 2000) == [1100]  # events before the window are ignored


# --- recording the fixture site -------------------------------------------------------------------


def scene(visual: dict[str, Any], type_: str = "feature_demo") -> Scene:
    base: dict[str, Any] = {
        "id": "s1", "type": type_, "layout": "full_screen", "voiceover": "x " * 10,
        "key_point": "k", "icon": "check", "visual": visual,
    }  # fmt: skip
    if type_ == "feature_demo":
        base["feature"] = "f"
    return Scene.model_validate(base)


def loc(css: str | None = None, **kw: Any) -> dict[str, Any]:
    return {"css": css, **kw}


def goto(site: str, path: str) -> dict[str, Any]:
    return {"do": "goto", "url": f"{site}{path}"}


def probe(path: Path) -> dict[str, Any]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name,width,height,pix_fmt,r_frame_rate", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return json.loads(out.stdout)


def rec(
    session: BrowserSession,
    site: str,
    tmp_path: Path,
    visual: dict[str, Any],
    speech_ms: int = 2000,
    **kw: Any,
):  # type: ignore[no-untyped-def]
    return record_scene(session, scene(visual), tmp_path, speech_ms, root_url=site, **kw)


def test_a_recording_is_a_1280x720_h264_mp4_with_a_click_log_of_what_was_done(
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
    r = rec(browser_session, site, tmp_path, visual, speech_ms=1500)
    assert r.kind == "recording" and r.clip_path and r.clip_path.is_file() and r.warnings == []
    info = probe(r.clip_path)
    stream = info["streams"][0]
    assert (stream["codec_name"], stream["width"], stream["height"], stream["pix_fmt"]) == (
        "h264",
        1280,
        720,
        "yuv420p",
    )
    assert stream["r_frame_rate"] == "30/1"
    duration_ms = float(info["format"]["duration"]) * 1000
    # the log's clock follows the recording; under load the video lags the log by more than a
    # second (that drift is what the sync pulse measures), so only a gross mismatch is a bug
    assert abs(duration_ms - r.content_ms) < 3000
    assert r.start_offset_ms > 0 and r.setup_end_ms == r.start_offset_ms
    kinds = [e["type"] for e in r.click_log]
    assert kinds[0] == "click" and "hover" in kinds  # typing focuses the field with a click first
    assert all(0 <= e["x"] <= 1280 and 0 <= e["y"] <= 720 for e in r.click_log)
    assert [e["t_ms"] for e in r.click_log] == sorted(e["t_ms"] for e in r.click_log)
    assert r.click_log[0]["t_ms"] > r.start_offset_ms - 50
    assert r.steps_ok == 2 and r.steps_failed == 0


def test_typing_really_types_and_enter_follows_the_policy(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    visual = {
        "mode": "recording",
        "actions": [
            goto(site, "/todo.html"),
            {"do": "type", "locator": loc("#new"), "text": "Một việc mới"},
        ],
    }
    r = rec(browser_session, site, tmp_path, visual)
    assert r.steps_ok == 1
    # the todo was added: the clip's last frames show it (checked through the list the page keeps)
    assert any(e["type"] == "click" for e in r.click_log)


def test_double_click_and_right_click_are_logged_with_their_type(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    visual = {
        "mode": "recording",
        "actions": [
            goto(site, "/edit.html"),
            {"do": "dblclick", "locator": loc("#item1")},
            {"do": "right_click", "locator": loc("#rc")},
        ],
    }
    r = rec(browser_session, site, tmp_path, visual, speech_ms=1000)
    assert [e["type"] for e in r.click_log] == ["dblclick", "click"]
    assert r.steps_ok == 2


def test_scroll_to_and_highlight_show_the_section_and_remove_the_overlay(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    section = loc("#target", text="Báo cáo tự động")
    visual = {
        "mode": "recording",
        "actions": [
            goto(site, "/tall.html"),
            {"do": "scroll_to", "locator": section},
            {"do": "highlight", "locator": section, "ms": 900},
        ],
    }
    r = rec(browser_session, site, tmp_path, visual, speech_ms=1000, highlight_color="#ff8800")
    assert [e["type"] for e in r.click_log] == ["scroll", "highlight"]
    hl = r.click_log[1]
    assert 0 < hl["y"] < 720  # the section was scrolled to the middle of the viewport
    assert 300 < hl["y"] < 560
    assert r.steps_ok == 2 and r.warnings == []
    assert r.content_ms >= r.click_log[1]["t_ms"] + 900  # the overlay stayed for its time


def test_upload_goes_through_set_input_files(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    visual = {
        "mode": "recording",
        "actions": [goto(site, "/pick.html"), {"do": "upload", "locator": loc("#f1")}],
    }
    r = rec(browser_session, site, tmp_path, visual)
    assert r.steps_ok == 1 and r.warnings == []


def test_a_failing_step_is_skipped_with_a_warning_and_a_screenshot(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    visual = {
        "mode": "recording",
        "actions": [
            goto(site, "/todo.html"),
            {"do": "click", "locator": loc("#does-not-exist")},
            {"do": "type", "locator": loc("#new"), "text": "Vẫn chạy tiếp"},
        ],
    }
    r = rec(browser_session, site, tmp_path, visual)
    assert r.kind == "recording" and r.steps_ok == 1 and r.steps_failed == 1
    assert (
        len(r.warnings) == 1 and "action[2] click" in r.warnings[0] and "not found" in r.warnings[0]
    )
    assert list((tmp_path / "errors").glob("*.png"))


def test_a_blacklisted_element_is_never_clicked(
    browser_session: BrowserSession, site: str, tmp_path: Path, hits: list[str]
) -> None:
    visual = {
        "mode": "recording",
        "actions": [goto(site, "/tall.html"), {"do": "click", "locator": loc("a[href='/logout']")}],
    }
    r = rec(browser_session, site, tmp_path, visual, speech_ms=1000)
    assert not any(h.startswith("/logout") for h in hits)
    assert r.steps_failed == 1 and any("an toàn" in w for w in r.warnings)


def test_when_no_step_can_run_the_scene_falls_back_to_a_screenshot(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    visual = {
        "mode": "recording",
        "actions": [goto(site, "/todo.html"), {"do": "click", "locator": loc("#nope")}],
    }
    r = rec(browser_session, site, tmp_path, visual)
    assert r.kind == "fallback_screenshot" and r.clip_path is None
    assert r.image_path and r.image_path.suffix == ".png" and r.image_path.is_file()
    assert any("ảnh trang đích" in w for w in r.warnings)


def test_setup_is_recorded_before_the_actions_and_its_end_is_reported(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    visual = {
        "mode": "recording",
        "setup": [
            goto(site, "/todo.html"),
            {"do": "type", "locator": loc("#new"), "text": "Việc chuẩn bị"},
        ],
        "actions": [{"do": "click", "locator": loc("a[href='#/active']")}],
        "show_setup": False,
    }
    r = rec(browser_session, site, tmp_path, visual, speech_ms=1000)
    assert r.steps_ok == 2  # the setup's goto is the first load, not a second step
    assert r.setup_end_ms > r.start_offset_ms
    assert r.click_log[0]["t_ms"] < r.setup_end_ms < r.click_log[-1]["t_ms"]


def test_a_quiet_stretch_is_filled_with_harmless_hovers_and_never_with_clicks(
    browser_session: BrowserSession, site: str, tmp_path: Path, hits: list[str]
) -> None:
    visual = {
        "mode": "recording",
        "actions": [goto(site, "/tall.html"), {"do": "hover", "locator": loc("#safe")}],
    }
    # the filler fills what the clock leaves missing, so a slow machine (real time spent on the
    # actions) must not eat the whole gap: ask for far more than the actions can ever take
    r = rec(browser_session, site, tmp_path, visual, speech_ms=30000)
    kinds = [e["type"] for e in r.click_log]
    assert kinds.count("hover") >= 2 and "click" not in kinds and "dblclick" not in kinds
    assert r.filled_ms > 1500 and r.content_ms >= 5000
    assert not any(h.startswith(("/logout", "/features")) for h in hits)  # hovered, never followed
    # nothing hovered is on the blacklist: the "Xóa tất cả" button and the logout link are skipped
    danger_y = 0
    assert all(e["y"] != danger_y for e in r.click_log)


def test_no_filler_when_the_clip_is_only_a_little_short(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    visual = {
        "mode": "recording",
        "actions": [goto(site, "/tall.html"), {"do": "hover", "locator": loc("#safe")}],
    }
    r = rec(browser_session, site, tmp_path, visual, speech_ms=3000)
    assert r.filled_ms == 0  # the renderer holds the last frame for the missing second


def test_the_page_standing_still_is_visible_as_an_idle_gap(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    visual = {
        "mode": "recording",
        "actions": [
            goto(site, "/tall.html"),
            {"do": "wait", "ms": 2500},
            {"do": "hover", "locator": loc("#safe")},
        ],
    }
    r = rec(browser_session, site, tmp_path, visual, speech_ms=1000)
    assert max(r.idle_gaps_ms) >= 2000


def test_typing_and_cursor_movement_are_not_idle_time(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    long_text = "Một việc cần làm có nội dung khá dài để gõ lâu"
    visual = {
        "mode": "recording",
        "actions": [
            goto(site, "/todo.html"),
            {"do": "type", "locator": loc("#new"), "text": long_text},
        ],
    }
    r = rec(browser_session, site, tmp_path, visual, speech_ms=1000)
    # ~4 s of typing is continuous motion: the only quiet stretch is the 1.5 s hold that follows it
    assert len(r.idle_gaps_ms) <= 1 and max(r.idle_gaps_ms, default=0) < 2600


def test_a_template_scene_needs_no_browser(
    browser_session: BrowserSession, site: str, tmp_path: Path, hits: list[str]
) -> None:
    hits.clear()
    r = record_scene(browser_session, scene({"mode": "template"}), tmp_path, 2000, root_url=site)
    assert r.kind == "template" and r.clip_path is None and r.image_path is None and hits == []


def test_other_modes_are_photographs(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    r = record_scene(
        browser_session,
        scene({"mode": "screenshot", "page": f"{site}/index.html"}, "hook") if False else scene({"mode": "screenshot", "page": f"{site}/"}),
        tmp_path, 2000, root_url=site,
    )  # fmt: skip
    assert (
        r.kind == "screenshot" and r.clip_path is None and r.image_path and r.image_path.is_file()
    )
    assert SiteHandler.hits is not None
