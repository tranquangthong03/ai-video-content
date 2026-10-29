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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import Page
from pydantic import BaseModel, Field

from app.browser.auth_detect import LoginRequired, detect_login
from app.browser.env_issue import check_env_issue
from app.browser.form_actions import ActionFailed, NoReadableOptions, fold
from app.browser.locate import Unsafe, resolve
from app.browser.page_utils import dismiss_cookie_banner, page_is_blank, wait_for_settle
from app.browser.session import BrowserSession
from app.core.commit_verbs import commit_group
from app.core.goal_status import goal_status, required_groups
from app.core.usage import BudgetExceeded
from app.flows.actions import ActionRunner, FlowAction, StepResult, is_submit_target
from app.flows.chapters import chapter_ids, group_chapters
from app.flows.film import Film
from app.flows.page_state import (
    PageElement,
    PageState,
    capture_state,
    format_elements,
    format_messages,
)
from app.llm.json_call import JsonCaller, LLMCallError, VisionUnavailable
from app.llm.prompts import render
from app.schemas.generated.core_flow import CoreFlow
from app.schemas.generated.flow_run import FlowRun
from app.schemas.generated.locator import LocatorSpec

ROLE = "flow_agent"
FLOW_DIR = "flow"
RUN_FILE = "flow_run.json"
HISTORY_LINES = 14
ESCALATE_FAILED = 2  # refused actions after which the screenshot goes along
ESCALATE_CANVAS = 0.25  # share of the viewport a canvas / svg must take to do the same
FILMED_TIMEOUT_S = 480.0
REPEAT_WARN, REPEAT_STOP = 2, 3
# "the account cannot do this" needs evidence; the agent may be refused this many times first
GIVE_UP_REFUSALS = 2
EVIDENCE_KINDS = ("no_data", "feature_missing")
GIVE_UP_NEEDS_ENV = "env_blocked cần cảnh báo môi trường (trang trống vì hệ thống an toàn chặn)"
GIVE_UP_NEEDS_PROOF = (
    "chưa có thông báo của trang và chưa thử mở menu/mục khớp mô tả luồng; "
    "hãy điều hướng qua menu tới màn hình đó rồi mới kết luận"
)
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
    blank: bool = False  # the page was empty after the wait: not a valid storyboard step
    no_effect: bool = False  # the page did not change after the action
    flag_reason: str | None = None


def tried_to_reach(flow: CoreFlow, steps: list[_Step]) -> bool:
    """Did the agent open a menu or link that matches the flow's own words (not just the start)?"""
    words = {
        w
        for w in fold(" ".join([flow.title, flow.goal, *flow.expected_steps])).split()
        if len(w) >= 4
    }
    return any(
        s.action.get("do") in ("navigate", "click") and words & set(fold(s.target_text).split())
        for s in steps
    )


def give_up_has_evidence(
    kind: str,
    quote: str | None,
    flow: CoreFlow,
    steps: list[_Step],
    env_issues: Sequence[object] = (),
) -> bool:
    """no_data / feature_missing only count with the site's own message on the page, or after the
    agent really tried to reach the screen through the menu; env_blocked only after the guard was
    seen breaking a page (an env_issue); other kinds need no proof."""
    if kind == "env_blocked":
        return bool(env_issues)
    return kind not in EVIDENCE_KINDS or bool(quote) or tried_to_reach(flow, steps)


