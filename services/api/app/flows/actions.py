"""The Flow Agent's hands: one validated action from the model, done on the live page.

Every action goes through the shared browser layer: the ref must be in the list the model was
given, the element is resolved again from its LocatorSpec, the blacklist and the same-site rules
apply, and the page settles afterwards. A click on a submit-like control is refused unless the
flow's submit policy is "allow" (then at most MAX_SUBMITS times, inside the guard's write window).
"""

from dataclasses import dataclass
from typing import Any, Literal

from playwright.sync_api import Page
from pydantic import BaseModel, model_validator

from app.browser import form_actions
from app.browser.enter_policy import enter_decision
from app.browser.env_issue import check_env_issue
from app.browser.form_actions import SUBMIT_NAME, ActionFailed, Ops, check_submit_click
from app.browser.guard import MAX_WRITE_WINDOWS, RequestGuard, WritesNotAllowed
from app.browser.locate import ElementInfo, Target, Unsafe, check_clickable, check_typeable, resolve
from app.browser.page_utils import wait_for_settle
from app.browser.write_intent import action_trigger
from app.flows.page_state import PageElement, PageState
from app.schemas.generated.locator import LocatorSpec

MAX_SUBMITS = MAX_WRITE_WINDOWS
REF_ACTIONS = {"click", "type", "select", "check", "pick_date", "navigate", "stop_before_submit"}
VALUE_ACTIONS = {"type", "select", "pick_date"}
SCROLL_FRACTION = 0.7

ActionName = Literal[
    "click", "type", "select", "check", "pick_date", "scroll", "navigate",
    "stop_before_submit", "finish", "give_up",
]  # fmt: skip


class FlowAction(BaseModel):
    """The `action` object of the model's answer."""

    do: ActionName
    ref: str | None = None
    value: str | None = None
    direction: Literal["down", "up"] | None = None
    reason: str | None = None
    reason_kind: (
        Literal[
            "no_data", "no_permission", "feature_missing", "blocked_by_site", "stuck", "env_blocked"
        ]
        | None
    ) = None
    quote: str | None = None  # give_up: the site's own message, word for word

    @model_validator(mode="after")
    def _complete(self) -> "FlowAction":
        if self.do in REF_ACTIONS and not self.ref:
            raise ValueError(f"{self.do} needs a ref")
        if self.do in VALUE_ACTIONS and self.value is None:
            raise ValueError(f"{self.do} needs a value")
        if self.do == "scroll" and self.direction is None:
            self.direction = "down"
        if self.do == "give_up" and self.reason_kind is None:
            self.reason_kind = "stuck"
        return self


@dataclass
class StepResult:
    do: str
    locator: LocatorSpec | None = None
    target_text: str = ""
    value: str | None = None
    url_before: str = ""
    url_after: str = ""
    submitted: bool = False
    pressed_enter: bool = False  # typed, then Enter (the page may have added the item)
    env_issue: dict[str, Any] | None = None  # the page stayed empty because the guard refused


def is_submit_target(element: PageElement) -> bool:
    """A button that sends the form: the DOM says so, or it sits in a form and is named like one.
    Links never count (a menu entry called "Apply" only goes to another page)."""
    if element.is_submit_like and element.role != "link":
        return True
    return element.role == "button" and element.in_form and bool(SUBMIT_NAME.search(element.name))


