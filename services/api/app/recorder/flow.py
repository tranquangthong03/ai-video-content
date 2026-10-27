"""Filming a core flow in one go.

record_flow() replays the approved run's steps on ONE browser context (so what chapter 1 filled in
is still there in chapter 2), at the usual slow pace, and marks when each step started and ended.
FlowRecorder then cuts that long clip into one RecordResult per chapter (clip, click / focus /
action logs and frame_inventory, all re-timed), so the producer treats a chapter like any other
recorded scene: dead-time trimming, the focus planner, the quality gate.

A step that can no longer be done (it is retried once by its visible text) ends the replay. The
chapters after it, and the part of the chapter it broke, fall back to the storyboard pictures
taken by the agent; the film is never started over.
"""

import random
import shutil
import subprocess
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.browser.auth_detect import LoginRequired
from app.browser.form_actions import SUBMIT_NAME
from app.browser.guard import WritesNotAllowed
from app.browser.page_utils import dismiss_cookie_banner
from app.browser.session import BrowserSession
from app.core.hero import before_after_pair, choose_hero, hero_item, hero_window
from app.recorder import motion, sync
from app.recorder.record import (
    CAPTURE,
    INIT_JS,
    TAIL_MS,
    RecordResult,
    _Recorder,
    record_scene,
    to_mp4,
)
from app.schemas.generated.action import BrowserAction
from app.schemas.generated.flow_run import FlowRun
from app.schemas.generated.locator import LocatorSpec
from app.schemas.generated.scene import Scene

HERO_MS = 2000  # the hook shows this much of the flow around its most telling moment
# A click whose target is gone is often the agent's second click on something that was still
# loading: the replay skips up to MAX_SKIPS of them and goes on. Typing, choosing and dates are
# never skipped (the steps after them depend on what they entered).
SKIPPABLE = ("click", "navigate", "hover", "highlight", "scroll", "check")
MAX_SKIPS = 2


@dataclass
class StepMark:
    i: int
    chapter_id: str | None
    start_ms: int
    end_ms: int
    ok: bool
    warnings: list[str] = field(default_factory=list)
    skipped: bool = False  # failed, but the film goes on without it


@dataclass
class FlowRecording:
    clip_path: Path | None
    start_offset_ms: int
    content_ms: int
    width: int
    height: int
    marks: list[StepMark]
    click_log: list[dict[str, Any]]
    focus_log: list[dict[str, Any]]
    inventory: list[dict[str, Any]]
    action_log: list[dict[str, Any]]
    activity_ms: list[float]
    warnings: list[str]
    sync_offset_ms: int = 0  # video clock = log clock + this (measured with the sync pulse)
    pulse_at_ms: int = 0  # log time at which the pulse was shown
    source: str = "replay"  # live: made while the agent ran; replay: the steps done again
    llm_wait_cut_ms: int = 0  # (live) waiting for the model that was cut out
    retry_cut: int = 0  # (live) failed tries that were corrected and cut out
    rejected_cut: int = 0  # (live) refused or made-up actions that were cut out

    @property
    def failed_at(self) -> int | None:
        return next((m.i for m in self.marks if not m.ok and not m.skipped), None)


# --- filming -------------------------------------------------------------------------------------


def _action_of(step: Any) -> BrowserAction:
    data = step.action.model_dump(exclude_none=True)
    if step.locator is not None:
        data["locator"] = step.locator.model_dump(exclude_none=True)
    return BrowserAction.model_validate(data)


def _replay_step(rec: _Recorder, step: Any) -> bool:
    """Do one step; a miss is retried once looking the element up by its visible text."""
    action = _action_of(step)
    is_submit = (
        rec.submit_ok and action.do == "click" and bool(SUBMIT_NAME.search(step.target_text or ""))
    )

    def attempt(a: BrowserAction) -> bool:
        before = rec.failed
        try:
            window = rec.session.guard.allow_writes() if is_submit else nullcontext()
            with window:
                rec.step(a, step.i, "action")
        except WritesNotAllowed as e:
            rec.failed += 1
            rec.warnings.append(f"action[{step.i}] không được ghi dữ liệu ({e})")
        return rec.failed == before

    mark = len(rec.warnings)
    if attempt(action):
        return True
    text = step.target_text
    if text and action.locator is not None and action.do not in ("scroll", "wait", "goto"):
        rec.failed -= 1  # the first miss is not a failure yet
        del rec.warnings[mark:]
        spec = LocatorSpec(role=action.locator.role, name=text, text=text)
        return attempt(action.model_copy(update={"locator": spec}))
    return False


