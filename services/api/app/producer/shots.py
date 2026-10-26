"""Shots: one shot per spoken phrase, and every shot starts with something changing on screen.

A change is the camera moving to a new focus, something being done on the page, or a cut to the
next stretch of footage. A shot that starts without one gets a punch-in (the frame grows 8-12 %
within 6 frames, then eases back); a long shot gets more punch-ins so no stretch of the video
stays unchanged for more than MAX_STATIC_MS. Pure functions on scene time (ms).
"""

from dataclasses import dataclass
from typing import Any

FPS = 30
PUNCH_FRAMES = 6  # the grow-in takes six frames
PUNCH_MS = round(PUNCH_FRAMES * 1000 / FPS)
PUNCH_SCALES = (0.08, 0.10, 0.12)  # +8 .. +12 %, taken in turn so repeats do not look the same
MAX_STATIC_MS = 3000
CHANGE_WINDOW_MS = 350  # a change this close to a shot's start counts for it


@dataclass(frozen=True)
class Shot:
    from_ms: int
    to_ms: int
    change: str  # focus | action | cut | punch


def phrase_shots(captions: list[dict[str, Any]], duration_ms: int) -> list[tuple[int, int]]:
    """Contiguous (from, to) shots: one per caption group, the first from 0, the last to the end."""
    starts = sorted({max(0, round(c["start_ms"])) for c in captions if c["start_ms"] < duration_ms})
    if not starts or starts[0] > 0:
        starts = [0, *starts]
    bounds = [*starts, duration_ms]
    return [(a, b) for a, b in zip(bounds, bounds[1:], strict=False) if b > a]


def _near(times: list[float], t: float) -> bool:
    return any(t - CHANGE_WINDOW_MS <= x <= t + CHANGE_WINDOW_MS for x in times)


def plan_shots(
    captions: list[dict[str, Any]],
    duration_ms: int,
    *,
    focus_times: list[float],
    action_times: list[float],
    cut_times: list[float] | None = None,
) -> tuple[list[Shot], list[dict[str, float]]]:
    """(shots, punches). punches = [{t_ms, scale}] for the renderer; scale is the extra zoom."""
    cuts = [0.0, *(cut_times or [])]
    shots: list[Shot] = []
    punches: list[dict[str, float]] = []
    turn = 0

    def punch(at: float) -> None:
        nonlocal turn
        punches.append({"t_ms": round(at), "scale": PUNCH_SCALES[turn % len(PUNCH_SCALES)]})
        turn += 1

    for a, b in phrase_shots(captions, duration_ms):
        if _near(cuts, a):
            change = "cut"
        elif _near(focus_times, a):
            change = "focus"
        elif _near(action_times, a):
            change = "action"
        else:
            change = "punch"
            punch(a)
        shots.append(Shot(a, b, change))

    # no stretch longer than MAX_STATIC_MS without a change (a punch counts as one)
    changes = sorted({*focus_times, *action_times, *cuts, *(p["t_ms"] for p in punches)})
    edge = [0.0, *[c for c in changes if 0 < c < duration_ms], float(duration_ms)]
    for left, right in zip(edge, edge[1:], strict=False):
        t = left
        while right - t > MAX_STATIC_MS:
            t += MAX_STATIC_MS - PUNCH_MS
            punch(t)
    punches.sort(key=lambda p: p["t_ms"])
    return shots, punches


def max_static_ms(
    duration_ms: int, focus_times: list[float], action_times: list[float],
    punches: list[dict[str, float]], cut_times: list[float] | None = None,
) -> int:  # fmt: skip
    """The longest stretch of the scene in which no change happens (what the scorecard checks)."""
    changes = sorted({
        0.0, *focus_times, *action_times, *(cut_times or []), *(p["t_ms"] for p in punches),
    })  # fmt: skip
    edge = [c for c in changes if 0 <= c < duration_ms] + [float(duration_ms)]
    return round(max((b - a for a, b in zip(edge, edge[1:], strict=False)), default=duration_ms))
