"""Cutting dead time out of a clip: pure planning, time shifting, and a real ffmpeg cut."""

import json
import subprocess
from pathlib import Path

import pytest

from app.producer.trim import (
    KEEP_MS,
    Cut,
    apply_cuts,
    cuttable,
    detect_freezes,
    plan_cuts,
    protected_windows,
    shift_logs,
    shift_time,
    subtract,
    trim_dead_time,
)


def test_subtract_leaves_the_pieces_outside_the_windows() -> None:
    assert subtract((0, 10_000), [(2_000, 3_000), (6_000, 7_500)]) == [
        (0, 2_000),
        (3_000, 6_000),
        (7_500, 10_000),
    ]
    assert subtract((1_000, 2_000), [(0, 5_000)]) == []
    assert subtract((1_000, 2_000), [(3_000, 4_000)]) == [(1_000, 2_000)]


def test_protected_windows_cover_the_first_second_and_every_event_with_its_hold() -> None:
    focus = [{"t_ms": 5_000, "hold_ms": 1_500, "kind": "click", "bbox": {}}]
    clicks = [{"t_ms": 5_000, "x": 1, "y": 1, "type": "click"}]
    windows = protected_windows(focus, clicks, start_ms=2_000)
    assert (2_000, 3_000) in windows  # the establishing shot after the loading phase
    assert any(a <= 5_000 and b >= 6_500 for a, b in windows)  # the click plus its hold
    assert any(a < 5_000 for a, _ in windows)  # the cursor is already on its way


def test_only_long_quiet_pieces_outside_the_protected_windows_are_cuttable() -> None:
    freezes = [(0.0, 900.0), (3_000.0, 8_000.0), (9_000.0, 9_500.0)]
    protected = [(0.0, 1_000.0), (5_000.0, 6_500.0)]
    assert cuttable(freezes, protected, 0, 10_000) == [(3_000.0, 5_000.0), (6_500.0, 8_000.0)]
    assert cuttable(freezes, protected, 4_000, 7_000) == [(4_000.0, 5_000.0)]


def test_cuts_leave_400_ms_of_every_stretch_and_stop_once_the_excess_is_gone() -> None:
    pieces = [(3_000.0, 5_000.0), (6_500.0, 8_000.0)]
    cuts = plan_cuts(pieces, excess_ms=10_000)  # more than can be cut: take all it can
    assert cuts == [Cut(3_400, 5_000), Cut(6_900, 8_000)]
    assert sum(c.length for c in cuts) == (2_000 - KEEP_MS) + (1_500 - KEEP_MS)
    partial = plan_cuts(pieces, excess_ms=700)  # the longest stretch first, only as much as needed
    assert partial == [Cut(4_300, 5_000)]
    assert plan_cuts(pieces, 0) == []


def test_times_after_two_cuts_are_shifted_by_what_was_removed_before_them() -> None:
    cuts = [Cut(0, 2_000), Cut(5_000, 6_500)]  # the loading phase, and one dead stretch
    assert shift_time(2_000, cuts) == 0
    assert shift_time(4_000, cuts) == 2_000
    assert shift_time(5_000, cuts) == 3_000  # at the start of a cut
    assert shift_time(6_000, cuts) == 3_000  # inside it: its start
    assert shift_time(6_500, cuts) == 3_000
    assert shift_time(9_000, cuts) == 5_500
    logs = [{"t_ms": 4_000, "x": 1}, {"t_ms": 7_000, "x": 2}, {"t_ms": 9_000, "x": 3}]
    assert shift_logs(logs, cuts) == [
        {"t_ms": 2_000, "x": 1},
        {"t_ms": 3_500, "x": 2},
        {"t_ms": 5_500, "x": 3},
    ]
    assert logs[0]["t_ms"] == 4_000  # the input is not modified


# --- a real clip: 2 s still, 1 s of motion, 3 s still ---------------------------------------------


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    out = tmp_path / "s2.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=0x2255aa:s=320x240:r=30:d=2",
         "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=1",
         "-f", "lavfi", "-i", "color=c=0x22aa55:s=320x240:r=30:d=3",
         "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0,format=yuv420p",
         "-c:v", "libx264", "-r", "30", str(out)],
        check=True, capture_output=True,
    )  # fmt: skip
    return out


def duration_ms(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return float(json.loads(out.stdout)["format"]["duration"]) * 1000


def test_freezedetect_finds_the_two_still_stretches(clip: Path) -> None:
    found = detect_freezes(clip, 6_000)
    assert len(found) == 2
    (a0, a1), (b0, b1) = found
    assert a0 < 100 and 1_800 < a1 < 2_300
    assert 2_800 < b0 < 3_300 and b1 > 5_800


def test_apply_cuts_removes_exactly_those_stretches_with_a_re_encode(
    clip: Path, tmp_path: Path
) -> None:
    out = tmp_path / "cut.mp4"
    apply_cuts(clip, out, [Cut(500, 1_500), Cut(4_000, 5_000)])
    assert duration_ms(out) == pytest.approx(4_000, abs=80)
    info = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name,pix_fmt,r_frame_rate", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert info.stdout.strip() == "h264,yuv420p,30/1"


def test_trim_dead_time_shortens_toward_the_speech_keeps_the_raw_clip_and_shifts_the_logs(
    clip: Path,
) -> None:
    focus = [
        {"t_ms": 2_500, "bbox": {"x": 0, "y": 0, "w": 10, "h": 10}, "kind": "click", "hold_ms": 500}
    ]
    clicks = [{"t_ms": 2_500, "x": 5, "y": 5, "type": "click"}]
    result = trim_dead_time(
        clip, scene_id="s2", lead_ms=500, content_ms=6_000, speech_ms=3_500,
        focus_log=focus, click_log=clicks, activity_ms=[2_500.0],
    )  # fmt: skip
    assert result is not None
    raw = clip.with_name("s2_raw.mp4")
    assert result.raw == raw and raw.is_file() and result.clip == clip
    assert duration_ms(raw) == pytest.approx(6_000, abs=80)  # the original is untouched
    # 5.5 s were shown; the speech needs 3.5 s: 2 s of dead time went, the loading phase too
    assert result.trimmed_ms >= 1_800
    assert result.duration_ms == pytest.approx(duration_ms(clip), abs=80)
    assert result.duration_ms == pytest.approx(3_500, abs=300)
    assert result.cuts[0] == Cut(0, 500)
    # the click is still on its moment in the new clip: its time moved by what was cut before it
    moved = result.click_log[0]["t_ms"]
    assert moved == round(2_500 - sum(c.length for c in result.cuts if c.to_ms <= 2_500))
    assert result.focus_log[0]["t_ms"] == moved and result.focus_log[0]["hold_ms"] == 500
    assert result.activity_ms == [moved]


def test_nothing_is_cut_when_the_clip_is_not_longer_than_the_speech(clip: Path) -> None:
    result = trim_dead_time(
        clip, scene_id="s2", lead_ms=0, content_ms=6_000, speech_ms=7_000,
        focus_log=[], click_log=[], activity_ms=[],
    )  # fmt: skip
    assert result is None and not clip.with_name("s2_raw.mp4").exists()