@dataclass
class _Run:
    steps: list[_Step] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sample_data: dict[str, Any] = field(default_factory=dict)
    history: list[str] = field(default_factory=list)
    unchanged: dict[str, int] = field(default_factory=dict)
    invented_refs: int = 0
    repeat_warnings: int = 0
    failed_actions: int = 0
    give_up: dict[str, Any] | None = None
    give_up_refused: int = 0
    env_issues: list[dict[str, Any]] = field(default_factory=list)
    text_calls: int = 0
    vision_calls: int = 0
    escalated_because: str | None = None
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
        previous: FlowRun | None = None,
        keep: int = 0,
        film: Film | None = None,
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
        # vision auto: text only until the work gets hard (see _maybe_escalate); an explicit
        # use_images wins over the role's setting
        mode = (
            getattr(caller, "vision_mode", "on")
            if use_images is None
            else ("on" if use_images else "off")
        )
        self.vision_auto = mode == "auto" and caller.can_see_images
        self.images = caller.can_see_images and mode == "on"
        self.film = film  # filming while the agent works (the live clip of FlowRun.live)
        # holds and slow typing make a filmed run longer than a silent one
        self.limits = limits or (Limits(timeout_s=FILMED_TIMEOUT_S) if film else Limits())
        self.use_cache = caller.cache_enabled if use_cache is None else use_cache
        self.clock = clock
        self.previous = previous  # earlier run: its first `keep` steps are repeated, not asked
        self.keep = keep
        self.images_sent = False
        self._calls0 = 0
        self.flow_dir = job_dir / FLOW_DIR

    # --- entry point -----------------------------------------------------------------------

    def run(self) -> FlowRun:
        cached = None if self.previous else self._from_cache()
        if cached is not None:
            return cached
        started = self.clock()
        before = dict(self.caller.tracker.steps.get(ROLE, {}))
        self._calls0 = before.get("calls", 0)
        run = _Run()
        film = self.film
        context = self.session.new_context(
            viewport=self.viewport, record_video_dir=film.raw_dir if film else None
        )
        try:
            if film is not None:
                film.prepare(context)
            page = context.new_page()
            if film is not None:
                film.start(page, allow_submit=self.policy == "allow")
            self._open(page, run)
            if run.status != "failed":
                self._loop(page, run, started)
            if film is not None:
                film.stop()
        finally:
            context.close()
        live = film.finish() if film is not None else None
        flow_run = self._finish(run, started, before, live)
        self._save(flow_run)
        return flow_run

    # --- the loop --------------------------------------------------------------------------

    def _open(self, page: Page, run: _Run) -> None:
        run.status = "partial"
        since = self.session.guard.clock()
        try:
            response = page.goto(self.flow.start_url, wait_until="domcontentloaded")
            wait_for_settle(page)
            dismiss_cookie_banner(page)
        except Exception as e:
            run.status = "failed"
            run.warnings.append(f"Không mở được trang bắt đầu: {str(e)[:160]}")
            return
        self._check_login(page, response.status if response else None)
        issue = check_env_issue(page, self.session.guard, since)
        if issue is not None:
            self._note_env_issue(run, issue)
        if self.film is not None:
            self.film.opened()

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
            ops=self.film.ops if self.film else None,
            observer=self.film,
        )
        pending_key: str | None = None
        pending_sig = ""
        shot = self._shot(page, run, 1)
        run.steps.append(self._goto_step(page))
        if self.previous is not None and self.keep > 1:
            shot = self._replay(page, runner, run) or shot
        while True:
            if self.film is not None:
                self.film.begin_wait()  # nothing moves on the page until the model has answered
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
            self._maybe_escalate(state, run)
            stop = self._limit_reached(run, started)
            if stop:
                run.warnings.append(stop)
                return
            answer = self._ask(state, shot, run)
            if self.film is not None:
                self.film.end_wait()
            if answer is None:
                return
            action = answer.action
            run.sample_data.update(answer.sample_data_update)
            if action.do in ("finish", "give_up"):
                run.status = "reached_goal" if action.do == "finish" else "partial"
                if action.do == "give_up":
                    why = action.reason or answer.reason or "?"
                    kind = action.reason_kind or "stuck"
                    quote = self._verified_quote(action.quote, state)
                    if not give_up_has_evidence(kind, quote, self.flow, run.steps, run.env_issues):
                        if run.give_up_refused < GIVE_UP_REFUSALS:
                            run.give_up_refused += 1
                            run.status = "partial"
                            self._failed(
                                run, action, "give_up",
                                GIVE_UP_NEEDS_ENV
                                if kind == "env_blocked"
                                else GIVE_UP_NEEDS_PROOF,
                            )  # fmt: skip
                            continue
                        kind = "stuck"  # still no proof: the flow is not blamed on the account
                    run.warnings.append(f"Agent bỏ cuộc: {why}")
                    run.give_up = {"reason_kind": kind, "reason": why, "quote": quote}
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
                result = self._run_action(runner, state, action, len(run.steps) + 1)
            except ActionFailed as e:
                if "không có trong danh sách" in str(e):
                    run.invented_refs += 1
                if isinstance(e, NoReadableOptions):
                    self._escalate(run, "control tự vẽ không đọc được option")
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
            step = self._step(result, answer, action)
            self._flag(run, step, result)
            run.steps.append(step)
            run.history.append(self._history_line(len(run.steps), result))
            if result.env_issue is not None:
                self._note_env_issue(run, result.env_issue)
            if len([s for s in run.steps if s.action["do"] != "goto"]) >= self.limits.max_actions:
                run.warnings.append(f"Dừng: đã đủ {self.limits.max_actions} hành động.")
                return

    def _run_action(
        self, runner: ActionRunner, state: PageState, action: FlowAction, step: int
    ) -> StepResult:
        """runner.run, noted by the film: a failed attempt is cut later, a good one is held."""
        film = self.film
        if film is not None:
            film.attempt_start()
        try:
            result = runner.run(state, action)
        except BaseException:
            if film is not None:
                film.attempt_end(False, None, action.do)
            raise
        if film is not None:
            film.attempt_end(True, step, action.do)
        return result

    def _replay(self, page: Page, runner: ActionRunner, run: _Run) -> bytes | None:
        """Repeat the kept steps of the previous run from their locators, without asking the model.
        A step that no longer works ends the replay; the agent carries on from there."""
        prev = self.previous
        assert prev is not None
        titles = {c.id: c.title for c in prev.chapters}
        run.sample_data = dict(prev.sample_data)
        shot: bytes | None = None
        for old in prev.steps[1 : self.keep]:
            do = old.action.do
            action = FlowAction(
                do=do,  # type: ignore[arg-type]
                ref=None if do == "scroll" else "r",
                value=old.action.text,
                direction="up" if old.action.text == "up" else "down",
            )
            element = PageElement(
                ref="r", role=(old.locator.role if old.locator else None) or "button",
                tag=(old.locator.tag if old.locator else None) or "", name=old.target_text or "",
                locator=old.locator or LocatorSpec(),
            )  # fmt: skip
            state = PageState(page.url, "", "", [], [element])
            try:
                result = self._run_action(runner, state, action, len(run.steps) + 1)
            except Exception as e:
                run.warnings.append(
                    f"Không lặp lại được bước {old.i} ({str(e).splitlines()[0][:100]}); "
                    "agent làm tiếp từ đây."
                )
                break
            shot = self._shot(page, run, len(run.steps) + 1)
            run.steps.append(
                _Step(
                    action=old.action.model_dump(exclude_none=True),
                    locator=old.locator.model_dump() if old.locator else None,
                    target_text=old.target_text or "",
                    value=old.value,
                    url_before=result.url_before,
                    url_after=result.url_after,
                    note=old.note,
                    chapter=titles.get(old.chapter_id or "", ""),
                )  # fmt: skip
            )
            run.history.append(self._history_line(len(run.steps), result))
        return shot

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
        for issue in run.env_issues[-1:]:
            warnings.append(
                f"⚠ MÔI TRƯỜNG: trang {issue['page_url']} trống vì hệ thống an toàn đã chặn "
                f"{len(issue['blocked_urls'])} yêu cầu ghi dữ liệu mà trang cần để tải nội dung. "
                'Đây không phải lỗi của bạn: dùng give_up với reason_kind "env_blocked", '
                "đừng thử tiếp trang này."
            )
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

    @staticmethod
    def _verified_quote(quote: str | None, state: PageState) -> str | None:
        """The site's message, only when it really is on the page (the model may not invent it)."""
        if not quote or not quote.strip():
            return None
        seen = [state.heading, state.title, *state.messages, *(e.name for e in state.elements)]
        wanted = fold(quote)
        return quote.strip() if any(wanted in fold(text) for text in seen if text) else None

    def _escalate(self, run: _Run, why: str) -> None:
        """From the next question on the screenshot goes along (vision auto only; it stays on)."""
        if self.vision_auto and not self.images:
            self.images = True
            run.escalated_because = why
            run.warnings.append(f"Bắt đầu gửi kèm ảnh màn hình: {why}.")

    def _maybe_escalate(self, state: PageState, run: _Run) -> None:
        if not self.vision_auto or self.images:
            return
        if self._repeat_warnings(run):
            self._escalate(run, "cảnh báo lặp")
        elif run.failed_actions >= ESCALATE_FAILED:
            self._escalate(run, f"{run.failed_actions} hành động bị từ chối")
        elif state.canvas_ratio >= ESCALATE_CANVAS:
            self._escalate(run, "trang có canvas/svg lớn")

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
                    run.vision_calls += 1
                    return answer
                except (LLMCallError, BudgetExceeded):
                    raise
                except Exception as e:  # no vision model, a bad image, a provider that refuses it
                    self.images = False
                    kind = "chưa cấu hình" if isinstance(e, VisionUnavailable) else str(e)[:100]
                    run.warnings.append(f"Không gửi được ảnh ({kind}); chuyển sang chỉ dùng chữ.")
            run.text_calls += 1
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
        blank = page_is_blank(page)
        return _Step(
            action={"do": "goto", "url": self.flow.start_url},
            locator=None, target_text="", value=None, url_before="",
            url_after=page.url,
            note="Mở trang bắt đầu", chapter="",
            blank=blank, flag_reason="blank_page" if blank else None,
        )  # fmt: skip

    def _step(self, result: StepResult, answer: AgentAnswer, action: FlowAction) -> _Step:
        recorded: dict[str, Any] = {"do": action.do, "target": result.target_text or None}
        if action.do in ("type", "select", "pick_date"):
            recorded["text"] = action.value
        if action.do == "scroll":
            recorded["ms"] = 600  # pixels; BrowserAction.ms is never negative: "up" goes in text
            if action.direction == "up":
                recorded["text"] = "up"
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

    @staticmethod
    def _flag(run: _Run, step: _Step, result: StepResult) -> None:
        """A step whose page is empty after the wait is no valid storyboard step."""
        if result.blank:
            step.blank = True
            step.flag_reason = "guard_broke_page" if result.env_issue else "blank_page"
            run.warnings.append(
                f"Bước {len(run.steps) + 1}: trang trống sau khi chờ, bước bị bỏ khỏi storyboard."
            )

    @staticmethod
    def _note_env_issue(run: _Run, issue: dict[str, Any]) -> None:
        if issue not in run.env_issues:
            run.env_issues.append(issue)
        run.warnings.append(
            f"Trang {issue['page_url']} trống vì hệ thống an toàn đã chặn "
            f"{len(issue['blocked_urls'])} yêu cầu."
        )

    def _history_line(self, n: int, result: StepResult) -> str:
        what = f"{result.do} «{result.target_text}»" + (
            f" = {result.value}" if result.value else ""
        )
        if result.pressed_enter:
            what += " (đã nhấn Enter)"
        if result.blank:
            what += " (trang TRỐNG sau khi chờ)"
        return f"{n}. {what} → {result.url_after}"

    def _failed(self, run: _Run, action: FlowAction, name: str, why: str) -> None:
        run.failed_actions += 1
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
        wanted = required_groups(self.flow)
        if wanted and commit_group(element.name) not in wanted and not element.is_submit_like:
            self._failed(  # the warning must point at the button that matches the user's action
                run, action, element.name,
                "nút này không khớp hành động phải làm: " + "; ".join(self.flow.required_actions),
            )  # fmt: skip
            return False
        found = resolve(page, element.locator)
        if found.target is None:
            self._failed(run, action, element.name, "không tìm lại được nút gửi")
            return False
        spec = element.locator.model_dump()
        if self.film is not None:  # the film's own pointing (hover, then the outline)
            if not self.film.point_at(spec, element.name, len(run.steps) + 1):
                self._failed(run, action, element.name, "không trỏ được vào nút gửi")
                return False
        else:
            found.target.hover()
            page.wait_for_timeout(400)
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

    def _finish(
        self, run: _Run, started: float, before: dict[str, int], live: dict[str, Any] | None = None
    ) -> FlowRun:
        names = [(i, s.action["do"], s.chapter) for i, s in enumerate(run.steps, start=1)]
        first = next((c for _, d, c in names if d != "goto" and c), "Mở trang")
        names = [(i, d, first if d == "goto" else c) for i, d, c in names]
        chapters = group_chapters(names)
        ids = chapter_ids(chapters)
        usage = self.caller.tracker.steps.get(ROLE, {})
        calls = usage.get("calls", 0) - before.get("calls", 0)
        text_model, vision_model = (
            self.caller.llm.model,
            self.caller.llm.vision_model or self.caller.llm.model,
        )
        if run.vision_calls and run.text_calls:
            model = f"{text_model} + {vision_model}"
        else:
            model = vision_model if run.vision_calls else text_model
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
                    "blank": s.blank,
                    "no_effect": s.no_effect,
                    "flag_reason": s.flag_reason,
                }
            )
        flow_run = FlowRun.model_validate(
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
                "live": live,
                "give_up": run.give_up,
                "env_issues": run.env_issues,
                "report": {
                    "model": model,
                    "used_images": self.images_sent,
                    "llm_calls": calls,
                    "prompt_tokens": usage.get("input", 0) - before.get("input", 0),
                    "completion_tokens": usage.get("output", 0) - before.get("output", 0),
                    "seconds": round(self.clock() - started, 1),
                    "write_requests": list(self.session.guard.write_log),
                    "guard_intents": dict(self.session.guard.intents),
                    "text_calls": run.text_calls,
                    "vision_calls": run.vision_calls,
                    "escalated_because": run.escalated_because,
                    "invented_refs": run.invented_refs,
                    "repeat_warnings": sum(1 for n in run.unchanged.values() if n >= REPEAT_WARN),
                },
            }
        )
        flow_run.goal_status = goal_status(self.flow, flow_run)  # code decides, not the model
        if flow_run.goal_status == "not_reached" and flow_run.status in (
            "reached_goal",
            "stopped_before_submit",
        ):
            flow_run.status = "partial"
            flow_run.warnings.append(
                "Chưa thực hiện hành động bạn yêu cầu: " + "; ".join(self.flow.required_actions)
                if self.flow.required_actions
                else "Luồng chưa chứng minh được kết quả."
            )
        return flow_run

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
