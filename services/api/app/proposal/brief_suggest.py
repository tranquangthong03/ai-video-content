"""Ideas for the marketing_brief card: one LLM call from the profile and the approved flow.

The suggestions only point the user in a direction; nothing here is ever put in a video by itself.
If the call fails the card still opens, with generic offers for the kind of site.
"""

from app.flows.discovery import profile_summary
from app.llm.json_call import JsonCaller, LLMCallError
from app.llm.prompts import render
from app.schemas.generated.brief_suggestions import BriefSuggestions
from app.schemas.generated.core_flow import CoreFlow
from app.schemas.generated.flow_run import FlowRun
from app.schemas.generated.product_profile import ProductProfile

PER_FIELD = 3
GENERIC_OFFERS: dict[str, list[str]] = {
    "tool": ["Miễn phí, chạy ngay trên trình duyệt", "Không cần cài đặt", "Dùng thử ngay"],
    "web_app": ["Dùng thử miễn phí", "Xem demo", "Liên hệ tư vấn"],
}
DEFAULT_OFFERS = ["Dùng thử miễn phí", "Xem demo", "Liên hệ tư vấn"]


def flow_summary(flow: CoreFlow | None, run: FlowRun | None = None) -> str:
    """The flow's goal and value come from CoreFlow; the chapters only exist on the run."""
    if flow is None:
        return ""
    chapters = "; ".join(c.title for c in run.chapters) if run is not None else ""
    return f"Luồng chính: {flow.title} — {flow.goal}\nGiá trị: {flow.value}\nCác chương: {chapters}"


def fallback(profile: ProductProfile) -> BriefSuggestions:
    return BriefSuggestions(
        audience=list(profile.target_users[:PER_FIELD]),
        main_benefit=list(profile.value_props[:PER_FIELD]),
        offer=GENERIC_OFFERS.get(profile.site_type, DEFAULT_OFFERS),
    )


def suggest(
    caller: JsonCaller,
    profile: ProductProfile,
    flow: CoreFlow | None = None,
    run: FlowRun | None = None,
) -> tuple[BriefSuggestions, str | None]:
    """(suggestions, a warning when the model could not be used)."""
    prompt = render(
        "brief_suggest",
        product_summary=profile_summary(profile),
        flow_summary=flow_summary(flow, run),
    )
    try:
        got = caller.call("brief_suggest", prompt, BriefSuggestions)
    except LLMCallError as e:
        return fallback(profile), f"Chưa tạo được gợi ý cho brief ({e}); dùng gợi ý chung."
    return (
        BriefSuggestions(
            audience=got.audience[:PER_FIELD],
            main_benefit=got.main_benefit[:PER_FIELD],
            offer=got.offer[:PER_FIELD],
        ),
        None,
    )
