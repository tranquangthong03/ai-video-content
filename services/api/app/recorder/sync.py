"""A sync pulse: the clock of the recorder's logs against the clock of the video.

Right after the page is created (while it is still blank, long before the phase that is shown) the
page flashes a colour nobody uses for a moment, at a time the recorder's own clock knows. The first
frame of the clip with that colour tells where the video clock stands against the log clock; every
cut of the clip is then made at log time + that offset. The pulse sits in the loading phase that is
cut off (before start_offset_ms) and must never reach the finished video: video_has_pulse() is the
check that says so.
"""

import subprocess
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Page

PULSE_HTML = "<!doctype html><body style='margin:0;background:#ff00ff'></body>"
PULSE_MS = 300
PULSE_SETTLE_MS = 200  # the loading phase lasts at least this long after the pulse
MAX_OFFSET_MS = 4000  # a bigger offset means the pulse was not seen right: do not trust it
SAMPLE = (48, 27)  # frames are looked at this small
MIN_AREA = 0.6  # share of the frame that must be pulse-coloured for the pulse itself
LEAK_AREA = 0.05  # share that counts as a leak in a finished video


def is_pulse_pixel(r: int, g: int, b: int) -> bool:
    return r > 200 and g < 80 and b > 200


def pulse_share(frame: bytes) -> float:
    """Share of pulse-coloured pixels in one raw RGB frame."""
    pixels = len(frame) // 3
    hits = sum(
        1 for i in range(0, pixels * 3, 3) if is_pulse_pixel(frame[i], frame[i + 1], frame[i + 2])
    )
    return hits / pixels if pixels else 0.0


def frames(clip: Path, from_ms: int, to_ms: int | None, fps: float) -> list[tuple[int, bytes]]:
    """(time in ms, raw RGB frame) sampled `fps` times a second between from_ms and to_ms."""
    w, h = SAMPLE
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(0, from_ms) / 1000:.3f}", "-i", str(clip)]
    if to_ms is not None:
        cmd += ["-t", f"{max(0, to_ms - from_ms) / 1000:.3f}"]
    cmd += ["-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    out = subprocess.run(cmd, capture_output=True).stdout
    size = w * h * 3
    return [
        (round(from_ms + i * 1000 / fps), out[i * size : (i + 1) * size])
        for i in range(len(out) // size)
    ]


def emit_pulse(page: Page, now: Callable[[], int]) -> int:
    """Flash the pulse on the (still blank) page; returns the log time at which it was shown."""
    page.set_content(PULSE_HTML)
    shown = now()
    page.wait_for_timeout(PULSE_MS)
    page.set_content("<!doctype html><body style='margin:0;background:#fff'></body>")
    return shown


def find_pulse(clip: Path, search_ms: int = 6000) -> int | None:
    """Time (video clock, ms) of the first frame that is the pulse, or None."""
    for t, frame in frames(clip, 0, search_ms, 30):
        if pulse_share(frame) >= MIN_AREA:
            return t
    return None


def measure_offset(clip: Path, pulse_log_ms: int) -> int | None:
    """video time = log time + offset. None when the pulse cannot be found (or looks wrong)."""
    seen = find_pulse(clip)
    if seen is None:
        return None
    offset = seen - pulse_log_ms
    return offset if abs(offset) <= MAX_OFFSET_MS else None


def video_has_pulse(clip: Path, from_ms: int = 0, fps: float = 10) -> bool:
    """True when any frame from `from_ms` on is (partly) pulse-coloured: it leaked into the film."""
    return any(pulse_share(f) >= LEAK_AREA for _, f in frames(clip, from_ms, None, fps))