def record_flow(
    session: BrowserSession,
    run: FlowRun,
    out_dir: Path,
    *,
    root_url: str,
    viewport: dict[str, int] | None = None,
    highlight_color: str = "#756eeb",
    seed: int | None = None,
) -> FlowRecording:
    """Replay the whole run on one context into out_dir/flow.mp4. Never raises for a failing step;
    LoginRequired (the session ran out) passes up."""
    viewport = viewport or CAPTURE
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw" / "flow"
    raw_dir.mkdir(parents=True, exist_ok=True)
    start_url = next(
        (s.action.url for s in run.steps if s.action.do == "goto" and s.action.url), root_url
    )
    context = session.new_context(record_video_dir=raw_dir, viewport=viewport)
    context.add_init_script(INIT_JS)
    marks: list[StepMark] = []
    try:
        page = context.new_page()
        rec = _Recorder(
            session, page, root_url, out_dir, "flow", color=highlight_color, policy="strict",
            rng=random.Random(seed if seed is not None else run.flow_id), viewport=viewport,
        )  # fmt: skip
        rec.submit_ok = run.submit_policy == "allow"
        rec.hover_submit = True  # the climax of a stopped flow points at the submit button
        page.mouse.move(*rec.home)
        pulse_at = sync.emit_pulse(page, rec.now)  # in the loading phase, which is cut off
        try:
            response = page.goto(start_url, wait_until="domcontentloaded")
            rec.settle()
            dismiss_cookie_banner(page)
            rec.settle()
            rec.check_login(start_url, response.status if response else None)
        except LoginRequired:
            raise
        except Exception as e:
            rec.warnings.append(f"không mở được {start_url}: {type(e).__name__}")
        shown_from = pulse_at + sync.PULSE_MS + sync.PULSE_SETTLE_MS
        if rec.now() < shown_from:  # the shown part never starts before the pulse is over
            page.wait_for_timeout(shown_from - rec.now())
        start_offset = rec.now()
        skips = 0
        for step in run.steps:
            if step.action.do == "goto":
                continue  # the page load above
            started, mark = rec.now(), len(rec.warnings)
            ok = _replay_step(rec, step)
            refused = any("bị chặn" in w or "không được ghi" in w for w in rec.warnings[mark:])
            # a step the safety layer refused is never "skipped past": the film stops there
            skip = not ok and not refused and step.action.do in SKIPPABLE and skips < MAX_SKIPS
            marks.append(
                StepMark(step.i, step.chapter_id, started, rec.now(), ok, rec.warnings[mark:], skip)
            )
            if skip:
                skips += 1
                rec.warnings.append(f"bước {step.i} bị bỏ qua (không còn phần tử), quay tiếp")
                continue
            if not ok:
                break
        page.wait_for_timeout(TAIL_MS)
        rec.collect_activity()
        content_ms = rec.now()
        video = page.video
    finally:
        context.close()
    clip = None
    if video is not None:
        clip = out_dir / "flow.mp4"
        to_mp4(Path(video.path()), clip)
    activity = [t - rec.t0 * 1000 for t in rec.activity] + [e["t_ms"] for e in rec.log] + rec.marks
    offset = sync.measure_offset(clip, pulse_at) if clip is not None else None
    if offset is None:
        rec.warnings.append("không đo được độ lệch đồng hồ log/hình (xung đồng bộ), dùng 0")
    return FlowRecording(
        clip, start_offset, content_ms, viewport["width"], viewport["height"], marks,
        rec.log, rec.focus_log, rec.inventory, rec.action_log, activity, rec.warnings,
        sync_offset_ms=offset or 0,
        pulse_at_ms=pulse_at,
    )  # fmt: skip


# --- cutting -------------------------------------------------------------------------------------


