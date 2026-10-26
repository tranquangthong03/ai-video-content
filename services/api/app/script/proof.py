"""Proof bank: the real numbers, quotes, offers and pains a video may lean on (pure functions).

Everything the writer says as a fact must come from here or from the frames of the filmed flow;
`unsupported_numbers` is how the code checks it, `strip_numbers` is the last resort when the
model keeps a number nobody can source.
"""

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from app.browser.form_actions import fold
from app.schemas.generated.product_profile import ProductProfile

MAX_QUOTE_CHARS = 120
MIN_QUOTE_CHARS = 20
MAX_NUMBERS, MAX_QUOTES, MAX_PAINS = 12, 8, 4
CONTEXT_CHARS = 40

# 2.8MB, 40%, 1,000, 3 bước, 10x ...: the number, then an optional known unit
UNITS = (
    r"%|KB|MB|GB|TB|ms|px|x|k|giây|phút|giờ|ngày|tuần|tháng|năm|lần|bước|phần trăm|"
    r"seconds?|minutes?|hours?|days?|weeks?|months?|years?|times|steps?|users?|người|ảnh|trang"
)
NUMBER_RE = re.compile(
    rf"(?<![\w.])(\d{{1,3}}(?:[.,]\d{{3}})+|\d+(?:[.,]\d+)?)(?:\s?({UNITS})(?![\wà-ỹ]))?",
    re.IGNORECASE,
)

# folded keyword -> (offer id, label shown to the writer)
OFFER_PATTERNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("free", "miễn phí", ("free", "mien phi", "gratis")),
    ("trial", "dùng thử", ("free trial", "dung thu", "try for free", "try it free")),
    ("open_source", "mã nguồn mở", ("open source", "open-source", "ma nguon mo")),
    ("no_card", "không cần thẻ", ("no credit card", "khong can the", "no card")),
    ("no_install", "không cần cài đặt", ("no install", "khong can cai dat", "in your browser",
                                         "trong trinh duyet", "in the browser")),
    ("no_signup", "không cần đăng ký", ("no sign up", "no signup", "khong can dang ky",
                                        "without signing up")),
    ("private", "xử lý ngay trên máy bạn", ("never leave your device", "locally", "tren thiet bi",
                                            "khong roi khoi may")),
)  # fmt: skip

PAIN_MARKERS = ("worried", "tired of", "slow", "hassle", "struggle", "waste", "painful", "lo ",
                "mat thoi gian", "cham", "kho khan", "phien", "met moi", "rac roi")  # fmt: skip


@dataclass(frozen=True)
class NumberFact:
    value: str  # as written, e.g. "2.8"
    unit: str  # "MB", "%", "" ...
    context: str  # the words around it
    source: str  # where it was read: profile / page:<url> / frame


@dataclass(frozen=True)
class Offer:
    id: str
    label: str
    source_text: str


@dataclass
class ProofBank:
    numbers: list[NumberFact] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)
    offers: list[Offer] = field(default_factory=list)
    audience_pains: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.numbers or self.quotes or self.offers)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def norm_number(raw: str) -> str:
    """'1,000' / '1.000' -> '1000'; '2,8' -> '2.8'; '2.80' -> '2.8' (comparison key)."""
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", raw):
        return re.sub(r"[.,]", "", raw)
    value = raw.replace(",", ".")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    return value


def numbers_in(text: str) -> list[tuple[str, str, int, int]]:
    """(normalized value, unit, start, end) of every number written in the text."""
    found = []
    for m in NUMBER_RE.finditer(text):
        found.append((norm_number(m.group(1)), m.group(2) or "", m.start(), m.end()))
    return found


def _texts_of_profile(profile: ProductProfile) -> list[str]:
    texts = [profile.one_liner, *profile.value_props]
    for f in profile.features:
        texts += [f.name, f.description]
        texts += [e.quote for e in f.evidence if e.quote and e.source != "app_action"]
    return [t for t in texts if t]


def _texts_of_page(page: dict[str, Any]) -> list[str]:
    texts = [
        page.get("title", ""),
        page.get("meta_description", ""),
        page.get("og_description", ""),
    ]
    texts += [
        h.get("text", "") if isinstance(h, dict) else str(h) for h in page.get("headings", [])
    ]
    texts += [str(t) for t in page.get("key_texts", [])]
    return [t for t in texts if t]


