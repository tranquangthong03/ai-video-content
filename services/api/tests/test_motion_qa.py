"""Motion QA on synthetic frames: each number must see exactly the defect it is named after."""

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.producer.motion_qa import (
    FrameMotion,
    analyze_frames,
    focus_match,
    motion_metrics,
    runs,
    verdict,
)
from app.producer.scorecard import build_scorecard, motion_lines

W, H = 400, 500


def texture(seed: int = 1) -> np.ndarray:
    """A feature-rich grey picture (blobs and lines), the stand-in for a page."""
    rng = np.random.default_rng(seed)
    img = np.full((H * 2, W * 2), 200, np.uint8)
    for _ in range(260):
        x, y = int(rng.integers(0, W * 2)), int(rng.integers(0, H * 2))
        r = int(rng.integers(4, 22))
        cv2.circle(img, (x, y), r, int(rng.integers(0, 160)), -1 if rng.random() < 0.5 else 2)
    for _ in range(70):
        a = (int(rng.integers(0, W * 2)), int(rng.integers(0, H * 2)))
        b = (int(rng.integers(0, W * 2)), int(rng.integers(0, H * 2)))
        cv2.line(img, a, b, int(rng.integers(0, 120)), 2)
    return img


def view(base: np.ndarray, zoom: float, dx: float = 0.0) -> np.ndarray:
    """The window of `base` at `zoom` (1 = whole 400x500 centre), shifted by dx pixels."""
    w, h = W / zoom, H / zoom
    x0 = (base.shape[1] - w) / 2 + dx
    y0 = (base.shape[0] - h) / 2
    m = np.float32([[W / w, 0, -x0 * W / w], [0, H / h, -y0 * H / h]])
    return cv2.warpAffine(base, m, (W, H), flags=cv2.INTER_LINEAR)


def zoom_path(
    base: np.ndarray, zooms: list[float], dxs: list[float] | None = None
) -> list[np.ndarray]:
    return [view(base, z, (dxs or [0.0] * len(zooms))[i]) for i, z in enumerate(zooms)]


def still(frame: np.ndarray, n: int) -> list[np.ndarray]:
    return [frame.copy() for _ in range(n)]


def metrics_of(frames: list[np.ndarray]) -> dict[str, Any]:
    return motion_metrics(analyze_frames(frames), intro_ms=0)


BASE = texture()


def test_a_gentle_zoom_is_under_the_limit_and_a_snap_zoom_is_not() -> None:
    gentle = metrics_of(zoom_path(BASE, [1.0 + 0.01 * i for i in range(20)]))  # 1 % per frame
    assert 0.005 < gentle["max_zoom_rate"] < 0.02
    assert verdict(gentle)["max_zoom_rate"] is True
    snap = metrics_of(zoom_path(BASE, [1.0, 1.0, 1.13, 1.28, 1.4, 1.4]))  # ~13 % per frame
    assert snap["max_zoom_rate"] > 0.1 and verdict(snap)["max_zoom_rate"] is False


def test_a_fast_pan_is_measured_as_a_share_of_the_window_width() -> None:
    slow = metrics_of(zoom_path(BASE, [1.2] * 12, [i * 2.0 for i in range(12)]))  # 0.5 % of 400 px
    fast = metrics_of(zoom_path(BASE, [1.2] * 12, [i * 20.0 for i in range(12)]))  # 5 %
    assert slow["max_pan_rate"] < 0.015 and verdict(slow)["max_pan_rate"] is True
    assert fast["max_pan_rate"] > 0.03 and verdict(fast)["max_pan_rate"] is False


def test_standing_still_and_then_jumping_is_found() -> None:
    frames = [*still(view(BASE, 1.0), 20), *zoom_path(BASE, [1.0, 1.1, 1.2, 1.3, 1.4])]
    m = metrics_of(frames)
    assert m["freeze_then_jump"] == 1 and m["static_ms_max"] >= 600
    smooth = metrics_of(zoom_path(BASE, [1.0 + 0.01 * i for i in range(40)]))
    assert smooth["freeze_then_jump"] == 0 and smooth["static_ms_max"] == 0


def test_the_longest_absolutely_still_stretch_counts_but_not_the_end_card() -> None:
    mid = metrics_of(
        [
            *zoom_path(BASE, [1.0, 1.01, 1.02]),
            *still(view(BASE, 1.02), 24),
            *zoom_path(BASE, [1.03, 1.04]),
        ]
    )
    assert 700 <= mid["static_ms_max"] <= 900
    end = metrics_of([*zoom_path(BASE, [1.0, 1.01, 1.02]), *still(view(BASE, 1.02), 60)])
    assert end["static_ms_max"] == 0  # the closing frame holds still on purpose


def test_a_hard_cut_is_not_camera_motion_and_a_blink_between_two_cuts_is_a_flash() -> None:
    other = texture(7)
    a, b = view(BASE, 1.0), view(other, 1.0)
    flash = metrics_of([*still(a, 10), *still(b, 3), *still(a, 10)])  # 0.1 s of another picture
    assert len(flash["cuts"]) == 2 and flash["flash_shots"] == 1
    assert flash["max_zoom_rate"] == 0.0  # the cut itself is not a zoom
    calm = metrics_of([*still(a, 10), *still(b, 30)])
    assert len(calm["cuts"]) == 1 and calm["flash_shots"] == 0


