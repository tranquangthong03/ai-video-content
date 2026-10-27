"""Dead frames: stretches of a clip with nothing to look at (blank page, spinner, skeleton).

Each frame is reduced to a small grey picture; a frame is dead when it carries almost no
information (flat colour: tiny spread of brightness AND almost no edges). A run of dead frames
longer than MIN_DEAD_MS is cut out like dead time; the final video must have none (dead_frames_ms).
The decisions are pure functions of the per-frame numbers; ffmpeg only supplies the pixels.
"""

import io
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageStat

SAMPLE_MS = 100  # one frame in ten is looked at
SIZE = (160, 100)
MIN_DEAD_MS = 300  # shorter blanks are a blink, not a dead stretch
DEAD_STD = 9.0  # brightness spread (0-255) below this = flat
DEAD_EDGES = 2.0  # mean edge response (0-255) below this = nothing drawn
MIN_KEEP_MS = 1000  # never cut a scene down to less than this


@dataclass(frozen=True)
class FrameStat:
    t_ms: int
    std: float
    edges: float

    @property
    def dead(self) -> bool:
        return self.std < DEAD_STD and self.edges < DEAD_EDGES


def stat_of(gray: Image.Image, t_ms: int) -> FrameStat:
    """Numbers for one grey frame: brightness spread and mean edge strength."""
    spread = float(ImageStat.Stat(gray).stddev[0])
    w, h = gray.size
    inner = gray.filter(ImageFilter.FIND_EDGES).crop(
        (2, 2, w - 2, h - 2)
    )  # the filter's border is noise
    edges = float(ImageStat.Stat(inner).mean[0])
    return FrameStat(t_ms, spread, edges)


def dead_runs(
    stats: list[FrameStat], step_ms: int = SAMPLE_MS, min_ms: int = MIN_DEAD_MS
) -> list[tuple[int, int]]:
    """(from_ms, to_ms) of every run of dead frames at least `min_ms` long."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for s in stats:
        if s.dead and start is None:
            start = s.t_ms
        elif not s.dead and start is not None:
            runs.append((start, s.t_ms))
            start = None
    if start is not None and stats:
        runs.append((start, stats[-1].t_ms + step_ms))
    return [(a, b) for a, b in runs if b - a >= min_ms]


def sample_clip(clip: Path, step_ms: int = SAMPLE_MS) -> list[FrameStat]:
    """Per-frame numbers of a clip (ffmpeg → small grey frames → stat_of)."""
    w, h = SIZE
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(clip), "-an",
         "-vf", f"fps={1000 / step_ms:g},scale={w}:{h},format=gray",
         "-f", "rawvideo", "-"],
        capture_output=True,
    )  # fmt: skip
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg sampling failed: {proc.stderr[:200]!r}")
    size = w * h
    frames = [proc.stdout[i : i + size] for i in range(0, len(proc.stdout) - size + 1, size)]
    return [
        stat_of(Image.frombuffer("L", SIZE, raw, "raw", "L", 0, 1), n * step_ms)
        for n, raw in enumerate(frames)
    ]


LOADING_MIN_MS = 100  # a flat grey slab where a picture should be is cut even when it only flashes
MIN_SHOT_MS = 800  # nothing that stays between two cuts is shorter than this
FADE_DIFF = (
    3.0  # frames either side of a cut that differ more than this (mean, 0-255) are dissolved
)
FADE_MS = 160  # about five frames


def merge_runs(runs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Sorted runs with the overlapping and touching ones joined."""
    out: list[tuple[int, int]] = []
    for a, b in sorted(runs):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def enforce_min_shot(
    runs: list[tuple[int, int]], from_ms: int, content_ms: int, min_ms: int = MIN_SHOT_MS
) -> list[tuple[int, int]]:
    """A stretch that would survive between two cuts (or between a cut and the clip's edge) for
    less than min_ms is cut too: a blink of picture between two blanks is a flash, not a shot."""
    runs = merge_runs(runs)
    edges = [from_ms, *[t for r in runs for t in r], content_ms]
    kept = list(zip(edges[::2], edges[1::2], strict=False))  # the pieces the runs leave
    extra = [(a, b) for a, b in kept if 0 < b - a < min_ms]
    return merge_runs([*runs, *extra])


def needs_fade(diff: float) -> bool:
    return diff > FADE_DIFF


