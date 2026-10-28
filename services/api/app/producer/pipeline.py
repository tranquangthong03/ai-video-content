"""Produce a video from an approved script: time it, record each scene, fit the timeline, render.

Estimated speech time decides how long every scene lasts (no TTS yet). A recording that is shorter
than its speech is held on its last frame; a longer one has its dead time cut out (producer/trim.py)
and, only for scrolling/pointing scenes, may play up to 1.15x; if it is still longer the scene
grows. Actions are never sped up. The result is a report with every number behind the timeline.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.browser.auth_detect import LoginRequired
from app.browser.session import BrowserSession
from app.core.brief import cta_domain, load_brief
from app.core.flow_value import value_actions_of_run
from app.core.timing import PAUSE_MS, EstimatedTimer, estimate_captions
from app.llm.json_call import JsonCaller
from app.producer.action_zoom import labels_for, plan_action_zooms
from app.producer.dead_frames import cut_dead, dead_ms
from app.producer.dedupe import MIN_SCENES, swap_scene, used_texts
from app.producer.focus_plan import phrases_from_captions, plan_focus
from app.producer.focus_rules import build_focus_track, enforce_hook_framing
from app.producer.live_clip import live_usable, recording_from_live
from app.producer.motion_qa import run_qa
from app.producer.scorecard import build_scorecard, hook_is_close, proof_from_dict
from app.producer.shots import max_static_ms, plan_shots
from app.producer.steps_coverage import steps_in_clip
from app.producer.text_cards import text_card_stats
from app.producer.trim import shift_actions, shift_logs, shift_time, trim_dead_time
from app.recorder.flow import FlowRecorder
from app.recorder.motion import idle_gaps
from app.recorder.record import RecordResult, record_scene
from app.schemas.generated.flow_run import FlowRun
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
    inventory_snapshots: int = 0  # frame_inventory snapshots taken (items are in inventory_file)
    inventory_file: str | None = None  # produce/inventory/<scene>.json: inventory + action_log
    focus: dict[str, Any] | None = None  # how the focus track came about (see focus_summary)
    focus_file: str | None = None  # produce/focus/<scene>.json: plan, track, metrics
    dead_cut_ms: int = 0  # dead frames (blank, spinner, skeleton) cut out of the clip
    dead_frames_ms: int = 0  # dead frames still in the part of the clip the scene shows
    shots: int = 0  # one per spoken phrase
    punches: int = 0  # punch-ins added where a shot began without a change
    max_static_ms: int | None = None  # longest stretch with nothing changing on screen

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
    inventory: list[dict[str, Any]] = field(default_factory=list)  # frame_inventory snapshots
    action_log: list[dict[str, Any]] = field(
        default_factory=list
    )  # what was done, and to which item
    trimmed_ms: int = 0
    cuts: list[dict[str, int]] = field(default_factory=list)


def save_inventory(work: Path, scene_id: str, plan: "ClipPlan | None") -> str | None:
    """Write a scene's frame_inventory and action log (clip time) next to the produce files."""
    if plan is None or not plan.inventory:
        return None
    path = work / "inventory" / f"{scene_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"inventory": plan.inventory, "action_log": plan.action_log}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path.relative_to(work.parent))