class ActionRunner:
    def __init__(
        self,
        page: Page,
        root_url: str,
        *,
        allow_submit: bool = False,
        guard: RequestGuard | None = None,
        ops: Ops | None = None,
        observer: Any = None,
    ) -> None:
        self.page = page
        # told which element each action is about (the live film follows it): on_target(do, element,
        # state, target); None for a scroll
        self.observer = observer
        self.root_url = root_url
        self.allow_submit = allow_submit
        self.guard = guard
        self.ops = ops or Ops()
        self.submits = 0
        self.typed: set[str] = set()

    def run(self, state: PageState, action: FlowAction) -> StepResult:
        """Do `action` on the page described by `state`. Raises ActionFailed or Unsafe."""
        result = StepResult(do=action.do, url_before=self.page.url, value=action.value)
        since = self.guard.clock() if self.guard else 0.0
        if action.do == "scroll":
            if self.guard is not None:
                self.guard.note_action("page_load")
            if self.observer is not None:
                self.observer.on_target("scroll", None, state, None)
            self._scroll(action)
        else:
            element = state.by_ref.get(action.ref or "")
            if element is None:
                raise ActionFailed(f"ref «{action.ref}» không có trong danh sách phần tử hiện tại")
            result.locator, result.target_text = element.locator, element.name
            target = self._resolve(element)
            if self.guard is not None:  # requests this action causes are judged by what it is
                self.guard.note_action(
                    action_trigger(
                        action.do, element.role, element.name, submit_like=is_submit_target(element)
                    ),
                    element.name,
                )
            if self.observer is not None:
                self.observer.on_target(action.do, element, state, target)
            self._act(action, element, target, result)
        wait_for_settle(self.page)
        result.url_after = self.page.url
        if self.guard is not None:
            result.env_issue = check_env_issue(self.page, self.guard, since)
        return result

    # --- internals ------------------------------------------------------------------------

    def _resolve(self, element: PageElement) -> Target:
        found = resolve(self.page, element.locator)
        if found.target is None:
            raise ActionFailed(
                f"không tìm lại được «{element.name}» ({'; '.join(found.tried)[:120]})"
            )
        return found.target

    def _act(
        self, action: FlowAction, element: PageElement, target: Target, result: StepResult
    ) -> None:
        do = action.do
        if do in ("click", "navigate"):
            self._click(element, target, result)
        elif do == "type":
            info = target.info()
            if not info.is_text_input and element.role != "textbox":
                raise ActionFailed(f"«{element.name}» không phải ô nhập chữ")
            check_typeable(info)
            self.ops.type_text(target, action.value or "")
            self.typed.add((action.value or "").strip().lower())
            self._enter(info, result)
        elif do == "select":
            check_clickable(target.info(), self.root_url, scope_prefix=None, strict=False)
            form_actions.select_option(
                self.page, target, action.value or "", self.root_url, self.ops
            )
        elif do == "check":
            check_clickable(target.info(), self.root_url, scope_prefix=None, strict=False)
            form_actions.check(target, self.ops)
        elif do == "pick_date":
            check_typeable(target.info())
            form_actions.pick_date(self.page, target, action.value or "", self.ops)
        else:
            raise ActionFailed(f"{do} không phải thao tác trên phần tử")

    def _enter(self, info: ElementInfo, result: StepResult) -> None:
        """Enter after typing, when the recorder's policy would press it too (a todo list adds the
        item on Enter; a form with several fields or another target is never submitted this way)."""
        guard_on = not (self.guard.allow_mutations if self.guard else False)
        allowed, _ = enter_decision(info, self.page.url, guard_on=guard_on)
        if allowed:
            self.page.wait_for_timeout(250)
            self.page.keyboard.press("Enter")
            result.pressed_enter = True

    def _click(self, element: PageElement, target: Target, result: StepResult) -> None:
        info = target.info()
        if is_submit_target(element):
            self._submit(element, target, info, result)
            return
        check_clickable(info, self.root_url, scope_prefix=None, ignore_texts=self.typed)
        self.ops.click(target)

    def _submit(
        self, element: PageElement, target: Target, info: ElementInfo, result: StepResult
    ) -> None:
        if not self.allow_submit:
            raise Unsafe(
                "blacklist", f"«{element.name}» gửi dữ liệu nhưng luồng không được phép gửi"
            )
        if self.submits >= MAX_SUBMITS:
            raise Unsafe("blacklist", f"đã bấm gửi {MAX_SUBMITS} lần trong luồng này")
        check_submit_click(info, self.root_url)
        if self.guard is None:
            raise Unsafe("blacklist", "không có request guard để mở cửa sổ ghi dữ liệu")
        try:
            with self.guard.allow_writes():
                self.submits += 1
                self.ops.click(target)
                wait_for_settle(self.page)
        except WritesNotAllowed as e:
            raise Unsafe("blacklist", f"không được ghi dữ liệu ({e})") from e
        result.submitted = True

    def _scroll(self, action: FlowAction) -> None:
        height = self.page.evaluate("window.innerHeight")
        sign = 1 if action.direction == "down" else -1
        pixels = round(sign * height * SCROLL_FRACTION)
        if self.ops.scroll is not None:
            self.ops.scroll(pixels)
        else:
            self.page.mouse.wheel(0, pixels)
        self.page.wait_for_timeout(300)
