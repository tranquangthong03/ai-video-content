"""select_flow: the card that lets the user pick the flow the video shows (pure, no I/O).

Answers of the UserResponse (all strings): selected_flows (ordered id list), flow_description
(free text: "describe the flow you want"), allow_submit ("true"/"false"), submit_confirmed
("true" when the user ticked "this is my own test account, creating data is fine").
"""

from dataclasses import dataclass, field
from typing import Literal

from app.core.interaction import make_request
from app.core.shared_demo import SHARED_DEMO_REASON, is_shared_demo
from app.schemas.generated.core_flow import CoreFlow
from app.schemas.generated.interaction import InteractionRequest
from app.schemas.generated.user_response import UserResponse

MAX_SELECTED_FLOWS = 2  # one main flow and, for videos of 45 s or more, a short second one
SECONDARY_MIN_DURATION_S = 45
SubmitPolicy = Literal["stop", "allow"]

SUBMIT_NEEDS_CONFIRMATION = "Cần tick xác nhận tài khoản thử nghiệm để cho phép bấm Gửi/Lưu."


@dataclass
class FlowSelection:
    """The user's pick: flows in priority order, the submit policy and notes for the report."""

    flows: list[CoreFlow]
    submit_policy: SubmitPolicy = "stop"
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FlowAnswer:
    selected: list[str]
    description: str
    wants_submit: bool
    confirmed: bool


def default_flow_ids(flows: list[CoreFlow]) -> list[str]:
    """The flow to preselect: the first one the model ranked (they are sorted by value)."""
    return [flows[0].id] if flows else []


def build_request(
    job_id: str,
    flows: list[CoreFlow],
    root_url: str,
    *,
    default: list[str] | None = None,
    notice: str = "",
) -> InteractionRequest:
    message = (
        "Chọn luồng chức năng chính sẽ xuất hiện trong video "
        f"(tối đa {MAX_SELECTED_FLOWS}; luồng thứ hai chỉ dùng khi video từ "
        f"{SECONDARY_MIN_DURATION_S}s). Hoặc tự mô tả luồng bạn muốn quay."
    )
    blocked = SHARED_DEMO_REASON if is_shared_demo(root_url) else None
    return make_request(
        job_id,
        "select_flow",
        f"{notice}\n{message}" if notice else message,
        flows=[f.model_dump() for f in flows],
        flow_select={
            "max": MAX_SELECTED_FLOWS,
            "default": default if default is not None else default_flow_ids(flows),
            "submit_blocked_reason": blocked,
        },
    )


def read_answer(response: UserResponse) -> FlowAnswer:
    answers = response.answers or {}
    raw = answers.get("selected_flows", [])
    selected = [raw] if isinstance(raw, str) else list(raw)
    description = answers.get("flow_description", "")
    return FlowAnswer(
        selected=[s for s in selected if s],
        description=(description if isinstance(description, str) else "").strip(),
        wants_submit=answers.get("allow_submit") == "true",
        confirmed=answers.get("submit_confirmed") == "true",
    )


def check_flow_answer(request: InteractionRequest, response: UserResponse) -> list[str]:
    """Errors in an `answer` to select_flow (ids that do not exist, too many, none)."""
    answer = read_answer(response)
    known = {f.id for f in request.flows or []}
    errors = [f"flow '{i}' does not exist" for i in answer.selected if i not in known]
    if len(set(answer.selected)) != len(answer.selected):
        errors.append("a flow was picked twice")
    if not answer.description:  # a description alone is a valid answer (it adds a flow)
        if not answer.selected:
            errors.append("pick at least one flow or describe one")
    if len(answer.selected) > MAX_SELECTED_FLOWS:
        errors.append(f"pick at most {MAX_SELECTED_FLOWS} flows")
    return errors


def resolve_submit_policy(
    root_url: str, flows: list[CoreFlow], answer: FlowAnswer
) -> tuple[SubmitPolicy, str | None]:
    """("allow", None) only when asked, confirmed, a flow needs it and the site is not a shared
    demo; otherwise ("stop", why the request was not honoured, or None when nothing was asked)."""
    if not answer.wants_submit:
        return "stop", None
    if is_shared_demo(root_url):
        return "stop", SHARED_DEMO_REASON
    if not answer.confirmed:
        return "stop", SUBMIT_NEEDS_CONFIRMATION
    if not any(f.needs_submit for f in flows):
        return "stop", None
    return "allow", None
