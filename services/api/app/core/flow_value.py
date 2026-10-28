"""Is a flow worth filming? Two cheap checks that need no model.

value_actions: how many steps of a flow produce something the viewer can SEE appear - typing,
choosing, ticking, picking a date, uploading, or a click that changes the page it is on. Moving
around (opening a page, a menu, scrolling, hovering) does not count. A flow with fewer than two
makes a video of someone browsing; it is ranked after the others and labelled.

empty signals: signs that the account (or the page) has no data - a zero next to a progress or
streak label, "No data", "Nothing here", an empty list's invitation to create the first item, or an
error page where the content should be. Two or more distinct signs across the pages of a flow mean
the video would show empty screens.

Pure functions of the data the pipeline already has.
"""

import json
import re
from pathlib import Path
from typing import Any

from app.core.env_issue import env_warning
from app.schemas.generated.core_flow import CoreFlow
from app.schemas.generated.flow_quality import FlowQuality
from app.schemas.generated.flow_run import FlowRun

MIN_VALUE_ACTIONS = 2
MIN_EMPTY_SIGNALS = 2
NAVIGATION_ONLY = "Chỉ điều hướng — video sẽ ít hấp dẫn"
EMPTY_WARNING = (
    "Tài khoản/trang chưa có dữ liệu — video sẽ kém hấp dẫn. "
    "Nên dùng tài khoản có dữ liệu mẫu, hoặc chọn luồng tạo mới dữ liệu."
)

# steps that leave something behind on the page
STATE_DO = {"type", "select", "check", "pick_date", "upload"}
RESULT_WINDOW_MS = 2500  # a click "has a result" when something new shows up this soon after it
CANVAS_WINDOW_MS = 6000  # a canvas / video (an opened sample image) takes longer to show


def value_actions_of_run(run: FlowRun, logs: dict[str, Any] | None = None) -> int:
    """Steps of a run that created something visible. `logs`: the live recording's logs (inventory
    and action_log), when there are any: they say whether a click made new things appear."""
    fresh, pictures = _fresh_after(logs) if logs else (None, set())
    count = clicks = 0
    for step in run.steps:
        do = step.action.do
        if do in STATE_DO:
            count += 1
        elif do in ("click", "dblclick"):
            clicks += 1
            moved = bool(step.url_before and step.url_after and step.url_before != step.url_after)
            if moved:
                # a new page is navigation, unless a picture / canvas appeared on it (a sample
                # image opened in an editor is a result)
                count += 1 if clicks in pictures else 0
            elif fresh is None or clicks in fresh:
                # (without logs a click that stays on the page is believed)
                count += 1
    return count


def _fresh_after(logs: dict[str, Any]) -> tuple[set[int], set[int]]:
    """Numbers (1-based, in the order of the logged clicks) of the clicks after which new things
    appeared, and of those after which a new picture / canvas appeared."""
    clicks = [a for a in logs.get("action_log", []) if a.get("do") in ("click", "dblclick")]
    anything: set[int] = set()
    pictures: set[int] = set()
    for n, a in enumerate(clicks, 1):
        for snap in logs.get("inventory", []):
            late = snap["t_ms"] - a["end_ms"]
            new = [i for i in snap.get("items", []) if i.get("is_new")]
            if 0 <= late <= RESULT_WINDOW_MS and any(
                i.get("text") or i.get("kind") in ("image", "media") for i in new
            ):
                anything.add(n)
            if 0 <= late <= CANVAS_WINDOW_MS and any(i.get("kind") == "media" for i in new):
                pictures.add(n)
    return anything, pictures


# words that say a step changes something, not just where we are
_DOES = re.compile(
    r"\b(nhập|điền|gõ|chọn|tích|đánh dấu|tải lên|upload|kéo|thêm|tạo|lưu|gửi|đổi|sửa|xóa|lọc|tìm|"
    r"nén|so sánh|điều chỉnh|kéo thả|bật|tắt|đặt|type|enter|fill|select|choose|check|tick|"
    r"add|create|save|submit|edit|filter|search|compress|compare|adjust|drag|toggle|set)\b",
    re.IGNORECASE,
)
_ONLY_LOOKS = re.compile(
    r"^(xem|mở|vào|truy cập|đi tới|quan sát|theo dõi|kiểm tra|open|go to|view|see|visit)\b",
    re.IGNORECASE,
)


