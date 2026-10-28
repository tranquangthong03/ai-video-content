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
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import cv2
import numpy as np

FPS = 30
# the media window of each template inside the 1080x1920 canvas (layout.ts of the template)
MEDIA_BOXES = {
    "desktop_focus": (
        40,
        365,
        1000,
        1250,
    ),  # left, top, width, height; 4:5, captions on its bottom edge
    "desktop_frame": (24, 474, 1032, 580),  # 16:9 (inside the 2 px border), captions are below it
}
MEDIA_BOX = MEDIA_BOXES["desktop_focus"]
# rows of the window the fit looks at (share of its height): above the captions of desktop_focus
FIT_ROWS = {"desktop_focus": (0.04, 0.72), "desktop_frame": (0.03, 0.97)}
CAPTION_STRIP = 340  # the dark strip with the captions along the window's bottom edge
ANALYSIS_WIDTH = 400  # frames are reduced to this width for the fit
DIFF_SIZE = (100, 125)

CUT_DIFF = 22.0  # mean abs difference (0-255) above which two frames are different shots
STATIC_DIFF = 0.03  # below this two frames are the same picture (a still page differs by 0-0.01)
MIN_FEATURES = 14  # matched features needed to trust a fit
CUT_INLIERS = 0.45  # share of matches that must agree with the fit to call a big change motion

MAX_ZOOM_RATE = 0.025  # per frame, as a share
MAX_PAN_RATE = 0.015  # per frame, as a share of the window's width
FREEZE_MS = 400  # a still stretch this long, then a jump = freeze_then_jump
MIN_SHOT_MS = 800
MAX_STATIC_MS = 400
INTRO_MS = 600  # the media window fades in over its first half second: not camera work
MIN_FOCUS_MATCH = 0.85
# a measured rate this far above what the planned camera does is the page moving, not the camera
EXPLAIN_ZOOM = 0.008
EXPLAIN_PAN = 0.006

# desktop_frame: the camera is still by design and zooms with a 0.5-0.7 s ease, so a zoom of 1.7x
# peaks at ~4.5 % of the width per frame; and a page that is just being held stays still for its
# whole hold because nothing drifts (the longest a page is held while one sentence is spoken).
# The speed and still-time limits are widened for it.
TEMPLATE_LIMITS = {
    "desktop_focus": {"zoom": MAX_ZOOM_RATE, "pan": MAX_PAN_RATE, "static_ms": MAX_STATIC_MS},
    "desktop_frame": {"zoom": 0.05, "pan": 0.035, "static_ms": 5000},
}
# the shot-camera numbers (all templates; the limits apply to desktop_frame, the others show them)
MAX_MOVING_RATIO = 0.25  # share of the frames in which the camera moves
MIN_FULL_RATIO = 0.50  # share of the frames on the full view
MAX_ZOOMS_PER_SCENE = 2
MOVE_EPS = (
    6e-4  # a view change below this share per frame is the camera standing still (drift is 3e-4)
)
GHOST_MIN_DIFF = 3.0  # both neighbours of a ghost differ from it by at least this (0-255)
GHOST_RATIO = 0.35  # and a blend of them is this much closer than either one
CROSSFADE_FRAMES = 10


@dataclass(frozen=True)
class FrameMotion:
    t_ms: int
    diff: float  # mean abs difference to the previous frame
    scale: float  # zoom between the two frames (1 = none)
    pan: float  # shift of the window centre, as a share of the width
    cut: bool  # a different shot (not camera motion)
    known: bool  # the fit worked (False: too flat to tell, treated as no motion)
    ghost: bool = False  # a blend of its two neighbours: two pictures on top of each other

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