def grab_still(src: Path, dst: Path, t_ms: int, offset_ms: int = 0) -> None:
    """One frame at flow time `t_ms` (offset_ms turns log time into video time) as a PNG."""
    at = max(0, t_ms + offset_ms)
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{at / 1000:.3f}", "-i", str(src),
         "-frames:v", "1", str(dst)],
        capture_output=True, text=True,
    )  # fmt: skip
    if result.returncode != 0 or not dst.is_file():
        raise RuntimeError(f"ffmpeg still failed: {result.stderr[:200]}")


def cut_clip(src: Path, dst: Path, start_ms: int, end_ms: int, offset_ms: int = 0) -> None:
    """Frame-accurate copy of [start, end] in LOG time (re-encoded the way the recorder encodes);
    offset_ms turns log time into video time (the sync pulse measured it)."""
    start_ms, end_ms = max(0, start_ms + offset_ms), max(1, end_ms + offset_ms)
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-ss", f"{start_ms / 1000:.3f}", "-i", str(src),
            "-t", f"{(end_ms - start_ms) / 1000:.3f}", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30", "-an", str(dst),
        ],
        capture_output=True, text=True,
    )  # fmt: skip
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[:300]}")


def _shift(
    items: list[dict[str, Any]], a: int, b: int, keys: tuple[str, ...]
) -> list[dict[str, Any]]:
    """Entries that start inside [a, b), re-timed to the window."""
    out = []
    for e in items:
        if a <= e["t_ms"] < b:
            moved = dict(e)
            for k in keys:
                if k in moved:
                    moved[k] = max(0, min(moved[k], b) - a) if k == "end_ms" else moved[k] - a
            out.append(moved)
    return out


def window_result(rec: FlowRecording, clip: Path, a: int, b: int, *, first: bool) -> RecordResult:
    """The RecordResult of the stretch [a, b) of the flow clip."""
    inventory = _shift(rec.inventory, a, b, ("t_ms",))
    before = [e for e in rec.inventory if e["t_ms"] < a]
    if before and (not inventory or inventory[0]["t_ms"] > 300):
        inventory.insert(0, {**before[-1], "t_ms": 0})  # what was on screen when the window opened
    activity = [t - a for t in rec.activity_ms if a <= t < b]
    offset = rec.start_offset_ms if first else 0
    return RecordResult(
        kind="recording",
        clip_path=clip,
        start_offset_ms=offset,
        setup_end_ms=offset,
        click_log=_shift(rec.click_log, a, b, ("t_ms",)),
        focus_log=_shift(rec.focus_log, a, b, ("t_ms",)),
        inventory=inventory,
        action_log=_shift(rec.action_log, a, b, ("t_ms", "end_ms")),
        width=rec.width,
        height=rec.height,
        content_ms=b - a,
        idle_gaps_ms=motion.idle_gaps(activity, offset, b - a),
        activity_ms=activity,
    )


# --- the recorder the producer uses --------------------------------------------------------------


def pick_hero(run: FlowRun) -> int | None:
    """The step the hook is built around: the highlighted submit button (the form is complete),
    else the last step (the result)."""
    for step in reversed(run.steps):
        if step.action.do == "highlight":
            return step.i
    return run.steps[-1].i if len(run.steps) > 1 else None


