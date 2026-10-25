"""Cut the dead time out of a recorded clip instead of speeding it up.

A clip that is longer than the speech is shortened by removing stretches where nothing happens:
ffmpeg's freezedetect finds runs of (almost) identical frames; of those, the parts near a click or
a focus box (including the hold after it) are protected, and what is left is shortened to KEEP_MS.
The cut is made with a re-encode (libx264 crf 18) so it is exact to the frame; the original clip
stays next to it as <scene>_raw.mp4. Click and focus logs are shifted to the new time axis.
"""

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FREEZE_NOISE = 0.003  # frames that differ by less than this (share of full scale) count as equal
MIN_FREEZE_MS = 600  # only stretches longer than this are worth cutting
KEEP_MS = 400  # a cut stretch keeps this much, so the video still "breathes"
ESTABLISH_MS = 1000  # the first second after the loading phase is the establishing shot: keep it
BEFORE_EVENT_MS = 250  # protected: just before an event (the cursor is already moving)
AFTER_CLICK_MS = 600  # protected: after a click without a hold of its own


@dataclass(frozen=True)
class Cut:
    from_ms: int  # in the time of the original clip
    to_ms: int

    @property
    def length(self) -> int:
        return self.to_ms - self.from_ms


@dataclass
class TrimResult:
    clip: Path
    raw: Path
    cuts: list[Cut]  # everything removed, loading phase included
    duration_ms: int  # of the new clip
    trimmed_ms: int  # dead time removed (without the loading phase)
    click_log: list[dict[str, Any]]
    focus_log: list[dict[str, Any]]
    activity_ms: list[float]
    inventory: list[dict[str, Any]] = field(default_factory=list)
    action_log: list[dict[str, Any]] = field(default_factory=list)


