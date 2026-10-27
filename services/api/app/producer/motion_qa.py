"""Motion QA: how the camera of the finished video MOVES, measured from its pixels.

Between every two consecutive frames of the media window the frame difference tells a cut from
camera motion; for motion an affine fit (ORB features + RANSAC) gives the zoom (scale) and the pan
(shift of the window's centre). From those series: zoom and pan speed, a freeze followed by a
jump, flashes (shots under 0.8 s), and the longest absolutely still stretch.

The decisions are pure functions of the per-frame numbers; OpenCV only reads the pixels.
"""

import json
import math
import os
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

FPS = 30
# the 4:5 media window of the desktop_focus template inside the 1080x1920 canvas (see layout.ts)
MEDIA_BOX = (40, 365, 1000, 1250)  # left, top, width, height
CAPTION_STRIP = 340  # the dark strip with the captions along the window's bottom edge
ANALYSIS_WIDTH = 400  # frames are reduced to this width for the fit
DIFF_SIZE = (100, 125)

CUT_DIFF = 22.0  # mean abs difference (0-255) above which two frames are different shots
STATIC_DIFF = 0.07  # below this two frames are the same picture (the noise floor is 0-0.05)
MIN_FEATURES = 14  # matched features needed to trust a fit
CUT_INLIERS = 0.45  # share of matches that must agree with the fit to call a big change motion

MAX_ZOOM_RATE = 0.025  # per frame, as a share
MAX_PAN_RATE = 0.015  # per frame, as a share of the window's width
FREEZE_MS = 400  # a still stretch this long, then a jump = freeze_then_jump
MIN_SHOT_MS = 800
MAX_STATIC_MS = 400
INTRO_MS = 600  # the media window fades in over its first half second: not camera work
MIN_FOCUS_MATCH = 0.85


@dataclass(frozen=True)
class FrameMotion:
    t_ms: int
    diff: float  # mean abs difference to the previous frame
    scale: float  # zoom between the two frames (1 = none)
    pan: float  # shift of the window centre, as a share of the width
    cut: bool  # a different shot (not camera motion)
    known: bool  # the fit worked (False: too flat to tell, treated as no motion)

    @property
    def zoom_rate(self) -> float:
        return abs(self.scale - 1.0) if self.known and not self.cut else 0.0

    @property
    def pan_rate(self) -> float:
        return self.pan if self.known and not self.cut else 0.0

    @property
    def static(self) -> bool:
        return self.diff < STATIC_DIFF


def fit_motion(
    prev: np.ndarray, cur: np.ndarray, mask: np.ndarray | None
) -> tuple[float, float, float] | None:
    """(scale, pan share, inlier share) from `prev` to `cur`; None when no fit can be trusted."""
    orb = cv2.ORB_create(nfeatures=700, fastThreshold=12)
    kp1, d1 = orb.detectAndCompute(prev, mask)
    kp2, d2 = orb.detectAndCompute(cur, mask)
    if d1 is None or d2 is None or len(kp1) < MIN_FEATURES or len(kp2) < MIN_FEATURES:
        return None
    matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d1, d2)
    if len(matches) < MIN_FEATURES:
        return None
    a = np.float32([kp1[m.queryIdx].pt for m in matches])
    b = np.float32([kp2[m.trainIdx].pt for m in matches])
    matrix, inliers = cv2.estimateAffinePartial2D(
        a, b, method=cv2.RANSAC, ransacReprojThreshold=2.5
    )
    if matrix is None or inliers is None or int(inliers.sum()) < MIN_FEATURES * 0.6:
        return None
    scale = float(math.hypot(matrix[0, 0], matrix[1, 0]))
    h, w = prev.shape[:2]
    centre = np.array([w / 2, h / 2, 1.0])
    moved = matrix @ centre
    pan = float(math.hypot(moved[0] - w / 2, moved[1] - h / 2) / w)
    return scale, pan, float(inliers.mean())


def analyze_frames(frames: Iterable[np.ndarray], fps: int = FPS) -> list[FrameMotion]:
    """Motion of every frame against the one before it (the first frame has none)."""
    out: list[FrameMotion] = []
    prev: np.ndarray | None = None
    prev_small: np.ndarray | None = None
    mask: np.ndarray | None = None
    for n, frame in enumerate(frames):
        small = cv2.resize(frame, DIFF_SIZE, interpolation=cv2.INTER_AREA)
        if prev is not None and prev_small is not None:
            diff = float(np.mean(np.abs(small.astype(np.int16) - prev_small.astype(np.int16))))
            fit = (1.0, 0.0, 1.0) if diff < STATIC_DIFF else fit_motion(prev, frame, mask)
            # a big change that no zoom + shift explains is a cut; one that does is camera work
            cut = diff > CUT_DIFF and (fit is None or fit[2] < CUT_INLIERS)
            out.append(
                FrameMotion(
                    round(n * 1000 / fps), diff, fit[0] if fit else 1.0, fit[1] if fit else 0.0,
                    cut, fit is not None,
                )
            )  # fmt: skip
        if mask is None:
            mask = np.zeros(frame.shape[:2], np.uint8)
            mask[int(frame.shape[0] * 0.04) : int(frame.shape[0] * 0.72), :] = (
                255  # above the captions
            )
        prev, prev_small = frame, small
    return out