def frame_texts(inventory: Iterable[dict[str, Any]]) -> list[str]:
    """Visible texts of the frame inventory (snapshots of {t_ms, items: [{text, ...}]})."""
    return [
        str(item["text"])
        for snap in inventory
        for item in snap.get("items", [])
        if item.get("text")
    ]


def _quote_ok(text: str) -> bool:
    text = text.strip()
    return MIN_QUOTE_CHARS <= len(text) <= MAX_QUOTE_CHARS and " " in text


def build_proof_bank(
    profile: ProductProfile | None,
    pages: Iterable[dict[str, Any]] = (),
    inventory: Iterable[dict[str, Any]] = (),
) -> ProofBank:
    """Read the facts a video may use from the confirmed profile, explored pages and flow frames."""
    sources: list[tuple[str, str]] = []  # (source label, text)
    if profile is not None:
        sources += [("profile", t) for t in _texts_of_profile(profile)]
    page_list = list(pages)
    for page in page_list:
        sources += [(f"page:{page.get('url', '')}", t) for t in _texts_of_page(page)]
    sources += [("frame", t) for t in frame_texts(inventory)]

    bank = ProofBank()
    seen_numbers: set[tuple[str, str]] = set()
    for label, text in sources:
        for value, unit, start, end in numbers_in(text):
            if (value, unit) in seen_numbers or len(bank.numbers) >= MAX_NUMBERS:
                continue
            seen_numbers.add((value, unit))
            ctx = text[max(0, start - CONTEXT_CHARS) : end + CONTEXT_CHARS].strip()
            bank.numbers.append(NumberFact(value, unit, ctx, label))

    # verbatim quotes only: page texts and claims the site makes, never our own summaries
    quote_sources = [t for page in page_list for t in _texts_of_page(page)]
    if profile is not None:
        quote_sources += [
            e.quote
            for f in profile.features
            for e in f.evidence
            if e.quote and e.source == "landing_claim"
        ]
    for text in quote_sources:
        if _quote_ok(text) and text.strip() not in bank.quotes and len(bank.quotes) < MAX_QUOTES:
            bank.quotes.append(text.strip())

    all_texts = [t for _, t in sources]
    for offer_id, label, keys in OFFER_PATTERNS:
        hit = next((t for t in all_texts if any(k in fold(t) for k in keys)), None)
        if hit:
            bank.offers.append(Offer(offer_id, label, hit.strip()[:MAX_QUOTE_CHARS]))

    for text in all_texts:
        if len(bank.audience_pains) >= MAX_PAINS:
            break
        folded = fold(text) + " "
        if _quote_ok(text) and any(k in folded for k in PAIN_MARKERS):
            if text.strip() not in bank.audience_pains:
                bank.audience_pains.append(text.strip())
    return bank


def proof_used(text: str, proof: ProofBank) -> bool:
    """Does the text lean on the proof bank: a sourced number, an offer, or a phrase of a quote?"""
    if proof.is_empty:
        return True  # nothing to lean on
    folded = fold(text)
    if any(v in {n.value for n in proof.numbers} for v, *_ in numbers_in(text)):
        return True
    if any(fold(o.label) in folded for o in proof.offers):
        return True
    for quote in proof.quotes:
        words = fold(quote).split()
        if any(" ".join(words[i : i + 4]) in folded for i in range(max(1, len(words) - 3))):
            return True
    return False


def supported_values(proof: ProofBank, inventory: Iterable[dict[str, Any]] = ()) -> set[str]:
    values = {n.value for n in proof.numbers}
    for text in frame_texts(inventory):
        values |= {v for v, *_ in numbers_in(text)}
    return values


def unsupported_numbers(
    text: str,
    proof: ProofBank,
    inventory: Iterable[dict[str, Any]] = (),
    extra: Iterable[str] = (),
) -> list[str]:
    """Numbers written in `text` that no source backs (`extra`: counts the flow itself gives,
    e.g. the number of steps). Returns them as written, in order, without repeats."""
    ok = supported_values(proof, inventory) | {norm_number(e) for e in extra}
    bad: list[str] = []
    for value, _unit, start, end in numbers_in(text):
        if value not in ok:
            written = text[start:end].strip()
            if written not in bad:
                bad.append(written)
    return bad


def strip_numbers(text: str, bad: Iterable[str]) -> str:
    """Remove unsourced numbers (with their unit) from the text and tidy the gap they leave."""
    for written in bad:
        text = re.sub(rf"(?<![\w.]){re.escape(written)}", "", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return re.sub(r"\s{2,}", " ", text).strip()