def ghost_frames(smalls: Sequence[np.ndarray]) -> set[int]:
    """Indices of frames that look like a blend of the frame before and the one after.

    A crossfade shows two pictures on top of each other; a frame of it is, pixel by pixel, a
    weighted mean of its neighbours. Camera motion is not: the mean of two shifted pictures is not
    the picture in between. So a frame whose neighbours both differ from it clearly, yet a blend of
    the two matches it far better than either, is a ghost."""
    found: set[int] = set()
    for i in range(1, len(smalls) - 1):
        a, b, c = (x.astype(np.float32) for x in smalls[i - 1 : i + 2])
        d1 = float(np.mean(np.abs(b - a)))
        d2 = float(np.mean(np.abs(c - b)))
        if min(d1, d2) < GHOST_MIN_DIFF:
            continue
        best = min(float(np.mean(np.abs(b - ((1 - t) * a + t * c)))) for t in (0.25, 0.5, 0.75))
        if best < GHOST_RATIO * min(d1, d2):
            found.add(i)
    return found


def analyze_frames(
    frames: Iterable[np.ndarray],
    fps: int = FPS,
    rows: tuple[float, float] = FIT_ROWS["desktop_focus"],
) -> list[FrameMotion]:
    """Motion of every frame against the one before it (the first frame has none)."""
    out: list[FrameMotion] = []
    prev: np.ndarray | None = None
    prev_small: np.ndarray | None = None
    mask: np.ndarray | None = None
    smalls: list[np.ndarray] = []
    for n, frame in enumerate(frames):
        small = cv2.resize(frame, DIFF_SIZE, interpolation=cv2.INTER_AREA)
        smalls.append(small)
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
            mask[int(frame.shape[0] * rows[0]) : int(frame.shape[0] * rows[1]), :] = 255
        prev, prev_small = frame, small
    ghosts = ghost_frames(smalls)
    # out[k] is frame k + 1 (the first frame has no motion entry)
    return [replace(m, ghost=True) if (k + 1) in ghosts else m for k, m in enumerate(out)]


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


def page_changes(
    motions: list[FrameMotion], camera: list[tuple[float, float]] | None, fps: int = FPS
) -> set[int]:
    """Frames (t_ms) whose measured zoom or pan the planned camera does NOT explain: the page
    itself moved (a row was added, a field changed size). That is the page, not the camera, so
    it is reported on its own and not held against the camera's speed limits."""
    if not camera:
        return set()
    out: set[int] = set()
    for m in motions:
        n = round(m.t_ms * fps / 1000)
        cam_zoom, cam_pan = camera[n] if n < len(camera) else (0.0, 0.0)
        if m.zoom_rate - cam_zoom > EXPLAIN_ZOOM or m.pan_rate - cam_pan > EXPLAIN_PAN:
            out.add(m.t_ms)
    return out


def motion_metrics(
    motions: list[FrameMotion],
    fps: int = FPS,
    intro_ms: int = INTRO_MS,
    camera: list[tuple[float, float]] | None = None,
    template: str = "desktop_focus",
) -> dict[str, Any]:
    """The numbers the scorecard judges (rates are shares: 0.025 = 2.5 % per frame).
    `camera`: the planned camera's own (zoom, pan) per frame, to tell the page moving from the
    camera moving."""
    frame_ms = 1000 / fps
    lim = TEMPLATE_LIMITS.get(template, TEMPLATE_LIMITS["desktop_focus"])
    motions = [m for m in motions if m.t_ms >= intro_ms]
    changed = page_changes(motions, camera, fps)
    zoom = max((m.zoom_rate for m in motions if m.t_ms not in changed), default=0.0)
    pan = max((m.pan_rate for m in motions if m.t_ms not in changed), default=0.0)

    still = runs([m.static for m in motions])
    freeze_jumps = 0
    longest_static = 0.0
    for a, b in still:
        length = (b - a + 1) * frame_ms
        if b < len(motions) - 1:  # (the still end card is not a defect)
            longest_static = max(longest_static, length)
            after = motions[b + 1]
            fast = (after.zoom_rate > lim["zoom"] or after.pan_rate > lim["pan"]) and (
                after.t_ms not in changed
            )
            if length >= FREEZE_MS and fast and not after.cut:
                freeze_jumps += 1

    cuts = [i for i, m in enumerate(motions) if m.cut]
    flashes = 0
    for a, b in zip(cuts, cuts[1:], strict=False):
        if (b - a) * frame_ms < MIN_SHOT_MS:
            flashes += 1
    return {
        "frames": len(motions),
        "camera_plan_max_zoom_rate": round(max((z for z, _p in camera or []), default=0.0), 4),
        "camera_plan_max_pan_rate": round(max((p for _z, p in camera or []), default=0.0), 4),
        "max_zoom_rate": round(zoom, 4),
        "max_pan_rate": round(pan, 4),
        "freeze_then_jump": freeze_jumps,
        "flash_shots": flashes,
        "static_ms_max": round(longest_static),
        "cuts": [motions[i].t_ms for i in cuts],
        "page_changes_ms": sorted(changed),
        "unfitted_frames": sum(1 for m in motions if not m.known and not m.cut),
        "ghost_frames": sum(1 for m in motions if m.ghost and moving_at(camera, m.t_ms, fps)),
    }