def runs(flags: Sequence[bool]) -> list[tuple[int, int]]:
    """(first, last) index of every run of True."""
    found: list[tuple[int, int]] = []
    start: int | None = None
    for i, f in enumerate(flags):
        if f and start is None:
            start = i
        elif not f and start is not None:
            found.append((start, i - 1))
            start = None
    if start is not None:
        found.append((start, len(flags) - 1))
    return found


def motion_metrics(
    motions: list[FrameMotion], fps: int = FPS, intro_ms: int = INTRO_MS
) -> dict[str, Any]:
    """The numbers the scorecard judges (rates are shares: 0.025 = 2.5 % per frame)."""
    frame_ms = 1000 / fps
    motions = [m for m in motions if m.t_ms >= intro_ms]
    zoom = max((m.zoom_rate for m in motions), default=0.0)
    pan = max((m.pan_rate for m in motions), default=0.0)

    still = runs([m.static for m in motions])
    freeze_jumps = 0
    longest_static = 0.0
    for a, b in still:
        length = (b - a + 1) * frame_ms
        if b < len(motions) - 1:  # (the still end card is not a defect)
            longest_static = max(longest_static, length)
            after = motions[b + 1]
            fast = after.zoom_rate > MAX_ZOOM_RATE or after.pan_rate > MAX_PAN_RATE
            if length >= FREEZE_MS and fast and not after.cut:
                freeze_jumps += 1

    cuts = [i for i, m in enumerate(motions) if m.cut]
    flashes = 0
    for a, b in zip(cuts, cuts[1:], strict=False):
        if (b - a) * frame_ms < MIN_SHOT_MS:
            flashes += 1
    return {
        "frames": len(motions),
        "max_zoom_rate": round(zoom, 4),
        "max_pan_rate": round(pan, 4),
        "freeze_then_jump": freeze_jumps,
        "flash_shots": flashes,
        "static_ms_max": round(longest_static),
        "cuts": [motions[i].t_ms for i in cuts],
        "unfitted_frames": sum(1 for m in motions if not m.known and not m.cut),
    }


def verdict(metrics: dict[str, Any]) -> dict[str, bool]:
    """pass / fail per measured number."""
    return {
        "max_zoom_rate": metrics["max_zoom_rate"] <= MAX_ZOOM_RATE,
        "max_pan_rate": metrics["max_pan_rate"] <= MAX_PAN_RATE,
        "freeze_then_jump": metrics["freeze_then_jump"] == 0,
        "flash_shots": metrics["flash_shots"] == 0,
        "static_ms_max": metrics["static_ms_max"] <= MAX_STATIC_MS,
    }


def read_media_frames(
    video: Path, box: tuple[int, int, int, int] = MEDIA_BOX
) -> Iterable[np.ndarray]:
    """Grey frames of the media window, reduced to ANALYSIS_WIDTH."""
    left, top, w, h = box
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video}")
    scale = ANALYSIS_WIDTH / w
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            grey = cv2.cvtColor(frame[top : top + h, left : left + w], cv2.COLOR_BGR2GRAY)
            yield cv2.resize(grey, (ANALYSIS_WIDTH, round(h * scale)), interpolation=cv2.INTER_AREA)
    finally:
        cap.release()


def video_motion(video: Path) -> list[FrameMotion]:
    cap = cv2.VideoCapture(str(video))
    fps = int(round(cap.get(cv2.CAP_PROP_FPS))) or FPS
    cap.release()
    return analyze_frames(read_media_frames(video), fps)


def series(motions: list[FrameMotion]) -> list[dict[str, Any]]:
    return [asdict(m) for m in motions]


# --- what the viewer should be looking at (from the produce files, no pixels) ------------------