def frame_at(clip: Path, t_ms: int) -> Image.Image:
    """One small grey frame of the clip."""
    w, h = SIZE
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{max(0, t_ms) / 1000:.3f}", "-i", str(clip), "-an",
         "-frames:v", "1", "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
        capture_output=True,
    )  # fmt: skip
    if proc.returncode != 0 or len(proc.stdout) < w * h:
        raise RuntimeError("ffmpeg frame failed")
    return Image.frombuffer("L", SIZE, proc.stdout[: w * h], "raw", "L", 0, 1)


def junction_diff(clip: Path, before_ms: int, after_ms: int) -> float:
    """How different the frame before a cut and the one after it are (mean abs, 0-255)."""
    a, b = frame_at(clip, before_ms), frame_at(clip, after_ms)
    return float(ImageStat.Stat(ImageChops.difference(a, b)).mean[0])


def cut_dead(
    clip: Path,
    scene_id: str,
    from_ms: int,
    content_ms: int,
    inventory: list[dict[str, Any]] | None = None,
    clip_size: tuple[int, int] = (1440, 900),
) -> tuple[Path, list[Any]] | None:
    """Cut the dead stretches (blank pages, spinners, a big picture still loading) at or after
    `from_ms` out of `clip`. A shot never ends up shorter than 0.8 s, and a junction where the
    picture changes a lot dissolves over five frames instead of jumping. The new clip replaces the
    old one (kept as <scene>_nodead_raw.mp4). None when nothing is dead, or cutting would leave less
    than a second. Returns (clip, the Cuts in the old clip's time)."""
    from app.producer.trim import Cut, apply_cuts

    runs = dead_runs([s for s in sample_clip(clip) if s.t_ms >= from_ms])
    if inventory:
        runs += media_loading_runs(
            clip, inventory, clip_size=clip_size, from_ms=from_ms, min_ms=LOADING_MIN_MS
        )
    runs = [(a, min(b, content_ms)) for a, b in merge_runs(runs)]
    runs = enforce_min_shot(runs, from_ms, content_ms)
    if not runs or content_ms - from_ms - sum(b - a for a, b in runs) < MIN_KEEP_MS:
        return None
    cuts = []
    for a, b in runs:
        fade = 0
        if a > from_ms and b < content_ms:  # a picture on both sides: does the jump show?
            try:
                fade = FADE_MS if needs_fade(junction_diff(clip, a - 40, b + 40)) else 0
            except RuntimeError:
                fade = 0
        cuts.append(Cut(a, b, fade))
    raw = clip.with_name(f"{scene_id}_nodead_raw.mp4")
    clip.replace(raw)
    try:
        apply_cuts(raw, clip, cuts)
    except Exception:
        raw.replace(clip)
        raise
    return clip, cuts


def dead_ms(clip: Path, from_ms: int = 0) -> int:
    """Total length of the dead stretches of a clip at or after `from_ms`."""
    runs = dead_runs([s for s in sample_clip(clip) if s.t_ms >= from_ms])
    return sum(b - a for a, b in runs)


def png_stat(png: bytes, t_ms: int = 0) -> FrameStat:
    """The same numbers for a picture file (tests, stills)."""
    return stat_of(Image.open(io.BytesIO(png)).convert("L").resize(SIZE), t_ms)


# --- media that is still loading ------------------------------------------------------------------
# An image / canvas whose box is one flat grey or black (not white) is not decoded yet: a viewer
# sees a grey slab where the picture should be.

LOADING_STD = 5.0  # brightness spread inside the media box below this = one flat colour
LOADING_MAX_MEAN = 235.0  # (a flat white box is an empty page, not a loading picture)
MEDIA_KINDS = ("media", "image")
MIN_MEDIA_SHARE = 0.03  # a media box smaller than this share of the view is an icon
LOAD_SIZE = (320, 200)
LOADING_MAX_MS = 4000  # a slab that stays longer than this is the picture itself, not a wait


LOADING_GRID = 8  # the box is cut into 8 x 8 cells ...
LOADING_SHARE = 0.5  # ... and it is "loading" when this share of them is one flat grey / black