def moving_at(camera: list[tuple[float, float]] | None, t_ms: int, fps: int = FPS) -> bool:
    """The planned camera moves around this frame (or there is no plan: then every blend counts)."""
    if camera is None:
        return True
    n = round(t_ms * fps / 1000)
    near = camera[max(0, n - 1) : n + 2]
    return any(z > MOVE_EPS or p > MOVE_EPS for z, p in near)


def shot_metrics(path: dict[str, Any]) -> dict[str, Any]:
    """How much of the time the camera moves / is on the full view, the zooms of every scene, and
    the crossfades laid over a moving camera - from the renderer's own camera path."""
    frames = moving = full = 0
    zooms: dict[str, int] = {}
    for scene in path["scenes"]:
        views = scene["views"]
        full_w = scene["full_w"]
        zoom_ins = 0
        zooming_in = False
        for i, (x, y, w) in enumerate(views):
            frames += 1
            if w >= full_w * 0.98:
                full += 1
            if i == 0:
                continue
            px, py, pw = views[i - 1]
            step = max(abs(math.log(pw / w)), math.hypot(x - px, y - py) / w)
            if step > MOVE_EPS:
                moving += 1
            closer = math.log(pw / w) > MOVE_EPS
            if closer and not zooming_in:
                zoom_ins += 1  # a new move towards a closer view
            zooming_in = closer or (zooming_in and abs(math.log(pw / w)) <= MOVE_EPS)
        zooms[scene["id"]] = zoom_ins
    blended = sum(
        1
        for b in path.get("boundaries", [])
        if b.get("crossfade") and b.get("moving_frames", 0) > 0
    )
    return {
        "camera_moving_ratio": round(moving / frames, 3) if frames else 0.0,
        "full_view_ratio": round(full / frames, 3) if frames else 1.0,
        "zoom_events_per_scene": max(zooms.values(), default=0),
        "zoom_events": sum(zooms.values()),
        "crossfade_during_motion": blended,
    }