class FlowRecorder:
    """A drop-in for record_scene: chapter scenes get their slice of the one flow recording."""

    def __init__(self, run: FlowRun, job_dir: Path, live: FlowRecording | None = None) -> None:
        self.run = run
        self.job_dir = job_dir
        self.live = live  # the film made while the agent ran: used instead of a replay
        self.recording: FlowRecording | None = None
        self.notes: list[str] = []
        self.hero: dict[str, Any] | None = None  # the hero frame the hook was cut around
        self._windows: dict[str, tuple[int, int, bool]] = {}

    def __call__(
        self,
        session: BrowserSession,
        scene: Scene,
        out_dir: Path,
        speech_ms: int,
        **kw: Any,
    ) -> RecordResult:
        s = scene.root
        chapter = getattr(s, "chapter_id", None)
        if chapter is None and s.type not in ("hook", "cta", "before_after"):
            return record_scene(session, scene, out_dir, speech_ms, **kw)
        rec = self._record(session, out_dir, kw)
        if s.type == "hook":
            result = self._hook(rec, out_dir, s.id)
            return result or record_scene(session, scene, out_dir, speech_ms, **kw)
        if chapter is None:  # the closing CTA and the before/after card use the flow's own frames
            result = (
                self._cta(rec, out_dir, s.id) if s.type == "cta" else self._pair(rec, out_dir, s.id)
            )
            return result or record_scene(session, scene, out_dir, speech_ms, **kw)
        assert chapter is not None
        result = self._chapter(rec, chapter, out_dir, s.id)
        result.continues = self.continues(chapter)
        return result

    # --- internals ---------------------------------------------------------------------------

    def _record(self, session: BrowserSession, out_dir: Path, kw: dict[str, Any]) -> FlowRecording:
        if self.recording is None and self.live is not None:
            self.recording = self.live
            self.notes += self.live.warnings
            self._plan_windows(self.live)
        if self.recording is None:
            self.recording = record_flow(
                session, self.run, out_dir, root_url=kw["root_url"], viewport=kw.get("viewport"),
                highlight_color=kw.get("highlight_color", "#756eeb"),
            )  # fmt: skip
            self.notes += self.recording.warnings
            self._plan_windows(self.recording)
        return self.recording

    def _plan_windows(self, rec: FlowRecording) -> None:
        """Chapter windows follow one another without gaps; the last one runs to the clip's end."""
        done = {m.i: m for m in rec.marks if m.ok}
        previous_end = 0
        chapters = self.run.chapters
        for n, chapter in enumerate(chapters):
            marks = [done[i] for i in chapter.step_ids if i in done]
            if not marks:
                continue
            end = max(m.end_ms for m in marks)
            if n == len(chapters) - 1 and len(marks) == len(chapter.step_ids):
                end = rec.content_ms
            self._windows[chapter.id] = (previous_end, end, n == 0)
            previous_end = end

    def _storyboard(self, step_i: int | None, out_dir: Path, scene_id: str) -> Path | None:
        step = next((s for s in self.run.steps if s.i == step_i), None)
        if step is None or not step.screenshot:
            return None
        src = self.job_dir / step.screenshot
        if not src.is_file():
            return None
        dst = out_dir / f"{scene_id}{src.suffix}"
        shutil.copyfile(src, dst)
        return dst

    def _chapter(
        self, rec: FlowRecording, chapter_id: str, out_dir: Path, scene_id: str
    ) -> RecordResult:
        chapter = next(c for c in self.run.chapters if c.id == chapter_id)
        window = self._windows.get(chapter_id)
        broke = rec.failed_at is not None and rec.failed_at in chapter.step_ids
        if window is not None and rec.clip_path is not None:
            a, b, first = window
            clip = out_dir / f"{scene_id}.mp4"
            cut_clip(rec.clip_path, clip, a, b, rec.sync_offset_ms)
            result = window_result(rec, clip, a, b, first=first)
            result.steps_ok = sum(1 for m in rec.marks if m.ok and m.i in chapter.step_ids)
            if broke:
                result.warnings.append(
                    f"luồng dừng ở bước {rec.failed_at}: phần còn lại của chương không quay được"
                )
            result.warnings += [w for m in rec.marks if m.i in chapter.step_ids for w in m.warnings]
            return result
        image = self._storyboard(
            chapter.step_ids[-1] if chapter.step_ids else None, out_dir, scene_id
        )
        at = rec.failed_at or "?"
        note = f"chương {chapter_id} không quay được (bước {at}): dùng ảnh storyboard"
        self.notes.append(note)
        if image is None:
            return RecordResult(
                kind="fallback_screenshot", warnings=[note, "không có ảnh storyboard"]
            )
        return RecordResult(kind="fallback_screenshot", image_path=image, warnings=[note])

    def continues(self, chapter_id: str) -> bool:
        """Does this chapter start on the page the last one ended on? Then its camera picks up
        where the previous one stopped instead of opening on the whole page again."""
        chapters = self.run.chapters
        n = next((i for i, c in enumerate(chapters) if c.id == chapter_id), 0)
        if n == 0:
            return False
        steps = {s.i: s for s in self.run.steps}
        before, now = chapters[n - 1].step_ids, chapters[n].step_ids
        if not before or not now or before[-1] not in steps or now[0] not in steps:
            return False
        left, start = steps[before[-1]].url_after, steps[now[0]].url_before
        return bool(left) and left == start

    def _still(self, rec: FlowRecording, out_dir: Path, name: str, t_ms: int) -> Path | None:
        """One frame of the flow clip at flow time `t_ms`."""
        if rec.clip_path is None:
            return None
        dst = out_dir / f"{name}.png"
        try:
            grab_still(rec.clip_path, dst, t_ms, rec.sync_offset_ms)
        except RuntimeError as e:
            self.notes.append(f"{name}: không lấy được khung hình ({str(e)[:60]})")
            return None
        return dst

    def _pair(self, rec: FlowRecording, out_dir: Path, scene_id: str) -> RecordResult | None:
        """Two real frames: the flow's first and its hero frame; None without a good pair."""
        hero = choose_hero(rec.inventory, from_ms=rec.start_offset_ms)
        pair = hero and before_after_pair(rec.inventory, hero.t_ms, from_ms=rec.start_offset_ms)
        if not pair:
            self.notes.append("trước/sau: không có cặp khung phù hợp, quay lại bằng ảnh trang")
            return None
        before = self._still(rec, out_dir, f"{scene_id}_before", pair[0])
        after = self._still(rec, out_dir, f"{scene_id}_after", pair[1])
        if before is None or after is None:
            return None
        return RecordResult(
            kind="screenshot", image_path=after, pair_images=(before, after),
            width=rec.width, height=rec.height,
        )  # fmt: skip

    def _cta(self, rec: FlowRecording, out_dir: Path, scene_id: str) -> RecordResult | None:
        """The hero frame as the closing background, with a gentle zoom toward its best item."""
        hero = choose_hero(rec.inventory, from_ms=rec.start_offset_ms)
        if hero is None:
            return None
        image = self._still(rec, out_dir, scene_id, hero.t_ms)
        if image is None:
            return None
        snap = next((s for s in rec.inventory if int(s["t_ms"]) == hero.t_ms), None)
        item = hero_item(snap["items"], (rec.width, rec.height)) if snap else None
        focus = (
            [{"t_ms": 0, "bbox": dict(item["bbox"]), "kind": "section", "hold_ms": 0}]
            if item
            else []
        )
        return RecordResult(
            kind="screenshot", image_path=image, focus_log=focus, width=rec.width, height=rec.height
        )

    def _hook(self, rec: FlowRecording, out_dir: Path, scene_id: str) -> RecordResult | None:
        """1.5-2.5 s around the hero frame (chosen by code from the frame inventory), else around
        the hero step, else its storyboard picture."""
        frame = choose_hero(rec.inventory, from_ms=rec.start_offset_ms)
        if frame is not None and rec.clip_path is not None:
            a, b = hero_window(frame.t_ms, rec.content_ms)
            clip = out_dir / f"{scene_id}.mp4"
            cut_clip(rec.clip_path, clip, a, b, rec.sync_offset_ms)
            self.hero = {"t_ms": frame.t_ms, "from_ms": a, "to_ms": b, "score": frame.score}
            return window_result(rec, clip, a, b, first=False)
        hero = pick_hero(self.run)
        mark = next((m for m in rec.marks if m.i == hero and m.ok), None)
        if mark is not None and rec.clip_path is not None:
            highlight = next((s for s in self.run.steps if s.i == hero), None)
            if highlight is not None and highlight.action.do == "highlight":
                a = max(0, mark.start_ms - 300)  # just before the button is outlined
                b = min(mark.end_ms, a + HERO_MS)
            else:  # a result on screen: its last moments
                b = mark.end_ms
                a = max(0, b - HERO_MS)
            clip = out_dir / f"{scene_id}.mp4"
            cut_clip(rec.clip_path, clip, a, b, rec.sync_offset_ms)
            return window_result(rec, clip, a, b, first=False)
        image = self._storyboard(hero, out_dir, scene_id)
        if image is not None:
            self.notes.append("hook: dùng ảnh storyboard của khoảnh khắc chính")
            return RecordResult(kind="screenshot", image_path=image)
        return None
