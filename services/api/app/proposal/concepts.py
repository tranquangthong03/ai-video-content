"""choose_concept: propose 3 video directions and read the user's pick."""

from dataclasses import dataclass
from typing import Literal

from app.core.interaction import make_request
from app.llm.json_call import JsonCaller
from app.llm.prompts import render
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
    """Unique ids, only real feature ids, exactly one recommended concept."""
    valid = {f.id for f in profile.features}
    seen: set[str] = set()
    for i, c in enumerate(concepts, start=1):
        if not c.id or c.id in seen:
            c.id = f"c{i}"
        seen.add(c.id)
        c.feature_ids = [f for f in c.feature_ids if f in valid]
    flagged = [c for c in concepts if c.recommended]
    keep = (
        flagged[0] if flagged else next((c for c in concepts if c.angle == "overview"), concepts[0])
    )
    for c in concepts:
        c.recommended = c is keep
    return concepts


def propose_concepts(
    caller: JsonCaller, profile: ProductProfile, notes: str = ""
) -> list[VideoConcept]:
    prompt = render(
        "concept_proposer",
        confirmed_product_profile_json=profile.model_dump_json(indent=1),
        user_notes_or_empty=notes,
    )
    result = caller.call("concepts", prompt, ConceptSet)
    return normalize_concepts(result.concepts, profile)


def build_request(
    job_id: str, concepts: list[VideoConcept], *, notice: str = ""
) -> InteractionRequest:
    message = (
        "Mình đề xuất 3 hướng video. Chọn một hướng (có thể kèm ghi chú) hoặc yêu cầu đề xuất lại."
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
