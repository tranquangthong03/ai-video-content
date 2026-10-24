"""Pure helpers for the recorder: how the mouse moves, how typing sounds, where the video idles."""

import math
import random

FRAME_MS = 16  # one mouse step per ~display frame so the cursor looks continuous in the recording


def ease_in_out(u: float) -> float:
    return 4 * u * u * u if u < 0.5 else 1 - math.pow(-2 * u + 2, 3) / 2


def move_duration_ms(distance: float) -> int:
    """Longer moves take longer, between 350 and 900 ms."""
    return int(min(900, max(350, 300 + distance * 0.5)))


def mouse_path(
    start: tuple[float, float], end: tuple[float, float], duration_ms: int
) -> list[tuple[float, float, float]]:
    """(x, y, wait_ms) steps from start to end with ease-in-out; the last step lands on `end`."""
    steps = max(6, round(duration_ms / FRAME_MS))
    wait = duration_ms / steps
    out = []
    for i in range(1, steps + 1):
        u = ease_in_out(i / steps)
        out.append((start[0] + (end[0] - start[0]) * u, start[1] + (end[1] - start[1]) * u, wait))
    out[-1] = (end[0], end[1], out[-1][2])
    return out


def typing_delays(text: str, rng: random.Random) -> list[int]:
    """Pause after each character: 60-90 ms like a person typing steadily."""
    return [rng.randint(60, 90) for _ in text]


def scroll_steps(total: float, steps: int = 10) -> list[float]:
    """A wheel scroll split into eased small steps that sum to `total`."""
    weights = [math.sin(math.pi * (i + 0.5) / steps) for i in range(steps)]
    scale = total / sum(weights)
    return [w * scale for w in weights]


def idle_gaps(
    activity_ms: list[float], start_ms: float, end_ms: float, *, min_gap_ms: float = 500
) -> list[int]:
    """Stretches of [start, end] in which nothing happens (no click, hover, scroll, highlight or
    page change). `activity_ms` are the instants where something did; gaps shorter than
    min_gap_ms are not reported."""
    points = sorted(t for t in activity_ms if start_ms <= t <= end_ms)
    edges = [start_ms, *points, end_ms]
    gaps = [round(b - a) for a, b in zip(edges, edges[1:], strict=False) if b - a >= min_gap_ms]
    return gaps
