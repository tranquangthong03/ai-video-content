"""The film made while the agent ran, turned into the FlowRecording the producer works with.

Everything the live film noted is on the recorder's log clock; the sync pulse says how far the video
clock is from it, so first every time is moved onto the video clock. Then what must not be seen is
cut out of the clip with ffmpeg and every log is moved along with it:

- llm_wait: the time spent waiting for the model, except 200 ms kept on each side (a pause that is
  cut to nothing looks like a jump). It is cut by the times noted, not by looking for still frames,
  so a spinner or a carousel in the page makes no difference.
- retry / rejected: an attempt that failed, whole.

What is left goes through the same per-chapter plan as a replayed recording (dead-time trimming, the
focus planner, the login gate).
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.producer.render import probe
from app.producer.trim import Cut, apply_cuts, shift_actions, shift_logs, shift_time
from app.recorder.flow import FlowRecording, StepMark
from app.schemas.generated.flow_run import FlowRun

WAIT_PAD_MS = 200
MIN_CUT_MS = 300  # a stretch shorter than this is not worth a jump


@dataclass
class LiveCuts:
    cuts: list[Cut]
    llm_wait_ms: int = 0
    retry: int = 0
    rejected: int = 0


def merge(cuts: list[Cut]) -> list[Cut]:
    out: list[Cut] = []
    for c in sorted(cuts, key=lambda c: c.from_ms):
        if out and c.from_ms <= out[-1].to_ms:
            out[-1] = Cut(out[-1].from_ms, max(out[-1].to_ms, c.to_ms))
        else:
            out.append(c)
    return out


def cuts_from_segments(segments: list[dict[str, Any]]) -> LiveCuts:
    """Cuts (same clock as the segments) and what they remove."""
    cuts: list[Cut] = []
    out = LiveCuts(cuts)
    for s in segments:
        start, end = int(s["from_ms"]), int(s["to_ms"])
        if s["kind"] == "llm_wait":
            start, end = start + WAIT_PAD_MS, end - WAIT_PAD_MS
            if end - start < MIN_CUT_MS:
                continue
            out.llm_wait_ms += end - start
        elif end - start <= 0:
            continue
        elif s["kind"] == "retry":
            out.retry += 1
        else:
            out.rejected += 1
        cuts.append(Cut(start, end))
    out.cuts = merge(cuts)
    return out


def live_usable(job_dir: Path, run: FlowRun) -> bool:
    live = run.live
    if live is None or not (job_dir / live.clip).is_file() or not (job_dir / live.logs).is_file():
        return False
    try:
        return int(probe(job_dir / live.clip)["duration_ms"]) > 0
    except Exception:
        return False


def recording_from_live(job_dir: Path, run: FlowRun) -> FlowRecording:
    live = run.live
    assert live is not None
    logs = json.loads((job_dir / live.logs).read_text(encoding="utf-8"))
    off = live.sync_offset_ms

    def video(entries: list[dict[str, Any]], *keys: str) -> list[dict[str, Any]]:
        return [{**e, **{k: e[k] + off for k in keys if k in e}} for e in entries]

    segments = [
        {"from_ms": s.from_ms + off, "to_ms": s.to_ms + off, "kind": s.kind} for s in live.segments
    ]
    planned = cuts_from_segments(segments)
    raw = job_dir / live.clip
    clip = raw
    if planned.cuts:
        clip = raw.with_name("flow_cut.mp4")
        apply_cuts(raw, clip, planned.cuts)
    cuts = planned.cuts
    chapter_of = {s.i: s.chapter_id for s in run.steps}
    marks = [
        StepMark(
            m.i, chapter_of.get(m.i),
            round(shift_time(m.start_ms + off, cuts)),
            round(shift_time(m.end_ms + off, cuts)),
            True,
        )
        for m in live.marks
    ]  # fmt: skip
    return FlowRecording(
        clip_path=clip,
        start_offset_ms=round(shift_time(live.start_offset_ms + off, cuts)),
        content_ms=int(probe(clip)["duration_ms"]),
        width=int(logs.get("width", 1440)),
        height=int(logs.get("height", 900)),
        marks=marks,
        click_log=shift_logs(video(logs["click_log"], "t_ms"), cuts),
        focus_log=shift_logs(video(logs["focus_log"], "t_ms"), cuts),
        inventory=shift_logs(video(logs["inventory"], "t_ms"), cuts),
        action_log=shift_actions(video(logs["action_log"], "t_ms", "end_ms"), cuts),
        activity_ms=[shift_time(t + off, cuts) for t in logs["activity_ms"]],
        warnings=list(logs.get("warnings", [])),
        sync_offset_ms=0,  # the logs are on the video clock now
        pulse_at_ms=round(shift_time(live.pulse_at_ms + off, cuts)),
        source="live",
        llm_wait_cut_ms=planned.llm_wait_ms,
        retry_cut=planned.retry,
        rejected_cut=planned.rejected,
    )
