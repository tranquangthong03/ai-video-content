"""The Flow Agent's hands: one validated action from the model, done on the live page.

Every action goes through the shared browser layer: the ref must be in the list the model was
given, the element is resolved again from its LocatorSpec, the blacklist and the same-site rules
apply, and the page settles afterwards. A click on a submit-like control is refused unless the
flow's submit policy is "allow" (then at most MAX_SUBMITS times, inside the guard's write window).
"""

import re
from dataclasses import dataclass
from typing import Literal

from playwright.sync_api import Page
from pydantic import BaseModel, model_validator

from app.browser import form_actions
from app.browser.blacklist import is_blocked, is_blocked_href
from app.browser.form_actions import ActionFailed, Ops
from app.browser.guard import MAX_WRITE_WINDOWS, RequestGuard, WritesNotAllowed
from app.browser.locate import ElementInfo, Target, Unsafe, check_clickable, check_typeable, resolve
from app.browser.page_utils import wait_for_settle
from app.browser.urls import same_site
from app.flows.page_state import PageElement, PageState
from app.schemas.generated.locator import LocatorSpec

MAX_SUBMITS = MAX_WRITE_WINDOWS
SUBMIT_NAME = re.compile(
    r"\b(save|submit|apply|create|add|confirm|send request|lưu|gửi|tạo|thêm|xác nhận)\b",
    re.IGNORECASE,
)
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

    @model_validator(mode="after")
    def _complete(self) -> "FlowAction":
        if self.do in REF_ACTIONS and not self.ref:
            raise ValueError(f"{self.do} needs a ref")
        if self.do in VALUE_ACTIONS and self.value is None:
            raise ValueError(f"{self.do} needs a value")
        if self.do == "scroll" and self.direction is None:
            self.direction = "down"
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


def is_submit_target(element: PageElement) -> bool:
    """A button that sends the form: the DOM says so, or it sits in a form and is named like one.
    Links never count (a menu entry called "Apply" only goes to another page)."""
    if element.is_submit_like and element.role != "link":
        return True
    return element.role == "button" and element.in_form and bool(SUBMIT_NAME.search(element.name))


def check_submit_click(info: ElementInfo, root_url: str) -> None:
    """The checks for the click the flow is allowed to make: still no delete/pay/invite/send."""
    if is_blocked(*info.texts, strict=False, interactive=True):
        raise Unsafe("blacklist", f"matches blacklist: {info.texts[:2]}")
    if is_blocked_href(info.href) or (info.href and not same_site(info.href, root_url)):
        raise Unsafe("blacklist", f"blocked link {info.href}")


class ActionRunner:
    def __init__(
        self,
        page: Page,
        root_url: str,
        *,
        allow_submit: bool = False,
        guard: RequestGuard | None = None,
        ops: Ops | None = None,
    ) -> None:
        self.page = page
        self.root_url = root_url
        self.allow_submit = allow_submit
        self.guard = guard
        self.ops = ops or Ops()
        self.submits = 0
        self.typed: set[str] = set()

    def run(self, state: PageState, action: FlowAction) -> StepResult:
        """Do `action` on the page described by `state`. Raises ActionFailed or Unsafe."""
        result = StepResult(do=action.do, url_before=self.page.url, value=action.value)
        if action.do == "scroll":
            self._scroll(action)
        else:
            element = state.by_ref.get(action.ref or "")
            if element is None:
                raise ActionFailed(f"ref «{action.ref}» không có trong danh sách phần tử hiện tại")
            result.locator, result.target_text = element.locator, element.name
            target = self._resolve(element)
            self._act(action, element, target, result)
        wait_for_settle(self.page)
        result.url_after = self.page.url
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
        self.page.mouse.wheel(0, sign * height * SCROLL_FRACTION)
        self.page.wait_for_timeout(300)