def value_actions_expected(flow: CoreFlow) -> int:
    """Estimate for a proposed flow (nothing has run yet): the expected steps that say they change
    something. A step that starts with looking or opening does not count, even when it says
    "bấm vào ... để mở"."""
    count = 0
    for step in flow.expected_steps:
        text = step.strip()
        if _ONLY_LOOKS.match(text) and not re.search(
            r"\b(nhập|điền|gõ|chọn|tải lên|thêm|tạo|lưu)\b", text, re.IGNORECASE
        ):
            continue
        if _DOES.search(text):
            count += 1
    return count


def label_for(value_actions: int) -> str | None:
    return NAVIGATION_ONLY if value_actions < MIN_VALUE_ACTIONS else None


# --- empty accounts and pages -------------------------------------------------------------------

_SIGNALS = (
    re.compile(r"\b0\s*/\s*\d+\b[^.]{0,30}", re.IGNORECASE),  # "0/1 courses completed"
    re.compile(r"[A-Za-z][A-Za-z ]{2,20}\(\s*0\s*\)"),  # "See all (0)": a list that counts zero
    re.compile(r"\b0\s+(?:days?|ngày|tuần|weeks?)\b[^.]{0,20}", re.IGNORECASE),  # "0 days in a row"
    re.compile(r"(?:streak|chuỗi|điểm|points|progress|tiến độ)\W{0,12}\b0\b(?!\d)", re.IGNORECASE),
    re.compile(
        r"\b0\s+(?:items?|results?|courses?|tasks?|projects?|records?|files?|kết quả|mục|khóa|bài|"
        r"nhân viên)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:no data|nothing here|nothing to show|no items?|no results?(?: found)?|"
        r"no records? found|"
        r"chưa có|không có dữ liệu|trống|get started by creating|create your first|"
        r"tạo .{0,25} đầu tiên)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:not found|failed to load|something went wrong|không tìm thấy|không tải được)\b",
        re.IGNORECASE,
    ),
)


def empty_signals(texts: list[str]) -> list[str]:
    """The distinct signs of "nothing to show" in these texts (one line of a page each)."""
    found: dict[str, str] = {}
    for text in texts:
        for pattern in _SIGNALS:
            m = pattern.search(text)
            if m:
                found.setdefault(re.sub(r"\s+", " ", m.group(0).strip().lower()), text[:80])
    return list(found)


def page_texts(page: dict[str, Any]) -> list[str]:
    """The lines of text of an explored page (headings and key texts)."""
    return [
        *(h.get("text", "") for h in page.get("headings", [])),
        *page.get("key_texts", []),
        *(e.get("text") or e.get("name") or "" for e in page.get("elements", [])),
    ]


def inventory_texts(logs: dict[str, Any]) -> list[str]:
    """The lines of text of a recording's frame_inventory snapshots."""
    return [
        i["text"]
        for snap in logs.get("inventory", [])
        for i in snap.get("items", [])
        if i.get("text")
    ]


def empty_warning(signals: list[str]) -> str | None:
    return EMPTY_WARNING if len(signals) >= MIN_EMPTY_SIGNALS else None


# --- what the cards show ------------------------------------------------------------------------


def quality_of_flow(flow: CoreFlow) -> FlowQuality:
    """A proposal that has not run yet: counted from its expected steps."""
    n = value_actions_expected(flow)
    return FlowQuality(value_actions=n, label=label_for(n), estimated=True)


def rank_by_value(flows: list[CoreFlow]) -> list[CoreFlow]:
    """Flows that only navigate go after the others (the order inside each group is kept)."""
    return sorted(flows, key=lambda f: value_actions_expected(f) < MIN_VALUE_ACTIONS)


def explored_texts(job_dir: Path) -> list[str]:
    """Every line of text of the explored pages of a job."""
    texts: list[str] = []
    for file in sorted((job_dir / "explore" / "pages").glob("*.json")):
        try:
            texts += page_texts(json.loads(file.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return texts


def quality_of_run(run: FlowRun, job_dir: Path) -> FlowQuality:
    """A run that was filmed: its value actions (the recording's logs say what appeared) and the
    empty-state signs of the pages explored plus the screens the run went through."""
    logs: dict[str, Any] | None = None
    if run.live is not None:
        try:
            logs = json.loads((job_dir / run.live.logs).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logs = None
    n = value_actions_of_run(run, logs)
    signals = empty_signals([*explored_texts(job_dir), *(inventory_texts(logs) if logs else [])])
    return FlowQuality(
        value_actions=n, label=label_for(n), empty_warning=empty_warning(signals),
        empty_signals=signals[:6], estimated=False,
        env_warning=env_warning([i.model_dump() for i in run.env_issues]),
    )  # fmt: skip
