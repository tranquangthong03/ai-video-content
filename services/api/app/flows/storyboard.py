"""The storyboard card (flow_storyboard_review): what the agent did, step by step, and what to keep
when the user asks for a change (pure functions, no I/O).

Step numbers are the `i` of the run (step 1 is the opening page), the same numbers the user sees.
"""

import re

from app.browser.form_actions import fold
from app.core.interaction import make_request
from app.flows.actions import SUBMIT_NAME
from app.schemas.generated.core_flow import CoreFlow
from app.schemas.generated.flow_quality import FlowQuality
from app.schemas.generated.flow_run import FlowRun
from app.schemas.generated.interaction import InteractionRequest

STATUS_TEXT = {
    "reached_goal": "Đạt mục tiêu",
    "stopped_before_submit": "Dừng trước khi gửi (nút gửi được tô sáng)",
    "partial": "Chưa trọn luồng",
    "failed": "Không thực hiện được",
}
TAIL_ACTIONS = ("hover", "highlight")  # the pointing steps that close a stopped_before_submit run
STEP_NUMBER = re.compile(r"(?:buoc|step)\s*(\d+)")
APPEND_WORDS = ("them", "add", "append", "tiep tuc", "xem them")
STOP_WORDS = {
    "chon", "thay", "bo", "buoc", "them", "xem", "loai", "cho", "voi", "the", "not", "instead",
    "remove", "step", "doi", "sua", "mot", "cac", "nhung", "nay", "kia", "vao", "ngay",
}  # fmt: skip


def build_request(
    job_id: str,
    flow: CoreFlow,
    run: FlowRun,
    *,
    notice: str = "",
    version: int = 1,
    quality: FlowQuality | None = None,
) -> InteractionRequest:
    # the web shows every line but the last as a notice: only the server's notice goes before it
    text = (
        f"Luồng «{flow.title}»: {STATUS_TEXT.get(run.status, run.status)} (bản {version}). "
        "Xem từng bước bên dưới. Bạn có thể duyệt, sửa bằng một câu "
        "(ví dụ «bỏ bước 3», «chọn loại nghỉ Annual thay vì Personal», «thêm bước xem My Leave»), "
        "chạy lại từ đầu hoặc hủy."
    )
    if run.status in ("partial", "failed"):
        text += " Luồng chưa trọn: bạn nên sửa hoặc chạy lại trước khi duyệt."
    message = "\n".join(([notice] if notice else []) + [text])
    return make_request(
        job_id,
        "flow_storyboard_review",
        message,
        flows=[flow.model_dump()],
        flow_review=run.model_dump(mode="json"),
        script_version=version,
        flow_quality=quality.model_dump() if quality else None,
    )


def first_unsafe_index(run: FlowRun) -> int:
    """Number of leading steps that are safe to repeat: those before a click on a submit-like
    button (it would send the form a second time) and before the closing hover/highlight."""
    n = len(run.steps)
    while n > 1 and run.steps[n - 1].action.do in TAIL_ACTIONS:
        n -= 1
    for index, step in enumerate(run.steps[:n]):
        if step.action.do == "click" and SUBMIT_NAME.search(step.target_text or ""):
            return index
    return n


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", fold(text)) if len(t) >= 3 and t not in STOP_WORDS}


def keep_prefix(run: FlowRun, instruction: str) -> int:
    """How many leading steps (the opening page included) to keep for the user's change.

    "bỏ bước 3" keeps steps 1-2; "thêm bước ..." keeps everything that can be repeated safely;
    otherwise the first step whose target or value is named in the sentence is where the rerun
    starts. Nothing recognised: only the opening page is kept."""
    limit = first_unsafe_index(run)
    text = fold(instruction)
    numbers = [int(m) for m in STEP_NUMBER.findall(text)]
    if numbers:
        return max(1, min(limit, min(numbers) - 1))
    if any(w in text for w in APPEND_WORDS) and not re.search(r"\bthay\b|\bdoi\b|\bsua\b", text):
        return max(1, limit)
    wanted = _tokens(instruction)
    for step in run.steps[1:limit]:
        if wanted & _tokens(f"{step.target_text or ''} {step.value or ''}"):
            return max(1, step.i - 1)
    return 1