def camera_path(props_file: Path) -> dict[str, Any]:
    """The renderer's own camera path (apps/render/scripts/camera-path.ts), frame by frame."""
    script = Path(__file__).resolve().parents[4] / "apps" / "render" / "scripts" / "camera-path.ts"
    proc = subprocess.run(
        ["pnpm", "exec", "tsx", str(script), str(props_file.resolve())],
        cwd=script.parents[1], capture_output=True, text=True, shell=os.name == "nt",
    )  # fmt: skip
    if proc.returncode != 0:
        raise RuntimeError(f"camera-path failed: {proc.stderr[-300:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])  # type: ignore[no-any-return]


def camera_rates(path: dict[str, Any]) -> list[tuple[float, float]]:
    """(zoom, pan) per video frame of the planned camera (0 where no clip is shown)."""
    ratio = path["frame"]["h"] / path["frame"]["w"]
    total = max((s["from"] + s["frames"] for s in path["scenes"]), default=0)
    out: list[tuple[float, float]] = [(0.0, 0.0)] * total
    for scene in path["scenes"]:
        prev = None
        for i, (x, y, w) in enumerate(scene["views"]):
            if prev is not None:
                px, py, pw = prev
                zoom = abs(pw / w - 1.0)
                dx = (x + w / 2) - (px + pw / 2)
                dy = (y + w * ratio / 2) - (py + pw * ratio / 2)
                out[scene["from"] + i] = (zoom, math.hypot(dx, dy) / w)
            prev = (x, y, w)
    return out


def verdict(metrics: dict[str, Any], template: str = "desktop_focus") -> dict[str, bool]:
    """pass / fail per measured number."""
    lim = TEMPLATE_LIMITS.get(template, TEMPLATE_LIMITS["desktop_focus"])
    ok = {
        "max_zoom_rate": metrics["max_zoom_rate"] <= lim["zoom"],
        "max_pan_rate": metrics["max_pan_rate"] <= lim["pan"],
        "freeze_then_jump": metrics["freeze_then_jump"] == 0,
        "flash_shots": metrics["flash_shots"] == 0,
        "static_ms_max": metrics["static_ms_max"] <= lim["static_ms"],
        "ghost_frames": metrics.get("ghost_frames", 0) == 0,
    }
    if (
        template == "desktop_frame"
    ):  # the limits of the shot camera (the other templates only show them)
        ok["camera_moving_ratio"] = metrics["camera_moving_ratio"] <= MAX_MOVING_RATIO
        ok["full_view_ratio"] = metrics["full_view_ratio"] >= MIN_FULL_RATIO
        ok["zoom_events_per_scene"] = metrics["zoom_events_per_scene"] <= MAX_ZOOMS_PER_SCENE
        ok["crossfade_during_motion"] = metrics["crossfade_during_motion"] == 0
        if "container_cut_frames" in metrics:
            ok["container_cut_frames"] = metrics["container_cut_frames"] == 0
    return ok


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


def video_motion(video: Path, template: str = "desktop_focus") -> list[FrameMotion]:
    cap = cv2.VideoCapture(str(video))
    fps = int(round(cap.get(cv2.CAP_PROP_FPS))) or FPS
    cap.release()
    box = MEDIA_BOXES.get(template, MEDIA_BOX)
    return analyze_frames(
        read_media_frames(video, box), fps, FIT_ROWS.get(template, FIT_ROWS["desktop_focus"])
    )


def series(motions: list[FrameMotion]) -> list[dict[str, Any]]:
    return [asdict(m) for m in motions]


# --- what the viewer should be looking at (from the produce files, no pixels) ------------------


def acts_on_focus(
    action: dict[str, Any], entry: dict[str, Any], snaps: list[dict[str, Any]]
) -> bool:
    """The focus entry is the thing the action worked on, or a row / card that contains it."""
    if action.get("item_id") == entry.get("item_id"):
        return True
    box = entry.get("bbox") or {}
    hit = next(
        (i for s in snaps for i in s.get("items", []) if i["id"] == action.get("item_id")), None
    )
    if not hit or not box:
        return False
    b = hit["bbox"]
    return (
        box["x"] - 2 <= b["x"]
        and box["y"] - 2 <= b["y"]
        and box["x"] + box["w"] + 2 >= b["x"] + b["w"]
        and box["y"] + box["h"] + 2 >= b["y"] + b["h"]
    )


def focus_match(props: dict[str, Any], produce_dir: Path, fps: int = FPS) -> dict[str, Any]:
    """Share of the focus time (establishing shots left out) in which the focus is something the
    voice-over names, something being operated, or the result that just appeared."""
    from app.core.textmatch import text_matches

    total = matched = 0.0
    per_scene: dict[str, float | None] = {}
    misses: list[dict[str, Any]] = []  # the stretches that do not match, for a check by eye
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
                acts_on_focus(x, e, snaps)
                and x["t_ms"] - 400 <= stop
                and x["end_ms"] + 1500 >= e["t_ms"]
                for x in actions
            )
            fresh = any(  # a result that showed up around the moment the focus went to it
                x.get("is_new") and x["id"] == e.get("item_id")
                for s in snaps
                if e["t_ms"] - 500 <= s["t_ms"] <= e["t_ms"] + 3000
                for x in s.get("items", [])
            )
            ok = (
                bool(e.get("text") and speech and text_matches(e["text"], speech))
                or operated
                or fresh
                or bool(item and item.get("is_new"))
                or str(e.get("reason", "")).startswith("hook:")  # the hero frame of the flow
            )
            scene_total += length
            scene_match += length if ok else 0.0
            if not ok:
                misses.append(
                    {
                        "scene": scene["id"], "from_ms": round(e["t_ms"]), "to_ms": round(stop),
                        "speech": speech[:80], "focus": (e.get("text") or "")[:50],
                        "kind": e.get("item_kind"), "source": e.get("source"),
                        "reason": (e.get("reason") or "")[:60],
                    }
                )  # fmt: skip
        if scene_total:
            per_scene[scene["id"]] = round(scene_match / scene_total, 3)
            total += scene_total
            matched += scene_match
    return {
        "focus_match_rate": round(matched / total, 3) if total else None,
        "per_scene": per_scene,
        "misses": misses,
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


def frame_blocks(props_file: Path) -> dict[str, Any]:
    """desktop_frame: frames in which the block of a zoom is cut (apps/render/scripts)."""
    script = (
        Path(__file__).resolve().parents[4] / "apps" / "render" / "scripts" / "frame-metrics.ts"
    )
    proc = subprocess.run(
        ["pnpm", "exec", "tsx", str(script), str(props_file.resolve())],
        cwd=script.parents[1], capture_output=True, text=True, shell=os.name == "nt",
    )  # fmt: skip
    if proc.returncode != 0:
        raise RuntimeError(f"frame-metrics failed: {proc.stderr[-300:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])  # type: ignore[no-any-return]


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
    template = props["script"].get("template", "desktop_frame")
    motions = video_motion(job_dir / "video.mp4", template)
    path: dict[str, Any] | None
    try:
        path = camera_path(props_file)
        camera: list[tuple[float, float]] | None = camera_rates(path)
    except RuntimeError:
        path, camera = None, None  # no node here: every frame counts against the camera
    metrics = motion_metrics(motions, camera=camera, template=template)
    metrics["template"] = template
    if path is not None:
        metrics.update(shot_metrics(path))
    metrics.update(loading_report(props, produce))
    match = focus_match(props, produce)
    metrics["focus_match_rate"] = match["focus_match_rate"]
    metrics["focus_match_per_scene"] = match["per_scene"]
    metrics["focus_unmatched"] = match["misses"]
    if with_focus_clipped and template == "desktop_frame":
        blocks = frame_blocks(props_file)
        metrics["container_cut_frames"] = blocks["container_cut_frames"]
        metrics["container_cut_spans"] = blocks["container_cut_spans"]
    elif with_focus_clipped:
        clipped = focus_clipped(props_file)
        metrics["focus_text_clipped"] = clipped["frames_text_clipped"]
        metrics["image_zoom_inside"] = clipped["image_zoom_inside"]
        metrics["focus_clipped_spans"] = clipped.get("clipped_spans", [])  # top 5
    ok = verdict(metrics, template)
    ok["loading_frames_ms"] = metrics["loading_frames_ms"] == 0
    if metrics["focus_match_rate"] is not None and template != "desktop_frame":
        # (desktop_frame zooms only where the planner found the voice-over talking about the block)
        ok["focus_match_rate"] = metrics["focus_match_rate"] >= MIN_FOCUS_MATCH
    if "focus_text_clipped" in metrics:
        ok["focus_text_clipped"] = metrics["focus_text_clipped"] == 0
    return {"metrics": metrics, "verdict": ok, "passed": all(ok.values())}
