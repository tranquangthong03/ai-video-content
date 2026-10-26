"""Flow Discovery: from the explored pages and the confirmed profile to 3-5 core flows.

The LLM proposes (or, in "normalize" mode, structures the user's own description); code then
checks what it cannot be trusted with: the start page was really explored and is not a side page,
the number of steps, real feature ids, unique ids. Landing-only sites get a "value tour" that
never submits anything.
"""

import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from app.browser.form_actions import fold
from app.browser.urls import normalize_url
from app.core.subpages import is_sensitive, is_subpage
from app.llm.json_call import JsonCaller
from app.llm.prompts import render
from app.schemas.generated.core_flow import CoreFlow
from app.schemas.generated.page_insight import PageInsight
from app.schemas.generated.product_profile import ProductProfile

Mode = Literal["propose", "normalize"]
MIN_STEPS, MAX_STEPS = 3, 10
MAX_FLOWS = 5
MAX_DESCRIPTION = 500
LOW_CONFIDENCE = 0.3
LANDING_TYPES = ("landing", "content")


class FlowSet(BaseModel):
    flows: list[CoreFlow] = Field(default_factory=list)


class PageSummary(BaseModel):
    url: str
    title: str = ""
    purpose: str = ""
    actions: list[str] = Field(default_factory=list)
    nav: list[str] = Field(default_factory=list)


def summarize_pages(
    insights: list[PageInsight], nav_by_url: dict[str, list[str]]
) -> list[PageSummary]:
    """One summary per explored page: its insight plus the menu entries seen on it."""
    return [
        PageSummary(
            url=i.url,
            title=i.title,
            purpose=i.purpose,
            actions=[a.name for a in i.actions][:8],
            nav=nav_by_url.get(i.url, [])[:12],
        )
        for i in insights
    ]


def profile_summary(profile: ProductProfile) -> str:
    lines = [
        f"Sản phẩm: {profile.product_name} — {profile.one_liner}",
        f"Loại site: {profile.site_type}",
        "Người dùng mục tiêu: " + "; ".join(profile.target_users),
        "Giá trị chính: " + "; ".join(profile.value_props),
        "Tính năng:",
    ]
    lines += [f"- {f.id}: {f.name} — {f.description}" for f in profile.features]
    return "\n".join(lines)


def pages_text(pages: list[PageSummary]) -> str:
    out = []
    for p in pages:
        parts = [f"- {p.url} | {p.title} | {p.purpose}"]
        if p.actions:
            parts.append("  actions: " + "; ".join(p.actions))
        if p.nav:
            parts.append("  nav: " + "; ".join(p.nav))
        out.append("\n".join(parts))
    return "\n".join(out)


def page_key(url: str) -> str:
    """Scheme-less comparison key: host + path (+ query), no fragment, no trailing slash."""
    norm = normalize_url(url) or url
    parsed = urlparse(norm)
    host = (parsed.hostname or "").removeprefix("www.")
    return f"{host}{parsed.path}?{parsed.query}".rstrip("?")


def start_problem(url: str, scope: set[str]) -> str | None:
    if page_key(url) not in scope:
        return "start_url không thuộc các trang đã khám phá"
    if is_subpage(url) or is_sensitive(url):
        return "start_url là trang đăng nhập/đăng ký/thanh toán/cài đặt"
    return None


def check_flow(flow: CoreFlow, pages: list[PageSummary]) -> list[str]:
    """What is wrong with a proposed flow (empty when it is usable)."""
    problems: list[str] = []
    bad_start = start_problem(flow.start_url, {page_key(p.url) for p in pages})
    if bad_start:
        problems.append(bad_start)
    n = len(flow.expected_steps)
    if not MIN_STEPS <= n <= MAX_STEPS:
        problems.append(f"expected_steps có {n} bước (cần {MIN_STEPS}–{MAX_STEPS})")
    return problems


