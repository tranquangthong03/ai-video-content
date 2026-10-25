"""choose_concept: propose 3 video directions and read the user's pick."""

import json
from dataclasses import dataclass
from typing import Literal

from app.core.budget import budget_for
from app.core.features import fold
from app.core.interaction import make_request
from app.llm.json_call import JsonCaller
from app.llm.prompts import render
from app.proposal.wordlimit import enforce_concepts
from app.schemas.generated.concept_set import ConceptSet
from app.schemas.generated.interaction import InteractionRequest
from app.schemas.generated.product_profile import ProductProfile
from app.schemas.generated.user_response import UserResponse
from app.schemas.generated.video_concept import VideoConcept


@dataclass
class ConceptDecision:
    kind: Literal["chosen", "regenerate", "cancel"]
    concept: VideoConcept | None = None
    notes: str = ""


def normalize_concepts(concepts: list[VideoConcept], profile: ProductProfile) -> list[VideoConcept]:
    """Unique ids, only real feature ids, the recommended duration, exactly one recommended one."""
    valid = {f.id for f in profile.features}
    recommended_s = budget_for(profile).recommended_duration_s
    seen: set[str] = set()
    for i, c in enumerate(concepts, start=1):
        if not c.id or c.id in seen:
            c.id = f"c{i}"
        seen.add(c.id)
        c.feature_ids = [f for f in c.feature_ids if f in valid]
        c.duration_s = recommended_s  # type: ignore[assignment]  # code decides; the LLM may not
    flagged = [c for c in concepts if c.recommended]
    keep = (
        flagged[0] if flagged else next((c for c in concepts if c.angle == "overview"), concepts[0])
    )
    for c in concepts:
        c.recommended = c is keep
    return concepts


MAX_REPAIRS = 2
MIN_NAME_LEN = 4  # shorter feature names are too generic to spot in a beat
MIN_BEATS = 4


def mentions(text: str, names: list[str]) -> list[str]:
    """The names (accents and case ignored) that appear in a beat."""
    hay = fold(text)
    return [n for n in names if len(fold(n)) >= MIN_NAME_LEN and fold(n) in hay]


def check_concept(
    concept: VideoConcept, selected_names: list[str], unselected_names: list[str]
) -> tuple[set[int], list[str]]:
    """(indexes of beats naming a feature outside the selection, all problems as text).

    Also checks the priority order: selected features must first show up in the order picked.
    """
    bad: set[int] = set()
    problems: list[str] = []
    for i, beat in enumerate(concept.beats):
        for name in mentions(beat, unselected_names):
            bad.add(i)
            problems.append(f"beat {i + 1} nhắc tới «{name}», tính năng người dùng KHÔNG chọn")
    first_seen: dict[str, int] = {}
    for i, beat in enumerate(concept.beats):
        for name in mentions(beat, selected_names):
            first_seen.setdefault(name, i)
    seen_order = [n for n in selected_names if n in first_seen]
    if sorted(seen_order, key=lambda n: first_seen[n]) != seen_order:
        problems.append("thứ tự demo phải theo ưu tiên người dùng: " + " → ".join(selected_names))
    return bad, problems


def drop_beats(concept: VideoConcept, bad: set[int]) -> bool:
    """Remove the offending beats; refuses (False) when fewer than MIN_BEATS would be left."""
    if not bad or len(concept.beats) - len(bad) < MIN_BEATS:
        return False
    concept.beats = [b for i, b in enumerate(concept.beats) if i not in bad]
    return True


def propose_concepts(
    caller: JsonCaller,
    profile: ProductProfile,
    notes: str = "",
    warnings: list[str] | None = None,
    *,
    unselected_names: list[str] | None = None,
) -> list[VideoConcept]:
    """`profile` holds only the selected features, in priority order (restrict_profile).

    Beats that name a feature the user did not select go through up to MAX_REPAIRS repair rounds
    (the problems are sent back to the model); beats still wrong are dropped.
    """
    unselected = unselected_names or []
    selected_names = [f.name for f in profile.features]
    budget = budget_for(profile)
    selected_json = json.dumps(
        [{"id": f.id, "name": f.name, "demo_kind": f.demo_kind} for f in profile.features],
        ensure_ascii=False,
    )
    guidance = notes
    for attempt in range(MAX_REPAIRS + 1):
        prompt = render(
            "concept_proposer",
            confirmed_product_profile_json=profile.model_dump_json(indent=1),
            selected_features_json=selected_json,
            user_notes_or_empty=guidance,
            recommended_duration_s=budget.recommended_duration_s,
        )
        result = caller.call("concepts", prompt, ConceptSet)
        concepts = normalize_concepts(result.concepts, profile)
        checks = [check_concept(c, selected_names, unselected) for c in concepts]
        problems = [f"{c.id}: {p}" for c, (_, ps) in zip(concepts, checks, strict=True) for p in ps]
        if not problems or attempt == MAX_REPAIRS:
            break
        fixes = "; ".join(problems)
        guidance = f"{notes}\nSỬA LỖI lần trước (giữ nguyên phần đúng): {fixes}"
    for c, (bad, ps) in zip(concepts, checks, strict=True):
        dropped = drop_beats(c, bad)
        if warnings is not None:
            warnings += [f"{c.id}: {p}" for p in ps]
            if bad and not dropped:
                warnings.append(f"{c.id}: không bỏ được beat sai vì dưới {MIN_BEATS} beat")
    found = enforce_concepts(caller, concepts)  # hook <= 12 words, beats <= 15
    if warnings is not None:
        warnings.extend(found)
    return concepts


def build_request(
    job_id: str, concepts: list[VideoConcept], *, notice: str = ""
) -> InteractionRequest:
    message = (
        "Mình đề xuất 3 hướng video. Chọn một hướng (có thể kèm ghi chú) hoặc yêu cầu đề xuất lại."
    )
    if concepts:
        message += (
            f" Thời lượng đề xuất: {concepts[0].duration_s}s (theo số tính năng trình diễn được)."
        )
    return make_request(
        job_id,
        "choose_concept",
        f"{notice}\n{message}" if notice else message,
        concepts=[c.model_dump() for c in concepts],
        questions=[
            {
                "id": "concept_id",
                "text": "Bạn chọn hướng nào?",
                "type": "single",
                "options": [{"id": c.id, "label": c.title, "description": c.why} for c in concepts],
                "allow_custom": False,
            },
            {
                "id": "notes",
                "text": "Ghi chú thêm (thời lượng, mục tiêu, thêm/bỏ tính năng...)",
                "type": "text",
                "options": [],
                "allow_custom": True,
            },
        ],
    )


def read_decision(concepts: list[VideoConcept], response: UserResponse) -> ConceptDecision:
    answers = response.answers or {}
    raw_notes = answers.get("notes", "")
    notes = raw_notes if isinstance(raw_notes, str) else " ".join(raw_notes)
    if response.action == "cancel":
        return ConceptDecision("cancel")
    if response.action == "regenerate":
        return ConceptDecision("regenerate", notes=notes)
    pick = answers.get("concept_id")
    pick = pick[0] if isinstance(pick, list) and pick else pick
    chosen: VideoConcept | None = None
    if pick == "recommended":
        chosen = next((c for c in concepts if c.recommended), None)
    elif isinstance(pick, str) and pick.isdigit() and 1 <= int(pick) <= len(concepts):
        chosen = concepts[int(pick) - 1]
    elif isinstance(pick, str):
        chosen = next((c for c in concepts if c.id == pick), None)
    if chosen is None:
        raise ValueError(f"unknown concept_id: {pick!r}")
    return ConceptDecision("chosen", chosen, notes)