def detect_freezes(clip: Path, content_ms: int) -> list[tuple[float, float]]:
    """(start_ms, end_ms) of every run of identical frames at least MIN_FREEZE_MS long."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(clip), "-map", "0:v:0", "-an",
         "-vf", f"freezedetect=n={FREEZE_NOISE}:d={MIN_FREEZE_MS / 1000}", "-f", "null", "-"],
        capture_output=True, text=True,
    )  # fmt: skip
    found: list[tuple[float, float]] = []
    start: float | None = None
    for line in proc.stderr.splitlines():
        if (m := re.search(r"freeze_start:\s*([0-9.]+)", line)) is not None:
            start = float(m.group(1)) * 1000
        elif (m := re.search(r"freeze_end:\s*([0-9.]+)", line)) is not None and start is not None:
            found.append((start, float(m.group(1)) * 1000))
            start = None
    if start is not None:  # still frozen when the clip ends
        found.append((start, float(content_ms)))
    return found


def protected_windows(
    focus_log: list[dict[str, Any]], click_log: list[dict[str, Any]], start_ms: float
) -> list[tuple[float, float]]:
    """Stretches that must stay: the establishing shot, and around every event plus its hold."""
    windows = [(start_ms, start_ms + ESTABLISH_MS)]
    for f in focus_log:
        windows.append((f["t_ms"] - BEFORE_EVENT_MS, f["t_ms"] + max(f.get("hold_ms", 0), 0) + 200))
    for c in click_log:
        windows.append((c["t_ms"] - BEFORE_EVENT_MS, c["t_ms"] + AFTER_CLICK_MS))
    return sorted(windows)


def subtract(
    span: tuple[float, float], windows: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """`span` minus every window, as the pieces that are left (in order)."""
    pieces = [span]
    for w0, w1 in windows:
        out: list[tuple[float, float]] = []
        for a, b in pieces:
            if w1 <= a or w0 >= b:
                out.append((a, b))
                continue
            if w0 > a:
                out.append((a, w0))
            if w1 < b:
                out.append((w1, b))
        pieces = out
    return pieces


def cuttable(
    freezes: list[tuple[float, float]],
    protected: list[tuple[float, float]],
    start_ms: float,
    end_ms: float,
) -> list[tuple[float, float]]:
    """Quiet pieces inside [start, end], outside every protected window, long enough to cut."""
    pieces: list[tuple[float, float]] = []
    for f0, f1 in freezes:
        span = (max(f0, start_ms), min(f1, end_ms))
        if span[1] - span[0] > 0:
            pieces += subtract(span, protected)
    return [p for p in pieces if p[1] - p[0] > MIN_FREEZE_MS]


def plan_cuts(pieces: list[tuple[float, float]], excess_ms: float) -> list[Cut]:
    """Shorten pieces to KEEP_MS each, longest saving first, until `excess_ms` is removed."""
    cuts: list[Cut] = []
    left = excess_ms
    for a, b in sorted(pieces, key=lambda p: p[1] - p[0], reverse=True):
        if left <= 0:
            break
        removable = (b - a) - KEEP_MS
        take = min(removable, left)
        if take < 1:
            continue
        cuts.append(Cut(round(b - take), round(b)))  # keep the start of the stretch, cut its end
        left -= take
    return sorted(cuts, key=lambda c: c.from_ms)


def shift_time(t: float, cuts: list[Cut]) -> float:
    """`t` on the new time axis: minus everything cut before it (inside a cut: its start)."""
    removed = 0.0
    for c in cuts:
        if t >= c.to_ms:
            removed += c.length
        elif t > c.from_ms:
            removed += t - c.from_ms
    return t - removed


def shift_logs(entries: list[dict[str, Any]], cuts: list[Cut]) -> list[dict[str, Any]]:
    return [{**e, "t_ms": round(shift_time(e["t_ms"], cuts))} for e in entries]


def shift_actions(entries: list[dict[str, Any]], cuts: list[Cut]) -> list[dict[str, Any]]:
    """Like shift_logs, and the end of each action (end_ms) moves with it."""
    return [
        {
            **e,
            "t_ms": round(shift_time(e["t_ms"], cuts)),
            "end_ms": round(shift_time(e.get("end_ms", e["t_ms"]), cuts)),
        }
        for e in entries
    ]


def apply_cuts(raw: Path, out: Path, cuts: list[Cut]) -> None:
    """Re-encode `raw` without the cut stretches (exact to the frame), 30 fps yuv420p, no audio."""
    drop = "+".join(f"gte(t\\,{c.from_ms / 1000:.3f})*lt(t\\,{c.to_ms / 1000:.3f})" for c in cuts)
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(raw),
         "-vf", f"select='not({drop})',setpts=N/(30*TB)", "-r", "30",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
         "-an", str(out)],
        capture_output=True, text=True,
    )  # fmt: skip
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg cut failed: {result.stderr[:300]}")


def trim_dead_time(
    clip: Path,
    *,
    scene_id: str,
    lead_ms: int,
    content_ms: int,
    speech_ms: int,
    focus_log: list[dict[str, Any]],
    click_log: list[dict[str, Any]],
    activity_ms: list[float],
    inventory: list[dict[str, Any]] | None = None,
    action_log: list[dict[str, Any]] | None = None,
) -> TrimResult | None:
    """Shorten `clip` toward `speech_ms` by cutting dead time; None when nothing can be cut.

    lead_ms is what the scene does not show (loading phase, hidden setup): it is cut too, so the new
    clip starts with the first thing the viewer sees."""
    usable = content_ms - lead_ms
    excess = usable - speech_ms
    if excess <= 0:
        return None
    freezes = detect_freezes(clip, content_ms)
    protect = protected_windows(focus_log, click_log, lead_ms)
    pieces = cuttable(freezes, protect, lead_ms, content_ms)
    cuts = plan_cuts(pieces, excess)
    if not cuts:
        return None
    all_cuts = ([Cut(0, lead_ms)] if lead_ms > 0 else []) + cuts
    raw = clip.with_name(f"{scene_id}_raw.mp4")
    clip.replace(raw)
    try:
        apply_cuts(raw, clip, all_cuts)
    except Exception:
        raw.replace(clip)  # leave the scene as it was recorded
        raise

    def kept(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [e for e in items if e["t_ms"] >= lead_ms]

    return TrimResult(
        clip=clip,
        raw=raw,
        cuts=all_cuts,
        duration_ms=round(content_ms - sum(c.length for c in all_cuts)),
        trimmed_ms=sum(c.length for c in cuts),
        click_log=shift_logs(kept(click_log), all_cuts),
        focus_log=shift_logs(kept(focus_log), all_cuts),
        activity_ms=[shift_time(t, all_cuts) for t in activity_ms if t >= lead_ms],
        inventory=shift_logs(kept(inventory or []), all_cuts),
        action_log=shift_actions(kept(action_log or []), all_cuts),
    )