def _is_side(page: PageSummary) -> bool:
    return is_subpage(page.url, page.title) or is_sensitive(page.url, page.title)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", fold(text)) if len(w) >= 4}


def page_match(text: str, page: PageSummary) -> int:
    """How many words of `text` the page's own address, title, purpose and actions share.
    (The menu is left out on purpose: it is the same on every page.)"""
    path = urlparse(page.url).path.replace("_", " ").replace("-", " ")
    own = _words(" ".join([path, page.title, page.purpose, *page.actions]))
    return len(_words(text) & own)


def nearest_page(text: str, pages: list[PageSummary]) -> PageSummary | None:
    """The explored, non-side page that best matches the description (first one on a tie), if
    any shares a word with it."""
    usable = [p for p in pages if not _is_side(p)]
    best = max(usable, key=lambda p: page_match(text, p), default=None)
    return best if best is not None and page_match(text, best) > 0 else None


def tour_flow(
    profile: ProductProfile, pages: list[PageSummary], flow_id: str = "tour"
) -> CoreFlow | None:
    """A value tour through the explored pages in order; the code's last resort. Never submits."""
    usable = [p for p in pages if not _is_side(p)]
    if not usable:
        return None
    steps = [f"Xem {p.title or p.purpose or p.url}" for p in usable[:MAX_STEPS]]
    while len(steps) < MIN_STEPS:
        steps.append("Cuộn xuống xem thêm nội dung")
    persona = profile.target_users[0] if profile.target_users else "Người dùng mới"
    value = profile.value_props[0] if profile.value_props else profile.one_liner
    return CoreFlow(
        id=flow_id,
        title=f"Tour giá trị {profile.product_name}",
        persona=persona,
        goal=f"Hiểu nhanh {profile.product_name} làm được gì",
        start_url=usable[0].url,
        expected_steps=steps,
        success_signal="Đã xem các phần chính của sản phẩm",
        needs_submit=False,
        value=value,
        confidence=LOW_CONFIDENCE,
        notes="Tạo bằng code: tour qua các trang đã khám phá",
    )


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:24] or "flow"


def clean_flows(
    flows: list[CoreFlow], pages: list[PageSummary], profile: ProductProfile
) -> tuple[list[CoreFlow], list[str]]:
    """Valid flows with unique ids and real feature ids, plus why the others were dropped."""
    valid_features = {f.id for f in profile.features}
    landing = profile.site_type in LANDING_TYPES
    kept: list[CoreFlow] = []
    dropped: list[str] = []
    seen: set[str] = set()
    for flow in flows:
        problems = check_flow(flow, pages)
        if problems:
            dropped.append(f"«{flow.title}»: " + "; ".join(problems))
            continue
        if not flow.id or flow.id in seen:
            flow.id = f"{_slug(flow.title)}_{len(kept) + 1}"
        seen.add(flow.id)
        flow.related_feature_ids = [f for f in flow.related_feature_ids if f in valid_features]
        flow.source = "proposed"
        if landing:
            flow.needs_submit = False
        kept.append(flow)
        if len(kept) == MAX_FLOWS:
            break
    return kept, dropped


def _ask(
    caller: JsonCaller,
    profile: ProductProfile,
    pages: list[PageSummary],
    mode: Mode,
    description: str,
    feedback: str = "",
    avoid: list[tuple[str, str]] | None = None,
) -> list[CoreFlow]:
    prompt = render(
        "flow_discovery",
        product_profile_summary=profile_summary(profile),
        pages_summary=pages_text(pages),
        mode=mode,
        user_description_or_empty=description,
    )
    if feedback:
        prompt += f"\n\nLần trước có lỗi, hãy sửa và trả lại json:\n{feedback}"
    if avoid:  # a second round: what the account cannot do is not offered again
        listed = "\n".join(f"- «{title}»: {why}" for title, why in avoid)
        prompt += (
            f"\n\n<infeasible>\n{listed}\n</infeasible>\n"
            "Các luồng trong <infeasible> không làm được với tài khoản này: KHÔNG đề xuất lại "
            "(kể cả bản diễn đạt khác). Ưu tiên luồng chỉ dùng dữ liệu đã thấy trong pages "
            "(danh sách đã có dữ liệu, form tạo mới không cần dữ liệu có sẵn). Trả về json."
        )
    return caller.call("flow_discovery", prompt, FlowSet).flows