def test_runs_finds_the_stretches_of_true() -> None:
    assert runs([False, True, True, False, True]) == [(1, 2), (4, 4)]
    assert runs([]) == []


def test_the_scorecard_shows_each_motion_number_and_na_when_it_could_not_be_measured() -> None:
    qa = {"metrics": {"max_zoom_rate": 0.169, "freeze_then_jump": 0, "focus_match_rate": 0.9},
          "verdict": {"max_zoom_rate": False, "freeze_then_jump": True, "focus_match_rate": True}}  # fmt: skip
    got = {x["id"]: x for x in motion_lines(qa)}
    assert (
        got["motion_max_zoom_rate"]["status"] == "fail"
        and got["motion_max_zoom_rate"]["value"] == "16.9%/khung"
    )
    assert got["motion_freeze_then_jump"]["status"] == "pass"
    assert got["motion_focus_match_rate"]["value"] == "90%"
    assert got["motion_static_ms_max"]["status"] == "na"
    assert all(x["status"] == "na" for x in motion_lines(None))
    card = build_scorecard(
        {"footage_ratio": 0.8}, hook_text=None, hook_close=None, said="", motion=qa
    )
    assert card["failed"] == 1 and any(x["id"] == "motion_max_zoom_rate" for x in card["lines"])


def test_a_focus_that_neither_is_said_nor_operated_nor_new_does_not_count(tmp_path: Path) -> None:
    props = {
        "script": {"scenes": [{"id": "s1"}]},
        "assets": {"s1": {
            "start_offset_ms": 0, "trim_start_ms": 0, "playback_rate": 1.0, "clip_duration_ms": 6000,
            "captions": [{"start_ms": 0, "end_ms": 3000, "text": "Bấm nút Add để thêm nhân viên"}],
            "focus_track": [
                {"t_ms": 0, "framing": "establish", "text": "", "item_id": None},
                {"t_ms": 1000, "framing": "tight", "text": "Add", "item_id": "add"},
                {"t_ms": 3000, "framing": "tight", "text": "Reset", "item_id": "reset"},
            ],
        }},
    }  # fmt: skip
    inv = {"inventory": [{"t_ms": 0, "items": [
        {"id": "add", "text": "Add", "is_new": False}, {"id": "reset", "text": "Reset", "is_new": False},
    ]}], "action_log": []}  # fmt: skip
    (tmp_path / "inventory").mkdir()
    (tmp_path / "inventory" / "s1.json").write_text(__import__("json").dumps(inv), encoding="utf-8")
    got = focus_match(props, tmp_path)
    assert (
        got["focus_match_rate"] == 0.4
    )  # 2 s of «Add» (said) against 3 s of «Reset» (nobody mentions it)... of 5 s
    inv["action_log"] = [{"t_ms": 3200, "end_ms": 3600, "item_id": "reset", "do": "click"}]
    (tmp_path / "inventory" / "s1.json").write_text(__import__("json").dumps(inv), encoding="utf-8")
    assert focus_match(props, tmp_path)["focus_match_rate"] == 1.0  # now it is being clicked


def test_a_frame_motion_ignores_a_fit_it_does_not_trust() -> None:
    unknown = FrameMotion(1000, 5.0, 3.0, 0.5, False, False)
    assert unknown.zoom_rate == 0.0 and unknown.pan_rate == 0.0
    cut = FrameMotion(1000, 50.0, 3.0, 0.5, True, True)
    assert cut.zoom_rate == 0.0


def test_a_jump_the_planned_camera_does_not_explain_is_the_page_not_the_camera() -> None:
    frames = [*zoom_path(BASE, [1.0] * 10), *zoom_path(BASE, [1.0, 1.0, 1.0])]
    shifted = zoom_path(BASE, [1.2] * 6, [i * 40.0 for i in range(6)])  # the content slides at once
    motions = analyze_frames([*frames[:10], *shifted])
    camera = [(0.0, 0.0)] * len(motions)  # the plan says: the camera holds still
    plain = motion_metrics(motions, intro_ms=0)
    split = motion_metrics(motions, intro_ms=0, camera=camera)
    assert (
        plain["max_pan_rate"] > 0.03 or plain["max_zoom_rate"] > 0.03
    )  # as a camera it would fail
    assert split["max_pan_rate"] <= 0.015 and split["max_zoom_rate"] <= 0.025
    assert split["page_changes_ms"]  # but it is reported
    # when the camera DID plan that motion, it still counts against the camera
    moving = [(1.0, 1.0)] * (len(motions) + 2)
    assert motion_metrics(motions, intro_ms=0, camera=moving)["page_changes_ms"] == []  # fmt: skip


def test_camera_rates_come_from_the_planned_views() -> None:
    from app.producer.motion_qa import camera_rates

    path = {
        "frame": {"w": 1000, "h": 1250},
        "scenes": [{"from": 2, "frames": 3, "views": [[0, 0, 800], [0, 0, 760], [40, 0, 760]]}],
    }
    rates = camera_rates(path)
    assert len(rates) == 5 and rates[0] == (0.0, 0.0) and rates[2] == (0.0, 0.0)
    assert abs(rates[3][0] - (800 / 760 - 1)) < 1e-9 and rates[3][1] > 0
    assert rates[4][0] == 0.0 and rates[4][1] > 0.04  # a 40 px shift of a 760 px view
