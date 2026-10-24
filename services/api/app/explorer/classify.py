"""Site type classification: DOM heuristic + one cheap LLM call."""

import json
from typing import Any, Literal

from pydantic import BaseModel

from app.explorer.models import PageData
from app.llm.json_call import JsonCaller, LLMCallError
from app.llm.prompts import render

SiteType = Literal["landing", "web_app", "ecommerce", "tool", "content"]


class SiteClassification(BaseModel):
    site_type: SiteType
    reason: str = ""


def heuristic_site_type(signals: dict[str, Any]) -> tuple[SiteType, float]:
    """(site_type, confidence 0-1) from page signals alone."""
    if signals.get("has_cart"):
        return "ecommerce", 0.8
    if signals.get("big_input") or signals.get("canvas"):
        if signals.get("sections", 0) < 4:
            return "tool", 0.6
    if signals.get("has_sidebar") and signals.get("interactive", 0) > 25:
        return "web_app", 0.6
    if signals.get("sections", 0) >= 4 and signals.get("forms", 0) <= 1:
        return "landing", 0.6
    if signals.get("text_length", 0) > 5000 and signals.get("interactive", 0) < 30:
        return "content", 0.5
    if signals.get("interactive", 0) > 15:
        return "web_app", 0.3
    return "landing", 0.2


def classify_site(caller: JsonCaller, page: PageData) -> tuple[SiteType, str]:
    """LLM verdict with the heuristic as a hint and as the fallback. Returns (site_type, source)."""
    guess, confidence = heuristic_site_type(page.signals)
    prompt = render(
        "site_classifier",
        url=page.url,
        title=page.title,
        meta_description=page.meta_description,
        headings="; ".join(h.text for h in page.headings[:12]),
        signals=json.dumps(page.signals, ensure_ascii=False),
        heuristic=f"{guess} (độ tin cậy {confidence})",
    )
    try:
        return caller.call("classify", prompt, SiteClassification).site_type, "llm"
    except LLMCallError:
        return guess, "heuristic"