def same_flow(a: str, b: str, threshold: float = 0.8) -> bool:
    """Two titles that name the same flow (accents and case ignored, most words shared)."""
    x, y = set(fold(a).split()), set(fold(b).split())
    return bool(x and y) and len(x & y) / len(x | y) >= threshold


def propose_flows(
    caller: JsonCaller,
    profile: ProductProfile,
    pages: list[PageSummary],
    avoid: list[tuple[str, str]] | None = None,
) -> list[CoreFlow]:
    """3-5 usable flows; one retry with the reasons when none survives, then a code-made tour.

    avoid: (title, why) of flows that cannot be done on this account; they are not offered again."""

    def usable(found: list[CoreFlow]) -> tuple[list[CoreFlow], list[str]]:
        kept, dropped = clean_flows(found, pages, profile)
        again = [f for f in kept if any(same_flow(f.title, t) for t, _ in avoid or [])]
        return [f for f in kept if f not in again], dropped

    flows, dropped = usable(_ask(caller, profile, pages, "propose", "", avoid=avoid))
    if not flows:
        feedback = "\n".join(dropped) or "Không có luồng nào."
        flows, dropped = usable(_ask(caller, profile, pages, "propose", "", feedback, avoid))
    if not flows:
        tour = tour_flow(profile, pages)
        flows = [tour] if tour else []
    if (
        profile.site_type in LANDING_TYPES
        and len(flows) < MAX_FLOWS
        and not any(f.id == "tour" for f in flows)
    ):
        tour = tour_flow(profile, pages)
        if tour:
            flows.append(tour)
    return flows


def normalize_flow(
    caller: JsonCaller, profile: ProductProfile, pages: list[PageSummary], description: str
) -> CoreFlow | None:
    """The user's own description as one CoreFlow (source=user). Unknown screens stay, with low
    confidence; a start page that was not explored falls back to the first usable page."""
    description = description.strip()[:MAX_DESCRIPTION]
    if not description:
        return None
    flows = _ask(caller, profile, pages, "normalize", description)
    if not flows:
        return None
    flow = flows[0]
    flow.source = "user"
    flow.expected_steps = flow.expected_steps[:MAX_STEPS]
    notes: list[str] = [flow.notes] if flow.notes else []
    bad = start_problem(flow.start_url, {page_key(p.url) for p in pages})
    wanted = " ".join([description, flow.title, flow.goal])
    near = nearest_page(wanted, pages)
    if bad:
        fallback = (near.url if near else None) or next(
            (p.url for p in pages if not _is_side(p)), flow.start_url
        )
        notes.append(f"{bad}; dùng {fallback}")
        flow.start_url = fallback
        flow.confidence = min(flow.confidence, LOW_CONFIDENCE)
    elif near and page_match(wanted, near) > 0:
        own = next((p for p in pages if page_key(p.url) == page_key(flow.start_url)), None)
        if (
            own is not None and page_match(wanted, own) == 0
        ):  # the model's pick has nothing to do with it
            notes.append(f"start_url không khớp mô tả; dùng {near.url}")
            flow.start_url = near.url
    if len(flow.expected_steps) < MIN_STEPS:
        notes.append("mô tả ngắn: agent tự bổ sung các bước trung gian")
    if profile.site_type in LANDING_TYPES:
        flow.needs_submit = False
    flow.notes = "; ".join(notes) or None
    flow.id = f"user_{_slug(flow.title)}"
    features = {f.id for f in profile.features}
    flow.related_feature_ids = [f for f in flow.related_feature_ids if f in features]
    return flow
