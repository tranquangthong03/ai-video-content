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

from PIL import Image, ImageFilter, ImageStat

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


def cut_dead(
    clip: Path, scene_id: str, from_ms: int, content_ms: int
) -> tuple[Path, list[tuple[int, int]]] | None:
    """Cut the dead stretches (at or after `from_ms`) out of `clip`; the new clip replaces it and
    the raw one stays as <scene>_nodead_raw.mp4. None when nothing is dead, or cutting would leave
    less than a second. Returns (clip, the cuts in the old clip's time)."""
    from app.producer.trim import Cut, apply_cuts

    runs = dead_runs([s for s in sample_clip(clip) if s.t_ms >= from_ms])
    runs = [(a, min(b, content_ms)) for a, b in runs]
    if not runs or content_ms - from_ms - sum(b - a for a, b in runs) < MIN_KEEP_MS:
        return None
    raw = clip.with_name(f"{scene_id}_nodead_raw.mp4")
    clip.replace(raw)
    try:
        apply_cuts(raw, clip, [Cut(a, b) for a, b in runs])
    except Exception:
        raw.replace(clip)
        raise
    return clip, runs


def dead_ms(clip: Path, from_ms: int = 0) -> int:
    """Total length of the dead stretches of a clip at or after `from_ms`."""
    runs = dead_runs([s for s in sample_clip(clip) if s.t_ms >= from_ms])
    return sum(b - a for a, b in runs)


def png_stat(png: bytes, t_ms: int = 0) -> FrameStat:
    """The same numbers for a picture file (tests, stills)."""
    return stat_of(Image.open(io.BytesIO(png)).convert("L").resize(SIZE), t_ms)