def flat_share(crop: Image.Image) -> float:
    """Share of the cells of the crop that are one flat colour that is not white. (A canvas box
    often has its own toolbars drawn over it: the whole box is not flat, most of it still is.)"""
    w, h = crop.size
    flat = total = 0
    for gy in range(LOADING_GRID):
        for gx in range(LOADING_GRID):
            cell = crop.crop(
                (gx * w // LOADING_GRID, gy * h // LOADING_GRID,
                 (gx + 1) * w // LOADING_GRID, (gy + 1) * h // LOADING_GRID)
            )  # fmt: skip
            if cell.size[0] < 2 or cell.size[1] < 2:
                continue
            st = ImageStat.Stat(cell)
            total += 1
            flat += int(st.stddev[0] < LOADING_STD and st.mean[0] < LOADING_MAX_MEAN)
    return flat / total if total else 0.0


def is_loading_crop(crop: Image.Image) -> bool:
    """Mostly one flat grey or black colour: the picture has not arrived."""
    return flat_share(crop) >= LOADING_SHARE


def media_boxes(
    snapshot: dict[str, Any], clip_size: tuple[int, int]
) -> list[tuple[int, int, int, int]]:
    """Boxes (x0, y0, x1, y1) on the LOAD_SIZE grid of the snapshot's big images and canvases."""
    sx, sy = LOAD_SIZE[0] / clip_size[0], LOAD_SIZE[1] / clip_size[1]
    boxes = []
    for item in snapshot.get("items", []):
        b = item["bbox"]
        if (
            item.get("kind") not in MEDIA_KINDS
            or b["w"] * b["h"] < MIN_MEDIA_SHARE * clip_size[0] * clip_size[1]
        ):
            continue
        x0, y0 = max(0, round(b["x"] * sx)), max(0, round(b["y"] * sy))
        x1, y1 = (
            min(LOAD_SIZE[0], round((b["x"] + b["w"]) * sx)),
            min(LOAD_SIZE[1], round((b["y"] + b["h"]) * sy)),
        )
        if x1 - x0 >= 8 and y1 - y0 >= 8:
            boxes.append((x0, y0, x1, y1))
    return boxes


def snapshot_for(inventory: list[dict[str, Any]], t_ms: int) -> dict[str, Any] | None:
    """The latest snapshot at or before t_ms (the first one before any exists)."""
    before = [s for s in inventory if s["t_ms"] <= t_ms]
    return before[-1] if before else (inventory[0] if inventory else None)


def flag_runs(flags: list[tuple[int, bool]], step_ms: int, min_ms: int) -> list[tuple[int, int]]:
    """(from, to) of the runs of True that last at least min_ms."""
    out: list[tuple[int, int]] = []
    start: int | None = None
    for t, flag in flags:
        if flag and start is None:
            start = t
        elif not flag and start is not None:
            out.append((start, t))
            start = None
    if start is not None and flags:
        out.append((start, flags[-1][0] + step_ms))
    return [(a, b) for a, b in out if b - a >= min_ms]


def media_loading_runs(
    clip: Path,
    inventory: list[dict[str, Any]],
    *,
    clip_size: tuple[int, int] = (1440, 900),
    from_ms: int = 0,
    step_ms: int = SAMPLE_MS,
    min_ms: int = MIN_DEAD_MS,
) -> list[tuple[int, int]]:
    """Stretches (clip time, at or after from_ms) where some big image or canvas is a flat slab."""
    w, h = LOAD_SIZE
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(clip), "-an",
         "-vf", f"fps={1000 / step_ms:g},scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
        capture_output=True,
    )  # fmt: skip
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg sampling failed: {proc.stderr[:200]!r}")
    size = w * h
    flags: list[tuple[int, bool]] = []
    for n, i in enumerate(range(0, len(proc.stdout) - size + 1, size)):
        t = n * step_ms
        if t < from_ms:
            continue
        snap = snapshot_for(inventory, t)
        frame = Image.frombuffer("L", LOAD_SIZE, proc.stdout[i : i + size], "raw", "L", 0, 1)
        loading = bool(snap) and any(
            is_loading_crop(frame.crop(box))
            for box in media_boxes(snap, clip_size)  # type: ignore[arg-type]
        )
        flags.append((t, loading))
    runs = flag_runs(flags, step_ms, min_ms)
    last = flags[-1][0] + step_ms if flags else 0
    # a wait ends: a flat box that runs to the end of the clip, or lasts for seconds, is the picture
    return [(a, b) for a, b in runs if b < last and b - a <= LOADING_MAX_MS]
