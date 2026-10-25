"""The Flow Agent: one browser session, one flow. Each round it looks at the page (text and, when
the role may, a screenshot), asks the model for exactly one action, does it through ActionRunner and
records a replayable step (locator, url, note, screenshot). It stops at the goal, before the
submit button (policy "stop"), when it is stuck, or at the limits.

The result is a FlowRun saved to <job_dir>/flow/flow_run.json; successful runs are cached by
(start url, goal, steps, policy, notes) so a rerun costs no LLM calls.
"""

import hashlib
import json
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import Page
from pydantic import BaseModel, Field

from app.browser.auth_detect import LoginRequired, detect_login
from app.browser.form_actions import ActionFailed
from app.browser.locate import Unsafe, resolve
from app.browser.page_utils import dismiss_cookie_banner, wait_for_settle
from app.browser.session import BrowserSession
from app.core.usage import BudgetExceeded
from app.flows.actions import ActionRunner, FlowAction, StepResult, is_submit_target
from app.flows.chapters import chapter_ids, group_chapters
from app.flows.page_state import PageState, capture_state, format_elements, format_messages
from app.llm.json_call import JsonCaller, LLMCallError, VisionUnavailable
from app.llm.prompts import render
from app.schemas.generated.core_flow import CoreFlow
from app.schemas.generated.flow_run import FlowRun

ROLE = "flow_agent"
FLOW_DIR = "flow"
RUN_FILE = "flow_run.json"
HISTORY_LINES = 14
REPEAT_WARN, REPEAT_STOP = 2, 3
STEP_MS = 2500  # a step is about this long on screen (before the hold)


@dataclass(frozen=True)
class Limits:
    max_actions: int = 15
    max_llm_calls: int = 20
    timeout_s: float = 360.0


class AgentAnswer(BaseModel):
    action: FlowAction
    chapter: str = ""
    note: str = ""
    reason: str = ""
    sample_data_update: dict[str, Any] = Field(default_factory=dict)


def signature(state: PageState) -> str:
    """A fingerprint of what the page shows; unchanged after an action = the action did nothing."""
    parts = [state.url, state.heading, "|".join(state.messages)]
    parts += [f"{e.role}:{e.name}={e.value}" for e in state.elements]
    return hashlib.sha1("\n".join(parts).encode()).hexdigest()


def cache_key(flow: CoreFlow, policy: str, notes: str) -> str:
    raw = "\0".join([flow.start_url, flow.goal, "|".join(flow.expected_steps), policy, notes])
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


@dataclass
class _Step:
    action: dict[str, Any]
    locator: dict[str, Any] | None
    target_text: str
    value: str | None
    url_before: str
    url_after: str
    note: str
    chapter: str


@dataclass
class _Run:
    steps: list[_Step] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sample_data: dict[str, Any] = field(default_factory=dict)
    history: list[str] = field(default_factory=list)
    unchanged: dict[str, int] = field(default_factory=dict)
    invented_refs: int = 0
    repeat_warnings: int = 0
    status: str = "partial"
    stop_name: str | None = None


