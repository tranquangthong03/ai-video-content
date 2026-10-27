"""M1-4a rules as pure functions: hero window, shots, dead frames, close frames, text cards."""

import subprocess
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw

from app.core.hero import hero_window
from app.producer.dead_frames import (
    FrameStat,
    cut_dead,
    dead_ms,
    dead_runs,
    stat_of,
)
from app.producer.focus_rules import enforce_hook_framing, with_context
from app.producer.pipeline import ClipPlan, shots_for_scene
from app.producer.shots import MAX_STATIC_MS, max_static_ms, phrase_shots, plan_shots
from app.producer.text_cards import text_card_stats
from tests.test_focus_rules import CLIP, INPUT, TITLE, TODO, item, snap


def test_the_hook_window_is_two_seconds_around_the_hero_inside_the_clip() -> None:
    a, b = hero_window(10_000, 30_000)
    assert 1500 <= b - a <= 2500 and a < 10_000 < b
    assert hero_window(100, 30_000)[0] == 0  # near the start: no negative time
    a, b = hero_window(29_900, 30_000)
    assert b <= 30_000 and b - a >= 1500  # near the end: pulled back inside
    assert hero_window(0, 1200) == (0, 1200)  # a tiny clip is all hook


# --- shots -----------------------------------------------------------------------------------

CAPTIONS = [
    {"text": "a", "start_ms": 0, "end_ms": 1800},
    {"text": "b", "start_ms": 1900, "end_ms": 3700},
    {"text": "c", "start_ms": 3800, "end_ms": 5000},
]


def test_one_shot_per_phrase_and_they_fill_the_scene() -> None:
    assert phrase_shots(CAPTIONS, 5200) == [(0, 1900), (1900, 3800), (3800, 5200)]
    assert phrase_shots([], 3000) == [(0, 3000)]


def test_a_shot_that_starts_with_a_change_needs_no_punch_a_quiet_one_gets_one() -> None:
    shots, punches = plan_shots(
        CAPTIONS, 5200, focus_times=[1950.0], action_times=[3700.0], cut_times=[0.0]
    )
    assert [s.change for s in shots] == ["cut", "focus", "action"]
    assert punches == []
    shots, punches = plan_shots(CAPTIONS, 5200, focus_times=[], action_times=[])
    assert [s.change for s in shots] == ["cut", "punch", "punch"]
    assert [p["t_ms"] for p in punches] == [1900, 3800]
    assert all(0.08 <= p["scale"] <= 0.12 for p in punches)


def test_no_stretch_of_a_long_shot_stays_unchanged_for_more_than_three_seconds() -> None:
    one = [{"text": "x", "start_ms": 0, "end_ms": 11_000}]
    shots, punches = plan_shots(one, 11_500, focus_times=[], action_times=[])
    assert len(shots) == 1 and len(punches) >= 3
    assert max_static_ms(11_500, [], [], punches) <= MAX_STATIC_MS
    assert max_static_ms(11_500, [], [], []) == 11_500  # without punches the whole scene is static
    # real changes count as much as punches
    _, few = plan_shots(one, 11_500, focus_times=[2500.0, 5000.0, 8000.0], action_times=[])
    assert max_static_ms(11_500, [2500.0, 5000.0, 8000.0], [], few) <= MAX_STATIC_MS


def test_shots_for_a_scene_are_on_the_scene_axis_after_the_lead_and_the_rate() -> None:
    plan = ClipPlan(Path("c.mp4"), 1000, 500, 12_000, 10_500, [], [], [])
    plan.action_log = [{"t_ms": 1500 + 3800, "end_ms": 1500 + 4200, "do": "click"}]
    entry = {"focus_track": [{"t_ms": 1500 + 1900}]}
    got = shots_for_scene(entry, plan, 1.0, 5200, CAPTIONS)
    assert [s["change"] for s in got["shots"]] == ["cut", "focus", "action"]
    assert got["max_static_ms"] <= MAX_STATIC_MS


# --- dead frames ------------------------------------------------------------------------------


def test_a_flat_frame_is_dead_a_page_with_content_is_not() -> None:
    flat = Image.new("L", (160, 100), 255)
    page = Image.new("L", (160, 100), 255)
    draw = ImageDraw.Draw(page)
    for y in range(10, 90, 14):
        draw.rectangle((10, y, 150, y + 6), fill=40)
    assert stat_of(flat, 0).dead and not stat_of(page, 0).dead
    spinner = Image.new("L", (160, 100), 245)
    ImageDraw.Draw(spinner).ellipse((76, 46, 84, 54), fill=200)
    assert stat_of(spinner, 0).dead  # a tiny spinner on a flat page says nothing


def stats(pattern: str, step: int = 100) -> list[FrameStat]:
    """'.' = a page with content, 'x' = a dead frame."""
    return [
        FrameStat(n * step, 0.0 if c == "x" else 60.0, 0.0 if c == "x" else 20.0)
        for n, c in enumerate(pattern)
    ]


def test_only_runs_of_300ms_or_more_count_as_dead() -> None:
    assert dead_runs(stats("..xx..")) == []  # 200 ms: a blink
    assert dead_runs(stats("..xxx..")) == [(200, 500)]
    assert dead_runs(stats("xxxx....xxxx")) == [(0, 400), (800, 1200)]  # also at both ends


def make_clip(path: Path, blank_s: float, content_s: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"color=c=white:s=320x200:d={blank_s}:r=30",
         "-f", "lavfi", "-i", f"testsrc=s=320x200:d={content_s}:r=30",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True,
    )  # fmt: skip