def focus_for_scene(
    work: Path,
    s: Any,
    plan: "ClipPlan",
    captions: list[dict[str, Any]],
    rate: float,
    record: RecordResult,
    caller: JsonCaller | None,
    final_chapter: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    """The scene's focus_track: the planner's plan (when it gave a usable one) through the rules."""
    # the track is worked out on the shown axis (0 = first shown moment of the clip) and moved
    # onto the clip's own axis at the end, where the renderer looks for it
    lead = plan.start_offset_ms + plan.trim_start_ms
    inventory = [{**e, "t_ms": e["t_ms"] - lead} for e in plan.inventory]
    actions = [
        {**a, "t_ms": a["t_ms"] - lead, "end_ms": a["end_ms"] - lead} for a in plan.action_log
    ]
    legacy = [{**f, "t_ms": f["t_ms"] - lead} for f in plan.focus_log]
    duration_ms = plan.content_ms - lead
    phrases = phrases_from_captions(captions, rate)
    planned = None
    if caller is not None:
        planned = plan_focus(
            caller,
            scene_kind=s.type,
            feature_name=getattr(s, "feature", None) or "",
            key_point=s.key_point,
            phrases=phrases,
            actions=actions,
            inventory=inventory,
            duration_ms=duration_ms,
        )
    built = build_focus_track(
        duration_ms=duration_ms,
        clip=(record.width, record.height),
        inventory=inventory,
        action_log=actions,
        phrases=phrases,
        plan=planned.plan if planned else None,
        legacy_focus=legacy,
        # the submit button may be the focus only in the last chapter, once the form was shown
        submit_after_ms=(
            max([a["end_ms"] for a in actions if a["do"] == "type"], default=0.0)
            if final_chapter
            else None
        ),
    )
    hook_reframed = 0
    if s.type == "hook":  # a hook is shot tight or medium on its hero, never establishing
        built.track, hook_reframed = enforce_hook_framing(
            built.track, inventory, (record.width, record.height)
        )
    for entry in built.track:
        entry["t_ms"] += lead
    summary = {
        "planner": "plan" if planned and planned.plan else ("failed" if planned else "off"),
        "planner_attempts": planned.attempts if planned else 0,
        "planner_errors": planned.errors if planned else [],
        "hook_reframed": hook_reframed,
        **built.metrics,
    }
    path = work / "focus" / f"{s.id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "lead_ms": lead,
                "phrases": phrases,
                "plan": planned.plan if planned else None,
                "track": built.track,
                "summary": summary,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return built.track, summary, str(path.relative_to(work.parent))


def shots_for_scene(
    entry: dict[str, Any],
    plan: "ClipPlan",
    rate: float,
    final_ms: int,
    captions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Shots (one per phrase) and punch-ins of a recorded scene, on the scene's own time axis."""
    lead = plan.start_offset_ms + plan.trim_start_ms

    def scene_time(t: float) -> float:
        return (t - lead) / rate if rate else t - lead

    focus_times = [scene_time(f["t_ms"]) for f in entry.get("focus_track", [])]
    action_times = [scene_time(a["t_ms"]) for a in plan.action_log]
    shots, punches = plan_shots(
        captions, final_ms, focus_times=focus_times, action_times=action_times
    )
    return {
        "shots": [{"from_ms": x.from_ms, "to_ms": x.to_ms, "change": x.change} for x in shots],
        "punches": punches,
        "max_static_ms": max_static_ms(final_ms, focus_times, action_times, punches),
    }


def zoom_for_scene(
    s: Any,
    plan: "ClipPlan",
    rate: float,
    final_ms: int,
    record: RecordResult,
    steps: list[Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The Action Zoom shots of a desktop_frame scene, moved onto the clip's own time axis.
    `steps`: the flow steps of the scene's chapter (their notes become the labels)."""
    lead = plan.start_offset_ms + plan.trim_start_ms

    def moved(entries: list[dict[str, Any]], *keys: str) -> list[dict[str, Any]]:
        return [{**e, **{k: e[k] - lead for k in keys if k in e}} for e in entries]

    actions = moved(plan.action_log, "t_ms", "end_ms")
    shots, summary = plan_action_zooms(
        limit_ms=final_ms * rate,
        clip=(record.width or 1280, record.height or 720),
        actions=actions,
        inventory=moved(plan.inventory, "t_ms"),
        focus_log=moved(plan.focus_log, "t_ms"),
        click_log=moved(plan.click_log, "t_ms"),
        activity_ms=[t - lead for t in plan.activity_ms],
        labels=labels_for(steps or [], actions),
    )
    for z in shots:
        for key in ("in_start_ms", "in_end_ms", "out_start_ms", "out_end_ms"):
            z[key] += lead
    return shots, summary


def chapter_order_ok(script: Script, recorder: FlowRecorder | None) -> bool | None:
    """The scenes of a flow video follow its chapters in order (None: not a flow video)."""
    if recorder is None:
        return None
    index = {c.id: n for n, c in enumerate(recorder.run.chapters)}
    seq = [
        index[sc.root.chapter_id]
        for sc in script.scenes
        if getattr(sc.root, "chapter_id", None) in index
    ]
    return seq == sorted(seq)


def short_domain(url: str) -> str:
    """hr.example.com for https://www.hr.example.com/app/x: what a CTA may say out loud."""
    return (urlparse(url).hostname or "").removeprefix("www.")


def measure_motion(job_dir: Path, report: dict[str, Any]) -> dict[str, Any] | None:
    """Motion QA of the finished video; a failure to measure never fails the job."""
    try:
        return run_qa(job_dir, report=report)
    except Exception as e:  # no video to read (a fake renderer), no node, ...
        report["motion_qa_error"] = f"{type(e).__name__}: {str(e)[:120]}"
        return None


def shows_login_page(inventory: list[dict[str, Any]]) -> bool:
    """True when at least 2 of 3 moments of a clip (start, middle, end) are the sign-in page."""
    if not inventory:
        return False
    picks = [inventory[0], inventory[len(inventory) // 2], inventory[-1]]
    if len(inventory) < 3:
        picks = inventory[:3]
    login = sum(1 for snap in picks if snap.get("login_page"))
    return login * 3 >= len(picks) * 2 if len(picks) >= 2 else login == 1


def without_dead_frames(record: RecordResult, lead: int, scene_id: str) -> RecordResult:
    """Blank pages, spinners and skeletons longer than 300 ms are cut out of the clip (a stretch
    before `lead` is hidden anyway). The logs move to the new time axis; a clip that cannot be
    cut keeps its frames and the scene reports them."""
    if record.clip_path is None:
        return record
    try:
        cut = cut_dead(
            record.clip_path, scene_id, lead, record.content_ms, record.inventory,
            (record.width or 1440, record.height or 900),
        )  # fmt: skip
    except Exception as e:  # sampling or cutting failed: the clip as recorded is still usable
        record.warnings.append(f"{scene_id}: không dò được khung hình chết ({type(e).__name__})")
        return record
    if cut is None:
        return record
    _, cuts = cut
    removed = sum(c.removed_ms for c in cuts)
    activity = [shift_time(t, cuts) for t in record.activity_ms]
    record.warnings.append(f"{scene_id}: đã cắt {removed} ms khung hình chết")
    return replace(
        record,
        content_ms=record.content_ms - removed,
        click_log=shift_logs(record.click_log, cuts),
        focus_log=shift_logs(record.focus_log, cuts),
        inventory=shift_logs(record.inventory, cuts),
        action_log=shift_actions(record.action_log, cuts),
        activity_ms=activity,
        idle_gaps_ms=idle_gaps(activity, record.start_offset_ms, record.content_ms - removed),
        dead_cut_ms=record.dead_cut_ms + removed,
    )


def plan_clip(record: RecordResult, visual: Any, speech_ms: int, scene_id: str) -> ClipPlan:
    """Hide the loading phase and hidden setup; a clip longer than the speech loses dead time."""
    lead = record.start_offset_ms
    if visual.setup and not visual.show_setup:
        lead = record.setup_end_ms
    record = without_dead_frames(record, lead, scene_id)
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
        [e for e in record.inventory if e["t_ms"] >= lead],
        [e for e in record.action_log if e["t_ms"] >= lead],
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
            inventory=record.inventory,
            action_log=record.action_log,
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
        cut.inventory,
        cut.action_log,
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


MAX_LOGIN_RETRIES = 2  # sign-ins asked for one scene before giving up


def flow_report(recorder: FlowRecorder, session: BrowserSession) -> dict[str, Any]:
    """How the one-go recording of a core flow went (goes into report.json)."""
    rec = recorder.recording
    return {
        "flow_id": recorder.run.flow_id,
        "steps": len(recorder.run.steps),
        "replayed": sum(1 for m in rec.marks if m.ok) if rec else 0,
        "replay_failed_at": rec.failed_at if rec else None,
        "skipped_steps": [m.i for m in rec.marks if m.skipped] if rec else [],
        **steps_in_clip(
            recorder.run, [m.i for m in rec.marks if m.ok and not m.skipped] if rec else []
        ),
        "hero": recorder.hero,
        "value_actions": value_actions_of_run(recorder.run),
        "clip_ms": rec.content_ms if rec else 0,
        "clip_source": rec.source if rec else None,
        "llm_wait_cut_ms": rec.llm_wait_cut_ms if rec else 0,
        "retry_segments_cut": rec.retry_cut if rec else 0,
        "rejected_segments_cut": rec.rejected_cut if rec else 0,
        "notes": recorder.notes,
        "write_requests": list(session.guard.write_log),
    }


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
    focus_caller: JsonCaller | None = None,
    on_login: Callable[[LoginRequired], Path] | None = None,
    flow_film: str = "auto",
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
    zoom_info: dict[str, dict[str, Any]] = {}  # desktop_frame: zoom shots per scene (summary)
    data = script.model_dump()
    started = time.monotonic()
    viewport = {"width": script.capture.width, "height": script.capture.height}
    dedupe = Dedupe(load_page_index(job_dir / "explore"))
    flow_recorder: FlowRecorder | None = None
    approved_flow = job_dir / "flow" / "flow_approved.json"
    if script.flow_id and recorder is record_scene and approved_flow.is_file():
        # a core flow is filmed in one go on one context and cut into its chapters
        flow_run = FlowRun.model_validate_json(approved_flow.read_text(encoding="utf-8"))
        live_recording = None
        film_note = None
        if flow_film != "replay":  # the clip made while the agent ran, unless told to replay
            if live_usable(job_dir, flow_run):
                live_recording = recording_from_live(job_dir, flow_run)
            elif flow_film == "live":
                film_note = "không có clip quay trực tiếp dùng được: quay lại bằng cách phát lại"
        flow_recorder = FlowRecorder(flow_run, job_dir, live=live_recording)
        if film_note:
            flow_recorder.notes.append(film_note)
        recorder = flow_recorder
    elif isinstance(recorder, FlowRecorder):
        flow_recorder = recorder
    dropped: set[int] = set()
    hook_close: bool | None = None  # is the camera close on the hook's first two seconds
    demos = [x.root.id for x in script.scenes if x.root.type == "feature_demo"]
    final_demo = demos[-1] if demos else None  # the last chapter: it may end on the submit button
    for i, scene in enumerate(script.scenes):
        s = scene.root
        timing = speech[s.id]
        speech_ms = timing.duration_ms
        say(f"[record] scene {i + 1}/{len(script.scenes)} {s.id} ({s.type}) ...")
        for attempt in range(MAX_LOGIN_RETRIES + 1):
            try:
                if flow_recorder is not None:  # chapters repeat each other's pages by design
                    recorded = (
                        scene,
                        recorder(
                            session, scene, work, speech_ms, root_url=url,
                            highlight_color=color, viewport=viewport,
                        ),
                    )  # fmt: skip
                else:
                    recorded = record_unique(
                        recorder, session, scene, work, speech_ms, url, color, viewport, dedupe,
                        can_drop=len(script.scenes) - len(dropped) > MIN_SCENES,
                    )  # fmt: skip
                if recorded is not None and shows_login_page(recorded[1].inventory):
                    # quality gate: a clip of the sign-in page is never rendered
                    raise LoginRequired("", "login_page", target_url=url, scene_id=scene.root.id)
                break
            except LoginRequired as e:  # the session ran out: sign in again, redo this scene
                e.scene_id = e.scene_id or scene.root.id
                if on_login is None or attempt == MAX_LOGIN_RETRIES:
                    raise
                session.storage_state = on_login(e)
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
            if record.pair_images:
                entry["before_url"], entry["after_url"] = (str(p) for p in record.pair_images)
            if record.focus_log:
                entry["focus_log"] = record.focus_log
            if (
                s.type == "cta" and not record.focus_log
            ):  # no button to point at: drift to the header
                bar = {"x": 0, "y": 0, "w": viewport["width"], "h": 140}
                entry["focus_log"] = [{"t_ms": 0, "bbox": bar, "kind": "section", "hold_ms": 0}]
        focus, focus_file = None, None
        if plan is not None and plan.clip is not None and plan.inventory:
            track, focus, focus_file = focus_for_scene(
                work, s, plan, captions, rate, record, focus_caller,
                final_chapter=bool(final_demo) and s.id == final_demo,
            )  # fmt: skip
            entry["focus_track"] = track
        shots_info: dict[str, Any] = {}
        if plan is not None and plan.clip is not None:
            shots_info = shots_for_scene(entry, plan, rate, final_ms, captions)
            entry["shots"], entry["punches"] = shots_info["shots"], shots_info["punches"]
            if script.template == "desktop_frame":
                chapter = (
                    next((c for c in flow_recorder.run.chapters if c.id == s.chapter_id), None)
                    if flow_recorder is not None and getattr(s, "chapter_id", None)
                    else None
                )
                chapter_steps = (
                    [x for x in flow_recorder.run.steps if x.i in chapter.step_ids]
                    if flow_recorder is not None and chapter is not None
                    else []
                )
                entry["zoom_shots"], zoom_summary = zoom_for_scene(
                    s, plan, rate, final_ms, record, chapter_steps
                )
                entry["punches"] = []  # the still camera has no punch-ins
                zoom_info[s.id] = zoom_summary
            if s.type == "hook":
                hook_close = hook_is_close(
                    entry.get("focus_track", []), plan.start_offset_ms + plan.trim_start_ms, rate
                )
        dead_left = (
            dead_ms(plan.clip, plan.start_offset_ms + plan.trim_start_ms)
            if plan is not None and plan.clip is not None
            else 0
        )
        if record.continues:
            entry["same_page"] = True
        if s.type == "cta":
            entry["cta_domain"] = cta_domain(load_brief(job_dir)) or short_domain(url)
        assets[s.id] = entry
        inventory_file = save_inventory(work, s.id, plan)
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
                inventory_snapshots=len(plan.inventory) if plan else 0,
                inventory_file=inventory_file,
                focus=focus,
                focus_file=focus_file,
                dead_cut_ms=record.dead_cut_ms,
                dead_frames_ms=dead_left,
                shots=len(shots_info.get("shots", [])),
                punches=len(shots_info.get("punches", [])),
                max_static_ms=shots_info.get("max_static_ms"),
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
        "dead_frames_ms": sum(o.dead_frames_ms for o in outcomes),
        "dead_frames_cut_ms": sum(o.dead_cut_ms for o in outcomes),
        "max_static_shot_s": round(
            max((o.max_static_ms or 0 for o in outcomes), default=0) / 1000, 2
        ),
        "punch_ins": sum(o.punches for o in outcomes),
        "template": final_script.template,
        "zoom_shots": zoom_info,
        "text_cards": text_card_stats([(o.kind, o.final_ms) for o in outcomes]),
        "features": features,
        "phases_s": phases,
        "render_ms": getattr(rendered, "render_ms", None),
        "warnings": [*dedupe.notes, *(w for o in outcomes for w in o.warnings)],
        "dropped_scenes": sorted(script.scenes[j].root.id for j in dropped),
        "chapter_order_ok": chapter_order_ok(final_script, flow_recorder),
        "dropped_chapter_scenes": sorted(
            script.scenes[j].root.id
            for j in dropped
            if getattr(script.scenes[j].root, "chapter_id", None)
        ),
        "tokens": token_usage,
        "flow": flow_report(flow_recorder, session) if flow_recorder else None,
        **(extra_report or {}),
    }
    hook = next((x.root for x in final_script.scenes if x.root.type == "hook"), None)
    qa = measure_motion(job_dir, report)
    report["motion_qa"] = qa
    report["scorecard"] = build_scorecard(
        report,
        hook_text=hook.on_screen_text if hook else None,
        hook_close=hook_close,
        said=" ".join(
            t for x in final_script.scenes for t in (x.root.voiceover, x.root.on_screen_text) if t
        ),
        proof=proof_from_dict(report.get("proof_bank")),
        critic=report.get("critic"),
        motion=qa,
    )
    (job_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return ProduceResult(out, report, final_script, outcomes)
