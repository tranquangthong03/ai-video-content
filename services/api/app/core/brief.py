"""The marketing brief: what the user tells us that the website does not (pure helpers, no I/O
besides the one json file in the job dir).

Every field is optional. `skip` keeps the old behaviour: the copy leans on the site alone. What the
user gives is trusted as sourced («source = user»): numbers in proof_points may appear in the video.
"""

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from app.core.interaction import make_request
from app.schemas.generated.brief_suggestions import BriefSuggestions
from app.schemas.generated.interaction import InteractionRequest
from app.schemas.generated.marketing_brief import MarketingBrief

BRIEF_FILE = "marketing_brief.json"
SKIPPED = {"skipped": True}
MAX_TEXT = 200
MAX_LIST = 6
MAX_POINTS = 5
NUMBER = re.compile(r"^\s*(\d[\d.,]*)\s*(\S.*)?$")

NOTE = "Chỉ nhập số liệu có thật — số liệu sẽ xuất hiện trong video."
MESSAGE = (
    "Website không nói hết những điều làm video thuyết phục. Bạn có thể bổ sung đối tượng, "
    "lợi ích chính, số liệu thật và ưu đãi (mọi ô tùy chọn); «Bỏ qua» để video chỉ dựa vào website."
)


def _text(value: str | None) -> str | None:
    cleaned = re.sub(r"\s+", " ", value or "").strip()[:MAX_TEXT]
    return cleaned or None


def _texts(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        cleaned = _text(v)
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out[:MAX_LIST]


def clean_brief(brief: MarketingBrief) -> MarketingBrief:
    """Tidy what the user typed: trimmed texts, a number and its unit apart ("40%" -> 40 + %),
    no point without both a number and a sentence, no repeats."""
    points = []
    seen: set[tuple[str, str]] = set()
    for p in brief.proof_points:
        claim = _text(p.claim)
        value, unit = (p.value or "").strip(), _text(p.unit)
        m = NUMBER.match(value)
        if m:
            value, unit = m.group(1), unit or _text(m.group(2))
        if not claim or not re.search(r"\d", value) or (value, unit or "") in seen:
            continue
        seen.add((value, unit or ""))
        points.append(
            p.model_copy(update={"value": value, "unit": unit, "claim": claim,
                                 "source_note": _text(p.source_note)})
        )  # fmt: skip
    return MarketingBrief(
        audience=_text(brief.audience),
        main_benefit=_text(brief.main_benefit),
        secondary_benefits=_texts(brief.secondary_benefits),
        proof_points=points[:MAX_POINTS],
        offer=_text(brief.offer),
        cta_text=_text(brief.cta_text),
        cta_url=_text(brief.cta_url),
        tone=_text(brief.tone),
        avoid=_texts(brief.avoid),
    )


def is_empty(brief: MarketingBrief | None) -> bool:
    return brief is None or not (
        brief.audience or brief.main_benefit or brief.secondary_benefits or brief.proof_points
        or brief.offer or brief.cta_text or brief.cta_url or brief.tone or brief.avoid
    )  # fmt: skip


def save_brief(job_dir: Path, brief: MarketingBrief | None) -> None:
    """The brief, or the mark that the user skipped (so a resumed job does not ask again)."""
    data = SKIPPED if is_empty(brief) else brief.model_dump(mode="json")  # type: ignore[union-attr]
    (job_dir / BRIEF_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def read_brief_file(path: Path) -> MarketingBrief:
    """A brief from a json file: the brief itself, or {"brief": {...}} with notes beside it
    (the keys that start with an underscore, e.g. a warning that it is test data)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return MarketingBrief.model_validate(data["brief"] if "brief" in data else data)


def asked(job_dir: Path) -> bool:
    return (job_dir / BRIEF_FILE).is_file()


def load_brief(job_dir: Path) -> MarketingBrief | None:
    """None when there is no brief (never asked, or skipped)."""
    file = job_dir / BRIEF_FILE
    if not file.is_file():
        return None
    data = json.loads(file.read_text(encoding="utf-8"))
    if data.get("skipped"):
        return None
    return MarketingBrief.model_validate(data)


def cta_domain(brief: MarketingBrief | None) -> str | None:
    """The short address the closing scene shows, from the brief's cta_url."""
    if brief is None or not brief.cta_url:
        return None
    raw = brief.cta_url.strip()
    host = urlparse(raw if "//" in raw else f"//{raw}").hostname or ""
    return host.removeprefix("www.") or None


def prompt_text(brief: MarketingBrief | None) -> str:
    """The brief as lines for a prompt ('' when there is none)."""
    if is_empty(brief):
        return ""
    assert brief is not None
    lines: list[str] = []
    if brief.audience:
        lines.append(f"- Đối tượng: {brief.audience}")
    if brief.main_benefit:
        lines.append(f"- Lợi ích chính: {brief.main_benefit}")
    for b in brief.secondary_benefits:
        lines.append(f"- Lợi ích phụ: {b}")
    for p in brief.proof_points:
        unit = f" {p.unit}" if p.unit else ""
        lines.append(f"- Số liệu thật (người dùng cam kết): {p.value}{unit} — {p.claim}")
    if brief.offer:
        lines.append(f"- Ưu đãi / lý do hành động ngay: {brief.offer}")
    if brief.cta_text:
        lines.append(f"- Lời kêu gọi: {brief.cta_text}")
    if brief.cta_url:
        lines.append(f"- Địa chỉ hiện ở cảnh cuối: {cta_domain(brief) or brief.cta_url}")
    if brief.tone:
        lines.append(f"- Giọng điệu: {brief.tone}")
    if brief.avoid:
        lines.append("- Tránh nói: " + "; ".join(brief.avoid))
    return "\n".join(lines)


def build_request(
    job_id: str, suggestions: BriefSuggestions, draft: MarketingBrief | None = None
) -> InteractionRequest:
    return make_request(
        job_id,
        "marketing_brief",
        MESSAGE,
        brief_form={"suggestions": suggestions.model_dump(), "note": NOTE,
                    "draft": draft.model_dump() if draft else None},
    )  # fmt: skip
