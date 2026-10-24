"""Produce a video from an approved script: time it, record each scene, fit the timeline, render.

Estimated speech time decides how long every scene lasts (no TTS yet). A recording that is shorter
than its speech is held on its last frame; a longer one has its dead time cut out (producer/trim.py)
and, only for scrolling/pointing scenes, may play up to 1.15x; if it is still longer the scene
grows. Actions are never sped up. The result is a report with every number behind the timeline.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.browser.session import BrowserSession
from app.core.timing import PAUSE_MS, EstimatedTimer, estimate_captions
from app.producer.dedupe import MIN_SCENES, swap_scene, used_texts
from app.producer.trim import trim_dead_time
from app.recorder.motion import idle_gaps
from app.recorder.record import RecordResult, record_scene
from app.schemas.generated.product_profile import ProductProfile
from app.schemas.generated.scene import Scene
from app.schemas.generated.script import Script
from app.script.lite import PageIndex, is_lite, load_page_index
from app.script.signature import recorded_signature
from app.script.theme import highlight_color

MAX_RATE = 1.0  # clicks and typing play at normal speed
SCROLL_RATE = 1.15  # scrolling and pointing scenes may be a little faster
SCROLL_KINDS = ("cuộn-highlight", "chỉ vị trí (showcase_lite)")
IDLE_LIMIT_MS = 2500
MAX_SWAPS = 3  # sections tried for a repeated scene before giving up
MAIN_FOCUS = ("click", "dblclick", "type", "hover", "highlight", "section")
Recorder = Callable[..., RecordResult]
Renderer = Callable[[dict[str, Any], Path, Path], Any]


def plan_scene_timing(
    speech_ms: int, usable_ms: int | None, max_rate: float = MAX_RATE
) -> tuple[int, float, bool]:
    """(final_ms, playback_rate, freeze_last_frame) for a scene.

    usable_ms is the recorded time left after the loading phase (and a hidden setup) are cut and
    the dead time trimmed; None for scenes without footage. Shorter than the speech: hold the last
    frame. Longer: speed up to max_rate (1.0 = never); if it is still longer the scene simply lasts
    as long as the (sped-up) clip.
    """
    if usable_ms is None:
        return speech_ms, 1.0, False
    if usable_ms < speech_ms:
        return speech_ms, 1.0, True
    rate = min(max_rate, usable_ms / speech_ms)
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
    trimmed_ms: int = 0  # dead time cut out of the clip
    cuts: list[dict[str, int]] = field(
        default_factory=list
    )  # removed stretches, original clip time
    actions: int = 0  # things the viewer was shown (clicks, typing, highlights, sections)
    hold_avg_ms: int | None = None  # mean time kept on the result of those actions

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


@dataclass
class ClipPlan:
    """What the renderer gets for one recorded scene: the clip, where to start it, and its logs."""

    clip: Path | None
    start_offset_ms: int
    trim_start_ms: int
    content_ms: int  # length of `clip`
    usable_ms: int  # what the scene can show of it
    click_log: list[dict[str, Any]]
    focus_log: list[dict[str, Any]]
    activity_ms: list[float]  # times of anything happening, from the first shown moment
    trimmed_ms: int = 0
    cuts: list[dict[str, int]] = field(default_factory=list)


def plan_clip(record: RecordResult, visual: Any, speech_ms: int, scene_id: str) -> ClipPlan:
    """Hide the loading phase and hidden setup; a clip longer than the speech loses dead time."""
    lead = record.start_offset_ms
    if visual.setup and not visual.show_setup:
        lead = record.setup_end_ms
    shown = [e for e in record.click_log if e["t_ms"] >= lead]
    focus = [e for e in record.focus_log if e["t_ms"] >= lead]
    plan = ClipPlan(
        record.clip_path,
        record.start_offset_ms,
        max(0, lead - record.start_offset_ms),
        record.content_ms,
        max(0, record.content_ms - lead),
        shown,
        focus,
        [t - lead for t in record.activity_ms if t >= lead],
    )
    if record.clip_path is None or plan.usable_ms <= speech_ms:
        return plan
    try:
        cut = trim_dead_time(
            record.clip_path,
            scene_id=scene_id,
            lead_ms=lead,
            content_ms=record.content_ms,
            speech_ms=speech_ms,
            focus_log=record.focus_log,
            click_log=record.click_log,
            activity_ms=record.activity_ms,
        )
    except Exception as e:  # the clip as recorded is still usable
        record.warnings.append(f"{scene_id}: không cắt được đoạn chờ ({type(e).__name__})")
        return plan
    if cut is None:
        return plan
    return ClipPlan(
        cut.clip,
        0,
        0,
        cut.duration_ms,
        cut.duration_ms,
        cut.click_log,
        cut.focus_log,
        cut.activity_ms,
        cut.trimmed_ms,
        [{"from_ms": c.from_ms, "to_ms": c.to_ms} for c in cut.cuts],
    )


@dataclass
class Dedupe:
    """Which parts of which pages the scenes so far have shown."""

    index: PageIndex | None
    seen: dict[str, str] = field(default_factory=dict)  # signature -> scene id
    used: set[str] = field(default_factory=set)  # headings already scrolled to
    notes: list[str] = field(default_factory=list)


def record_unique(
    recorder: Recorder,
    session: BrowserSession,
    scene: Scene,
    work: Path,
    speech_ms: int,
    url: str,
    color: str,
    viewport: dict[str, int],
    dedupe: Dedupe,
    *,
    can_drop: bool,
) -> tuple[Scene, RecordResult] | None:
    """Record a scene; if it repeats an earlier one, re-aim it at a new section or drop it."""

    def take(sc: Scene) -> RecordResult:
        return recorder(
            session, sc, work, speech_ms, root_url=url, highlight_color=color, viewport=viewport
        )

    record = take(scene)
    if record.kind != "recording":
        return scene, record
    size = (viewport["width"], viewport["height"])
    sid = scene.root.id
    sig = recorded_signature(scene.root.visual.model_dump(), record.focus_log, size)
    for _ in range(MAX_SWAPS):
        if sig is None or sig not in dedupe.seen:
            break
        earlier = dedupe.seen[sig]
        swapped = swap_scene(scene, dedupe.index, dedupe.used)
        if swapped is not None:
            scene, section = swapped
            dedupe.used.add(section.text.lower())  # whatever it turns out to be, not this one again
            dedupe.notes.append(
                f"{sid}: trùng hình ảnh với {earlier}, đổi sang section «{section.text}»"
            )
            record = take(scene)
            sig = recorded_signature(scene.root.visual.model_dump(), record.focus_log, size)
        elif can_drop:
            dedupe.notes.append(f"{sid}: trùng hình ảnh với {earlier} và hết section, bỏ cảnh")
            return None
        else:
            dedupe.notes.append(
                f"{sid}: trùng hình ảnh với {earlier} (giữ vì cần ≥ {MIN_SCENES} cảnh)"
            )
            break
    if sig is not None:
        dedupe.seen.setdefault(sig, sid)
    dedupe.used |= used_texts(scene.root.visual.model_dump())
    return scene, record


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
    viewport = {"width": script.capture.width, "height": script.capture.height}
    dedupe = Dedupe(load_page_index(job_dir / "explore"))
    dropped: set[int] = set()
    for i, scene in enumerate(script.scenes):
        s = scene.root
        timing = speech[s.id]
        speech_ms = timing.duration_ms
        say(f"[record] scene {i + 1}/{len(script.scenes)} {s.id} ({s.type}) ...")
        recorded = record_unique(
            recorder, session, scene, work, speech_ms, url, color, viewport, dedupe,
            can_drop=len(script.scenes) - len(dropped) > MIN_SCENES,
        )  # fmt: skip
        if recorded is None:
            dropped.add(i)
            continue
        scene, record = recorded
        s = scene.root
        data["scenes"][i] = s.model_dump()
        kind = kind_of(s, record)
        plan = plan_clip(record, s.visual, speech_ms, s.id) if record.kind == "recording" else None
        usable = plan.usable_ms if plan else None
        max_rate = SCROLL_RATE if kind in SCROLL_KINDS else MAX_RATE
        final_ms, rate, freeze = plan_scene_timing(speech_ms, usable, max_rate)
        idle: int | None = None
        if plan is not None:
            gaps = scene_idle_gaps(plan.activity_ms, 0, plan.usable_ms, rate, final_ms)
            idle = max(gaps, default=0)
        elif record.kind in ("screenshot", "fallback_screenshot"):
            idle = 0  # a still page still moves: the template's Ken Burns zoom never pauses
        data["scenes"][i]["duration_ms"] = final_ms
        captions = estimate_captions(s.voiceover, 0, max(1, speech_ms - PAUSE_MS))
        entry: dict[str, Any] = {"captions": captions}
        shown = [f for f in (plan.focus_log if plan else []) if f["kind"] in MAIN_FOCUS]
        holds = [f["hold_ms"] for f in shown if f["hold_ms"] > 0]
        if plan is not None and plan.clip is not None:
            entry.update(
                clip_url=str(plan.clip),
                start_offset_ms=plan.start_offset_ms,
                trim_start_ms=plan.trim_start_ms,
                playback_rate=rate,
                freeze_last_frame=freeze,
                clip_duration_ms=plan.content_ms,
                clip_width=record.width or script.capture.width,
                clip_height=record.height or script.capture.height,
                click_log=plan.click_log,
                focus_log=plan.focus_log,
                segments=plan.cuts,
            )
        elif record.image_path:
            entry["screenshot_url"] = str(record.image_path)
            entry["clip_width"], entry["clip_height"] = viewport["width"], viewport["height"]
            if s.type == "cta":  # no button to point at: drift toward the header
                bar = {"x": 0, "y": 0, "w": viewport["width"], "h": 140}
                entry["focus_log"] = [{"t_ms": 0, "bbox": bar, "kind": "section", "hold_ms": 0}]
        assets[s.id] = entry
        outcomes.append(
            SceneOutcome(
                id=s.id,
                type=s.type,
                kind=kind,
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
                trimmed_ms=plan.trimmed_ms if plan else 0,
                cuts=plan.cuts if plan else [],
                actions=len(shown),
                hold_avg_ms=round(sum(holds) / len(holds)) if holds else None,
            )
        )
    phases["record"] = round(time.monotonic() - started, 1)

    data["scenes"] = [sc for j, sc in enumerate(data["scenes"]) if j not in dropped]
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
    all_holds = [
        h for o in outcomes if o.hold_avg_ms is not None for h in [o.hold_avg_ms] * o.actions
    ]
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
        "speedup_used": max(
            (o.playback_rate for o in outcomes if o.usable_ms is not None), default=1.0
        ),
        "trimmed_ms": sum(o.trimmed_ms for o in outcomes),
        "actions_per_scene": {o.id: o.actions for o in outcomes if o.usable_ms is not None},
        "hold_avg_ms": round(sum(all_holds) / len(all_holds)) if all_holds else None,
        "idle_limit_ms": IDLE_LIMIT_MS,
        "idle_ok": all(o.idle_max_ms is None or o.idle_max_ms <= IDLE_LIMIT_MS for o in outcomes),
        "scenes": [o.as_dict() for o in outcomes],
        "features": features,
        "phases_s": phases,
        "render_ms": getattr(rendered, "render_ms", None),
        "warnings": [*dedupe.notes, *(w for o in outcomes for w in o.warnings)],
        "dropped_scenes": sorted(script.scenes[j].root.id for j in dropped),
        "tokens": token_usage,
        **(extra_report or {}),
    }
    (job_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return ProduceResult(out, report, final_script, outcomes)