class FlowAgent:
    def __init__(
        self,
        session: BrowserSession,
        caller: JsonCaller,
        flow: CoreFlow,
        job_dir: Path,
        *,
        submit_policy: str = "stop",
        user_notes: str = "",
        authenticated: bool = False,
        viewport: dict[str, int] | None = None,
        use_images: bool | None = None,
        limits: Limits | None = None,
        use_cache: bool | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = session
        self.caller = caller
        self.flow = flow
        self.job_dir = job_dir
        self.policy = submit_policy
        self.notes = user_notes.strip()
        self.authenticated = authenticated
        self.viewport = viewport
        self.images = caller.can_see_images if use_images is None else use_images
        self.limits = limits or Limits()
        self.use_cache = caller.cache_enabled if use_cache is None else use_cache
        self.clock = clock
        self.images_sent = False
        self._calls0 = 0
        self.flow_dir = job_dir / FLOW_DIR

    # --- entry point -----------------------------------------------------------------------

    def run(self) -> FlowRun:
        cached = self._from_cache()
        if cached is not None:
            return cached
        started = self.clock()
        before = dict(self.caller.tracker.steps.get(ROLE, {}))
        self._calls0 = before.get("calls", 0)
        run = _Run()
        context = self.session.new_context(viewport=self.viewport)
        try:
            page = context.new_page()
            self._open(page, run)
            if run.status != "failed":
                self._loop(page, run, started)
        finally:
            context.close()
        flow_run = self._finish(run, started, before)
        self._save(flow_run)
        return flow_run

    # --- the loop --------------------------------------------------------------------------

    def _open(self, page: Page, run: _Run) -> None:
        run.status = "partial"
        try:
            response = page.goto(self.flow.start_url, wait_until="domcontentloaded")
            wait_for_settle(page)
            dismiss_cookie_banner(page)
        except Exception as e:
            run.status = "failed"
            run.warnings.append(f"Không mở được trang bắt đầu: {str(e)[:160]}")
            return
        self._check_login(page, response.status if response else None)

    def _check_login(self, page: Page, status: int | None) -> None:
        if self.authenticated:
            signal = detect_login(page, self.flow.start_url, status)
            if signal is not None:
                raise LoginRequired(signal.login_url, "session_expired", target_url=page.url)

    def _loop(self, page: Page, run: _Run, started: float) -> None:
        runner = ActionRunner(
            page,
            self.flow.start_url,
            allow_submit=self.policy == "allow",
            guard=self.session.guard,
        )
        pending_key: str | None = None
        pending_sig = ""
        shot = self._shot(page, run, 1)
        run.steps.append(self._goto_step(page))
        while True:
            state = capture_state(page)
            sig = signature(state)
            if pending_key is not None and sig == pending_sig:
                run.unchanged[pending_key] = run.unchanged.get(pending_key, 0) + 1
                if run.unchanged[pending_key] >= REPEAT_STOP:
                    run.warnings.append(
                        f"Dừng: «{pending_key}» lặp {REPEAT_STOP} lần mà trang không đổi."
                    )
                    return
            pending_key = None
            stop = self._limit_reached(run, started)
            if stop:
                run.warnings.append(stop)
                return
            answer = self._ask(state, shot, run)
            if answer is None:
                return
            action = answer.action
            run.sample_data.update(answer.sample_data_update)
            if action.do in ("finish", "give_up"):
                run.status = "reached_goal" if action.do == "finish" else "partial"
                if action.do == "give_up":
                    run.warnings.append(f"Agent bỏ cuộc: {action.reason or answer.reason or '?'}")
                return
            if action.do == "stop_before_submit":
                if self._stop_before_submit(page, state, action, answer, run):
                    return
                pending_key, pending_sig = f"stop:{action.ref}", sig
                continue
            name = (
                state.by_ref[action.ref].name if action.ref in state.by_ref else (action.ref or "")
            )
            key = f"{action.do}:{name}"
            pending_key, pending_sig = key, sig
            try:
                result = runner.run(state, action)
            except ActionFailed as e:
                if "không có trong danh sách" in str(e):
                    run.invented_refs += 1
                self._failed(run, action, name, str(e))
                continue
            except Unsafe as e:
                self._failed(run, action, name, f"bị chặn vì an toàn ({e})")
                continue
            except LoginRequired:
                raise
            except Exception as e:  # a page that blew up under the action: report it, keep going
                self._failed(run, action, name, f"lỗi trình duyệt: {str(e).splitlines()[0][:120]}")
                continue
            self._check_login(page, None)
            shot = self._shot(page, run, len(run.steps) + 1)
            run.steps.append(self._step(result, answer, action))
            run.history.append(self._history_line(len(run.steps), result))
            if len([s for s in run.steps if s.action["do"] != "goto"]) >= self.limits.max_actions:
                run.warnings.append(f"Dừng: đã đủ {self.limits.max_actions} hành động.")
                return

    def _limit_reached(self, run: _Run, started: float) -> str | None:
        if self.clock() - started > self.limits.timeout_s:
            return f"Dừng: quá {int(self.limits.timeout_s // 60)} phút."
        calls = self.caller.tracker.steps.get(ROLE, {}).get("calls", 0)
        if calls - self._calls0 >= self.limits.max_llm_calls:
            return f"Dừng: đã dùng {self.limits.max_llm_calls} lần gọi LLM."
        return None

    # --- asking the model -----------------------------------------------------------------

    def _prompt(self, state: PageState, run: _Run, with_image: bool) -> str:
        warnings = [f"⚠ {w}" for w in self._repeat_warnings(run)]
        if with_image:
            warnings.append("Ảnh chụp màn hình hiện tại được đính kèm.")
        return render(
            "flow_agent",
            title=self.flow.title,
            persona=self.flow.persona,
            goal=self.flow.goal,
            expected_steps="; ".join(self.flow.expected_steps),
            success_signal=self.flow.success_signal,
            submit_policy=self.policy,
            user_notes_or_none=self.notes or "không có",
            sample_data_json_or_empty=json.dumps(run.sample_data, ensure_ascii=False) or "{}",
            steps_so_far="\n".join(run.history[-HISTORY_LINES:]) or "(chưa có)",
            url=state.url,
            page_title=state.title,
            main_heading=state.heading or "-",
            messages=format_messages(state.messages),
            elements=format_elements(state.elements) or "(không có phần tử)",
            warnings="\n".join(warnings),
        )

    def _repeat_warnings(self, run: _Run) -> list[str]:
        return [
            f"Hành động «{k}» đã lặp {n} lần mà trang không đổi; hãy chọn cách khác hoặc give_up."
            for k, n in run.unchanged.items()
            if n >= REPEAT_WARN
        ]

    def _ask(self, state: PageState, shot: bytes | None, run: _Run) -> AgentAnswer | None:
        send_image = self.images and shot is not None
        try:
            if send_image:
                try:
                    answer = self.caller.call(
                        ROLE, self._prompt(state, run, True), AgentAnswer, images=[shot]
                    )
                    self.images_sent = True
                    return answer
                except (LLMCallError, BudgetExceeded):
                    raise
                except Exception as e:  # no vision model, a bad image, a provider that refuses it
                    self.images = False
                    kind = "chưa cấu hình" if isinstance(e, VisionUnavailable) else str(e)[:100]
                    run.warnings.append(f"Không gửi được ảnh ({kind}); chuyển sang chỉ dùng chữ.")
            return self.caller.call(ROLE, self._prompt(state, run, False), AgentAnswer)
        except BudgetExceeded:
            raise
        except LLMCallError as e:
            run.warnings.append(f"Model không trả lời hợp lệ: {str(e)[:160]}")
            return None

    # --- steps ----------------------------------------------------------------------------

    def _shot(self, page: Page, run: _Run, index: int) -> bytes | None:
        """A viewport JPEG: saved as the step's picture and shown to the model next round."""
        try:
            data: bytes = page.screenshot(type="jpeg", quality=80)
        except Exception as e:
            run.warnings.append(f"Không chụp được ảnh: {str(e)[:80]}")
            return None
        path = self.flow_dir / "steps" / f"s{index}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return data

    def _rel(self, index: int) -> str:
        return f"{FLOW_DIR}/steps/s{index}.jpg"

    def _goto_step(self, page: Page) -> _Step:
        return _Step(
            action={"do": "goto", "url": self.flow.start_url},
            locator=None, target_text="", value=None, url_before="",
            url_after=page.url,
            note="Mở trang bắt đầu", chapter="",
        )  # fmt: skip

    def _step(self, result: StepResult, answer: AgentAnswer, action: FlowAction) -> _Step:
        recorded: dict[str, Any] = {"do": action.do, "target": result.target_text or None}
        if action.do in ("type", "select", "pick_date"):
            recorded["text"] = action.value
        if action.do == "scroll":
            recorded["do"], recorded["ms"] = "scroll", 600 if action.direction == "down" else -600
        return _Step(
            action=recorded,
            locator=result.locator.model_dump() if result.locator else None,
            target_text=result.target_text,
            value=action.value,
            url_before=result.url_before,
            url_after=result.url_after,
            note=answer.note.strip() or result.target_text,
            chapter=answer.chapter.strip(),
        )

    def _history_line(self, n: int, result: StepResult) -> str:
        what = f"{result.do} «{result.target_text}»" + (
            f" = {result.value}" if result.value else ""
        )
        return f"{n}. {what} → {result.url_after}"

    def _failed(self, run: _Run, action: FlowAction, name: str, why: str) -> None:
        run.history.append(f"✗ {action.do} «{name}»: {why[:140]}")
        run.warnings.append(f"{action.do} «{name}»: {why[:140]}")

    def _stop_before_submit(
        self, page: Page, state: PageState, action: FlowAction, answer: AgentAnswer, run: _Run
    ) -> bool:
        """Hover and highlight the final button; True when the run ends here."""
        element = state.by_ref.get(action.ref or "")
        if element is None or not is_submit_target(element):
            run.invented_refs += int(element is None)
            self._failed(run, action, action.ref or "", "ref không phải nút gửi của form")
            return False
        found = resolve(page, element.locator)
        if found.target is None:
            self._failed(run, action, element.name, "không tìm lại được nút gửi")
            return False
        found.target.hover()
        page.wait_for_timeout(400)
        spec = element.locator.model_dump()
        chapter = answer.chapter.strip()
        for do, extra in (("hover", {}), ("highlight", {"ms": 1800})):
            self._shot(page, run, len(run.steps) + 1)
            run.steps.append(
                _Step(
                    action={"do": do, "target": element.name, **extra},
                    locator=spec,
                    target_text=element.name,
                    value=None,
                    url_before=page.url,
                    url_after=page.url,
                    note=answer.note.strip() or f"Sẵn sàng bấm «{element.name}»",
                    chapter=chapter,
                )  # fmt: skip
            )
        run.status, run.stop_name = "stopped_before_submit", element.name
        return True

    # --- result ---------------------------------------------------------------------------

    def _finish(self, run: _Run, started: float, before: dict[str, int]) -> FlowRun:
        names = [(i, s.action["do"], s.chapter) for i, s in enumerate(run.steps, start=1)]
        first = next((c for _, d, c in names if d != "goto" and c), "Mở trang")
        names = [(i, d, first if d == "goto" else c) for i, d, c in names]
        chapters = group_chapters(names)
        ids = chapter_ids(chapters)
        usage = self.caller.tracker.steps.get(ROLE, {})
        calls = usage.get("calls", 0) - before.get("calls", 0)
        model = (
            self.caller.llm.vision_model if self.images_sent else self.caller.llm.model
        ) or self.caller.llm.model
        steps = []
        for i, s in enumerate(run.steps, start=1):
            steps.append(
                {
                    "i": i,
                    "action": s.action,
                    "locator": s.locator,
                    "target_text": s.target_text or None,
                    "value": s.value,
                    "url_before": s.url_before or None,
                    "url_after": s.url_after or None,
                    "screenshot": self._rel(i)
                    if (self.flow_dir / "steps" / f"s{i}.jpg").is_file()
                    else None,
                    "note": s.note,
                    "chapter_id": ids.get(i),
                    "t_ms_hint": (i - 1) * STEP_MS,
                }
            )
        return FlowRun.model_validate(
            {
                "flow_id": self.flow.id,
                "status": run.status if run.steps else "failed",
                "steps": steps,
                "chapters": [
                    {"id": f"c{n}", "title": c.title, "step_ids": c.step_ids}
                    for n, c in enumerate(chapters, start=1)
                ],
                "sample_data": run.sample_data,
                "warnings": run.warnings,
                "llm_calls": calls,
                "submit_policy": self.policy,
                "stop_ref": run.stop_name,
                "report": {
                    "model": model,
                    "used_images": self.images_sent,
                    "llm_calls": calls,
                    "prompt_tokens": usage.get("input", 0) - before.get("input", 0),
                    "completion_tokens": usage.get("output", 0) - before.get("output", 0),
                    "seconds": round(self.clock() - started, 1),
                    "write_requests": list(self.session.guard.write_log),
                    "invented_refs": run.invented_refs,
                    "repeat_warnings": sum(1 for n in run.unchanged.values() if n >= REPEAT_WARN),
                },
            }
        )

    # --- cache ----------------------------------------------------------------------------

    def _cache_dir(self) -> Path:
        key = cache_key(self.flow, self.policy, self.notes)
        return self.caller.cache_dir / "flow-cache" / key

    def _save(self, flow_run: FlowRun) -> None:
        self.flow_dir.mkdir(parents=True, exist_ok=True)
        (self.flow_dir / RUN_FILE).write_text(flow_run.model_dump_json(indent=2), encoding="utf-8")
        if self.use_cache and flow_run.status in ("reached_goal", "stopped_before_submit"):
            target = self._cache_dir()
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(self.flow_dir, target / FLOW_DIR)

    def _from_cache(self) -> FlowRun | None:
        if not self.use_cache:
            return None
        source = self._cache_dir() / FLOW_DIR
        if not (source / RUN_FILE).is_file():
            return None
        shutil.rmtree(self.flow_dir, ignore_errors=True)
        shutil.copytree(source, self.flow_dir)
        cached = FlowRun.model_validate_json((self.flow_dir / RUN_FILE).read_text(encoding="utf-8"))
        cached.warnings = [*cached.warnings, "Kết quả lấy từ cache (không gọi LLM)."]
        cached.llm_calls = 0
        if cached.report:
            cached.report.llm_calls = 0
        return cached
