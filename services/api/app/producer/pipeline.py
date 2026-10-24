"""Produce a video from an approved script: time it, record each scene, fit the timeline, render.

Estimated speech time decides how long every scene lasts (no TTS yet). A recording that is shorter
than its speech is held on its last frame; a longer one is played faster, up to 1.5x, and the scene
grows to fit the rest. The result is a report with every number behind the final timeline.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.browser.session import BrowserSession
from app.core.timing import PAUSE_MS, EstimatedTimer, estimate_captions
from app.recorder.motion import idle_gaps
from app.recorder.record import RecordResult, record_scene
from app.schemas.generated.product_profile import ProductProfile
from app.schemas.generated.script import Script
from app.script.lite import is_lite
from app.script.theme import highlight_color

MAX_RATE = 1.5
IDLE_LIMIT_MS = 2500
Recorder = Callable[..., RecordResult]
Renderer = Callable[[dict[str, Any], Path, Path], Any]


def plan_scene_timing(speech_ms: int, usable_ms: int | None) -> tuple[int, float, bool]:
    """(final_ms, playback_rate, freeze_last_frame) for a scene.

    usable_ms is the recorded time left after the loading phase (and a hidden setup) are cut; None
    for scenes without footage. Shorter than the speech: hold the last frame. Longer: speed up to
    MAX_RATE; if it is still longer the scene simply lasts as long as the sped-up clip.
    """
    if usable_ms is None:
        return speech_ms, 1.0, False
    if usable_ms < speech_ms:
        return speech_ms, 1.0, True
    rate = min(MAX_RATE, usable_ms / speech_ms)
    return max(speech_ms, round(usable_ms / rate)), round(rate, 3), False


def scene_idle_gaps(
    activity_ms: list[float], trim_ms: float, usable_ms: float, rate: float, final_ms: int
) -> list[int]:
    """Quiet stretches on the final timeline: the clip time is shifted by the trim and sped up by
    `rate`; a held last frame (final longer than the clip) counts as quiet too."""
    on_timeline = [(t - trim_ms) / rate for t in activity_ms if t >= trim_ms]
    return idle_gaps(on_timeline, 0, final_ms)


@dataclass
class SceneOutcome:
    id: str
    type: str
    kind: str  # thao tác | cuộn-highlight | ảnh | chữ
    speech_ms: int
    usable_ms: int | None
    final_ms: int
    playback_rate: float
    freeze: bool
    idle_max_ms: int | None
    warnings: list[str] = field(default_factory=list)
    steps_ok: int = 0
    steps_failed: int = 0
    filled_ms: int = 0
    feature: str | None = None
    recording: str = "recording"

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class ProduceResult:
    video: Path
    report: dict[str, Any]
    script: Script
    scenes: list[SceneOutcome]


def kind_of(scene_root: Any, record: RecordResult | None) -> str:
    if record is not None and record.kind == "fallback_screenshot":
        return "ảnh"
    mode = scene_root.visual.mode
    if mode == "recording":
        if is_lite(scene_root.visual):
            return "chỉ vị trí (showcase_lite)"
        return (
            "cuộn-highlight"
            if any(a.do == "highlight" for a in scene_root.visual.actions)
            else "thao tác"
        )
    return "ảnh" if mode == "screenshot" else "chữ"


def produce(
    script: Script,
    *,
    url: str,
    job_dir: Path,
    session: BrowserSession,
    render: Renderer,
    profile: ProductProfile | None = None,
    progress: Callable[[str], None] | None = None,
    recorder: Recorder = record_scene,
    token_usage: dict[str, Any] | None = None,
    extra_report: dict[str, Any] | None = None,
) -> ProduceResult:
    """Record every scene in order, fit the timeline, render, and write report.json."""
    say = progress or (lambda msg: None)
    job_dir = job_dir.resolve()  # the renderer runs in another directory: paths must be absolute
    work = job_dir / "produce"
    work.mkdir(parents=True, exist_ok=True)
    timer = EstimatedTimer()
    color = highlight_color(script.theme.primary)
    phases: dict[str, float] = {}
    t0 = time.monotonic()
    speech = {s.root.id: timer.timing(s.root.voiceover) for s in script.scenes}
    phases["timing"] = round(time.monotonic() - t0, 2)

    outcomes: list[SceneOutcome] = []
    assets: dict[str, dict[str, Any]] = {}
    data = script.model_dump()
    started = time.monotonic()
    for i, scene in enumerate(script.scenes):
        s = scene.root
        timing = speech[s.id]
        speech_ms = timing.duration_ms
        say(f"[record] scene {i + 1}/{len(script.scenes)} {s.id} ({s.type}) ...")
        record = recorder(session, scene, work, speech_ms, root_url=url, highlight_color=color)
        usable: int | None = None
        trim = 0
        if record.kind == "recording":
            visual = s.visual
            trim = record.start_offset_ms
            if visual.setup and not visual.show_setup:
                trim = record.setup_end_ms
            usable = max(0, record.content_ms - trim)
        final_ms, rate, freeze = plan_scene_timing(speech_ms, usable)
        idle: int | None = None
        if record.kind == "recording":
            gaps = scene_idle_gaps(record.activity_ms, trim, usable or 0, rate, final_ms)
            idle = max(gaps, default=0)
        elif record.kind in ("screenshot", "fallback_screenshot"):
            idle = 0  # a still page still moves: the template's Ken Burns zoom never pauses
        data["scenes"][i]["duration_ms"] = final_ms
        captions = estimate_captions(s.voiceover, 0, max(1, speech_ms - PAUSE_MS))
        entry: dict[str, Any] = {"captions": captions}
        if record.kind == "recording" and record.clip_path:
            entry.update(
                clip_url=str(record.clip_path),
                start_offset_ms=record.start_offset_ms,
                trim_start_ms=max(0, trim - record.start_offset_ms),
                playback_rate=rate,
                freeze_last_frame=freeze,
                clip_duration_ms=record.content_ms,
                clip_width=1920,
                clip_height=1080,
                click_log=[e for e in record.click_log if e["t_ms"] >= trim],
            )
        elif record.image_path:
            entry["screenshot_url"] = str(record.image_path)
        assets[s.id] = entry
        outcomes.append(
            SceneOutcome(
                id=s.id,
                type=s.type,
                kind=kind_of(s, record),
                speech_ms=speech_ms,
                usable_ms=usable,
                final_ms=final_ms,
                playback_rate=rate,
                freeze=freeze,
                idle_max_ms=idle,
                warnings=record.warnings,
                steps_ok=record.steps_ok,
                steps_failed=record.steps_failed,
                filled_ms=record.filled_ms,
                feature=getattr(s, "feature", None),
                recording=record.kind,
            )
        )
    phases["record"] = round(time.monotonic() - started, 1)

    final_script = Script.model_validate(data)
    props = {"script": final_script.model_dump(), "assets": assets}
    out = job_dir / "video.mp4"
    say("[render] rendering ...")
    r0 = time.monotonic()
    rendered = render(props, out, work)
    phases["render"] = round(time.monotonic() - r0, 1)
    phases["total"] = round(time.monotonic() - t0, 1)

    from app.producer.render import probe

    info = probe(out)
    features = []
    if profile is not None:
        names = {f.id: f.name for f in profile.features}
        features = [
            {"id": o.feature, "name": names.get(o.feature or "", o.feature)}
            for o in outcomes
            if o.feature
        ]
    estimated = sum(o.speech_ms for o in outcomes)
    planned = sum(o.final_ms for o in outcomes)
    footage_ms = sum(o.final_ms for o in outcomes if o.recording == "recording")
    report: dict[str, Any] = {
        "video": str(out),
        "target_ms": script.target_duration_s * 1000,
        "estimated_ms": estimated,
        "planned_ms": planned,
        "footage_ratio": round(footage_ms / planned, 3) if planned else 0.0,
        "actual_ms": info["duration_ms"],
        "ffprobe": {
            k: info[k] for k in ("codec_name", "width", "height", "pix_fmt", "r_frame_rate")
        },
        "idle_limit_ms": IDLE_LIMIT_MS,
        "idle_ok": all(o.idle_max_ms is None or o.idle_max_ms <= IDLE_LIMIT_MS for o in outcomes),
        "scenes": [o.as_dict() for o in outcomes],
        "features": features,
        "phases_s": phases,
        "render_ms": getattr(rendered, "render_ms", None),
        "warnings": [w for o in outcomes for w in o.warnings],
        "tokens": token_usage,
        **(extra_report or {}),
    }
    (job_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return ProduceResult(out, report, final_script, outcomes)