@pytest.mark.slow
def test_a_blank_stretch_is_cut_out_of_a_real_clip(tmp_path: Path) -> None:
    clip = tmp_path / "s1.mp4"
    make_clip(clip, 1.2, 3.0)
    assert 1000 <= dead_ms(clip) <= 1400
    cut = cut_dead(clip, "s1", 0, 4200)
    assert cut is not None and cut[1][0][0] == 0 and 1100 <= cut[1][0][1] <= 1300
    assert dead_ms(clip) == 0  # the new clip has none left
    assert (tmp_path / "s1_nodead_raw.mp4").is_file()  # the raw one is kept


@pytest.mark.slow
def test_a_clip_that_is_all_blank_is_left_alone(tmp_path: Path) -> None:
    clip = tmp_path / "s2.mp4"
    make_clip(clip, 1.5, 0.2)
    assert cut_dead(clip, "s2", 0, 1700) is None  # cutting would leave nothing to show


# --- close frames -----------------------------------------------------------------------------

LABEL = item("lab", "paragraph", "Tên nhân viên", 480, 130, 200, 30)


def test_a_tight_frame_keeps_the_nearest_label_in_view() -> None:
    box, grew = with_context(INPUT, dict(INPUT["bbox"]), [INPUT, LABEL, TITLE], CLIP)
    assert (
        grew
        and box["y"] <= LABEL["bbox"]["y"]
        and box["y"] + box["h"] >= INPUT["bbox"]["y"] + INPUT["bbox"]["h"]
    )
    far = item("far", "paragraph", "Chân trang", 480, 880, 200, 20)
    same, grew = with_context(INPUT, dict(INPUT["bbox"]), [INPUT, far], CLIP)
    assert not grew and same == INPUT["bbox"]
    big = item("big", "heading", "Rất lớn", 0, 0, 1440, 600)
    assert (
        with_context(INPUT, dict(INPUT["bbox"]), [INPUT, big], CLIP)[1] is False
    )  # would fill the view


def test_a_hook_never_opens_on_the_whole_page() -> None:
    inventory = [snap(0, TITLE, INPUT, TODO)]
    track: list[dict[str, Any]] = [
        {"t_ms": 0, "bbox": {"x": 0, "y": 0, "w": 1440, "h": 900}, "framing": "establish", "hold_ms": 1000, "source": "rule", "item_id": None, "text": ""},
        {"t_ms": 1000, "bbox": {"x": 480, "y": 170, "w": 480, "h": 60}, "framing": "tight", "hold_ms": 1000, "source": "plan", "item_id": "in", "text": "x"},
    ]  # fmt: skip
    fixed, n = enforce_hook_framing(track, inventory, CLIP)
    assert (
        n == 1 and fixed[0]["framing"] in ("tight", "medium") and fixed[0]["item_id"] == "li1"
    )  # what is new
    assert fixed[1] == track[1]
    assert enforce_hook_framing(track, [], CLIP)[1] == 0  # nothing to look at: left as it was


# --- text cards -------------------------------------------------------------------------------


def test_text_cards_are_short_and_a_small_share_of_the_video() -> None:
    ok = text_card_stats([("thao tác", 9000), ("chữ", 2500), ("thao tác", 9000)])
    assert ok["count"] == 1 and ok["longest_ms"] == 2500 and ok["ok"] is True
    long = text_card_stats([("thao tác", 20_000), ("chữ", 3500)])
    assert long["ok"] is False  # one card over 3 s
    many = text_card_stats([("thao tác", 10_000), ("chữ", 2000), ("chữ", 2000)])
    assert many["ratio"] > 0.15 and many["ok"] is False
    assert text_card_stats([("thao tác", 1000)])["count"] == 0


def test_a_hook_over_a_filled_form_shows_the_filled_fields_together() -> None:
    a = {**item("a", "input", "Nguyen", 480, 170, 300, 50), "filled": True}
    b = {**item("b", "input", "Van An", 480, 240, 300, 50), "filled": True}
    empty = {**item("c", "input", "Mã nhân viên", 480, 310, 300, 50), "filled": False}
    side = item("s", "list_item", "PIM", 10, 100, 200, 40, region="nav")
    inventory = [snap(0, side, a, b, empty)]
    wide = {"t_ms": 0, "bbox": {"x": 0, "y": 0, "w": 1440, "h": 900}, "framing": "establish",
            "hold_ms": 2000, "source": "rule", "item_id": None, "text": ""}  # fmt: skip
    fixed, n = enforce_hook_framing([wide], inventory, CLIP)
    assert n == 1 and fixed[0]["framing"] == "medium" and fixed[0]["reason"] == "hook: form đã điền"
    box = fixed[0]["bbox"]
    assert box["y"] <= 170 and box["y"] + box["h"] >= 290  # both filled fields, not the sidebar
    assert box["y"] + box["h"] < 310  # and not the empty one under them


def test_the_hero_frame_prefers_the_form_that_was_filled_in() -> None:
    from app.core.hero import score_snapshot

    empty = {
        "t_ms": 0,
        "items": [{"kind": "input", "text": "First", "is_new": False, "filled": False}],
    }
    filled = {
        "t_ms": 0,
        "items": [{"kind": "input", "text": "Nguyen", "is_new": False, "filled": True}],
    }
    assert score_snapshot(filled, 0.5) > score_snapshot(empty, 0.5)