def focus_match(props: dict[str, Any], produce_dir: Path, fps: int = FPS) -> dict[str, Any]:
    """Share of the focus time (establishing shots left out) in which the focus is something the
    voice-over names, something being operated, or the result that just appeared."""
    from app.core.textmatch import text_matches

    total = matched = 0.0
    per_scene: dict[str, float | None] = {}
    for scene in props["script"]["scenes"]:
        a = props["assets"].get(scene["id"], {})
        track = a.get("focus_track") or []
        inv_file = produce_dir / "inventory" / f"{scene['id']}.json"
        if not track or not inv_file.is_file():
            continue
        data = json.loads(inv_file.read_text(encoding="utf-8"))
        snaps, actions = data["inventory"], data.get("action_log", [])
        lead = a.get("start_offset_ms", 0) + a.get("trim_start_ms", 0)
        rate = a.get("playback_rate", 1.0) or 1.0
        phrases = [
            (c["start_ms"] * rate + lead, c["end_ms"] * rate + lead, c["text"])
            for c in a.get("captions", [])
        ]
        end = a.get("clip_duration_ms", track[-1]["t_ms"] + track[-1].get("hold_ms", 0))
        scene_total = scene_match = 0.0
        for i, e in enumerate(track):
            if e["framing"] == "establish":
                continue
            stop = track[i + 1]["t_ms"] if i + 1 < len(track) else end
            length = max(0.0, stop - e["t_ms"])
            if length <= 0:
                continue
            speech = " ".join(t for f, to, t in phrases if f < stop and to > e["t_ms"])
            snap = max(
                (x for x in snaps if x["t_ms"] <= (e["t_ms"] + stop) / 2),
                key=lambda x: x["t_ms"],
                default=None,
            )
            item = next(
                (x for x in (snap or {}).get("items", []) if x["id"] == e.get("item_id")), None
            )
            operated = any(
                x.get("item_id") == e.get("item_id")
                and x["t_ms"] - 400 <= stop
                and x["end_ms"] + 1500 >= e["t_ms"]
                for x in actions
            )
            ok = (
                bool(e.get("text") and speech and text_matches(e["text"], speech))
                or operated
                or bool(item and item.get("is_new"))
            )
            scene_total += length
            scene_match += length if ok else 0.0
        if scene_total:
            per_scene[scene["id"]] = round(scene_match / scene_total, 3)
            total += scene_total
            matched += scene_match
    return {
        "focus_match_rate": round(matched / total, 3) if total else None,
        "per_scene": per_scene,
    }


def focus_clipped(props_file: Path) -> dict[str, Any]:
    """Frames in which the focus's own text is cut by the view's edge (apps/render/scripts)."""
    script = (
        Path(__file__).resolve().parents[4] / "apps" / "render" / "scripts" / "focus-metrics.ts"
    )
    proc = subprocess.run(
        ["pnpm", "exec", "tsx", str(script), str(props_file.resolve())],
        cwd=script.parents[1], capture_output=True, text=True, shell=os.name == "nt",
    )  # fmt: skip
    if proc.returncode != 0:
        raise RuntimeError(f"focus-metrics failed: {proc.stderr[-300:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def loading_report(props: dict[str, Any], produce_dir: Path) -> dict[str, Any]:
    """Time in which a big image / canvas is still a flat grey or black slab, per scene clip."""
    from app.producer.dead_frames import LOADING_MIN_MS, media_loading_runs

    per_scene: dict[str, int] = {}
    for scene in props["script"]["scenes"]:
        a = props["assets"].get(scene["id"], {})
        clip = a.get("clip_url")
        inv_file = produce_dir / "inventory" / f"{scene['id']}.json"
        if not clip or not Path(clip).is_file() or not inv_file.is_file():
            continue
        lead = a.get("start_offset_ms", 0) + a.get("trim_start_ms", 0)
        inventory = json.loads(inv_file.read_text(encoding="utf-8"))["inventory"]
        runs_ = media_loading_runs(
            Path(clip), inventory, from_ms=lead,
            min_ms=LOADING_MIN_MS,
            clip_size=(a.get("clip_width", 1440), a.get("clip_height", 900)),
        )  # fmt: skip
        per_scene[scene["id"]] = sum(b - a_ for a_, b in runs_)
    return {"loading_frames_ms": sum(per_scene.values()), "per_scene": per_scene}


def run_qa(job_dir: Path, *, with_focus_clipped: bool = True) -> dict[str, Any]:
    """Every Motion QA number of a finished job, with the verdict per number."""
    produce = job_dir / "produce"
    props_file = produce / "render_props.json"
    props = json.loads(props_file.read_text(encoding="utf-8"))
    motions = video_motion(job_dir / "video.mp4")
    metrics = motion_metrics(motions)
    metrics.update(loading_report(props, produce))
    match = focus_match(props, produce)
    metrics["focus_match_rate"] = match["focus_match_rate"]
    metrics["focus_match_per_scene"] = match["per_scene"]
    if with_focus_clipped:
        clipped = focus_clipped(props_file)
        metrics["focus_text_clipped"] = clipped["frames_text_clipped"]
        metrics["image_zoom_inside"] = clipped["image_zoom_inside"]
    ok = verdict(metrics)
    ok["loading_frames_ms"] = metrics["loading_frames_ms"] == 0
    if metrics["focus_match_rate"] is not None:
        ok["focus_match_rate"] = metrics["focus_match_rate"] >= MIN_FOCUS_MATCH
    if "focus_text_clipped" in metrics:
        ok["focus_text_clipped"] = metrics["focus_text_clipped"] == 0
    return {"metrics": metrics, "verdict": ok, "passed": all(ok.values())}
