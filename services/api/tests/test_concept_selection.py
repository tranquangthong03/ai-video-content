from pathlib import Path

from app.core.features import restrict_profile
from app.llm.json_call import JsonCaller
from app.proposal.concepts import check_concept, drop_beats, propose_concepts
from app.proposal.outline import outline_from_concept
from app.schemas.generated.video_concept import VideoConcept
from tests.conftest import FakeLLM
from tests.test_explorer import feature, profile

FULL = profile(
    [
        {**feature("create_todo", None, []), "name": "Tạo việc", "demo_kind": "interaction"},
        {**feature("filter_todos", None, []), "name": "Lọc việc", "demo_kind": "interaction"},
        {**feature("export_csv", None, []), "name": "Xuất báo cáo", "demo_kind": "navigation"},
    ]
)
SELECTED = restrict_profile(FULL, ["filter_todos", "create_todo"])  # priority: filter first
OUT = ["Xuất báo cáo"]


def concept_json(i: int, beats: list[str], rec: bool = False) -> dict:  # type: ignore[type-arg]
    return {
        "id": f"c{i}", "angle": ["overview", "deep_dive", "pain_solution"][i - 1], "title": "T",
        "goal": "awareness", "hook_example": "Rối việc?", "feature_ids": ["filter_todos"],
        "duration_s": 30, "beats": beats, "why": "w", "recommended": rec,
    }  # fmt: skip


GOOD = ["Hook rối việc", "Demo Lọc việc", "Demo Tạo việc", "CTA dùng thử"]
BAD = ["Hook rối việc", "Demo Xuất báo cáo", "Demo Tạo việc", "Demo Lọc việc", "CTA dùng thử"]


def caller(tmp_path: Path, responses: list[list[str]]) -> tuple[JsonCaller, FakeLLM]:
    queue = list(responses)

    def handler(prompt: str) -> dict:  # type: ignore[type-arg]
        if prompt.startswith("Bạn là biên kịch"):
            beats = queue.pop(0) if len(queue) > 1 else queue[0]
            return {"concepts": [concept_json(i, beats, i == 1) for i in (1, 2, 3)]}
        return {"items": []}  # shortener: nothing to cut

    llm = FakeLLM(handler)
    return JsonCaller(llm, cache_dir=tmp_path), llm


def test_check_flags_unselected_features_and_wrong_order() -> None:
    c = VideoConcept.model_validate(concept_json(1, BAD))
    bad, problems = check_concept(c, ["Lọc việc", "Tạo việc"], OUT)
    assert bad == {1} and any("Xuất báo cáo" in p for p in problems)
    assert any("thứ tự" in p for p in problems)  # Tạo before Lọc


def test_a_violating_concept_is_repaired_by_a_second_model_call(tmp_path: Path) -> None:
    c, llm = caller(tmp_path, [BAD, GOOD])
    warnings: list[str] = []
    concepts = propose_concepts(c, SELECTED, warnings=warnings, unselected_names=OUT)
    calls = [x["prompt"] for x in llm.calls if x["prompt"].startswith("Bạn là biên kịch")]
    assert len(calls) == 2 and "SỬA LỖI" in calls[1] and "Xuất báo cáo" in calls[1]
    assert all(b == GOOD[i] for c in concepts for i, b in enumerate(c.beats))
    assert not any("Xuất báo cáo" in w for w in warnings)


def test_the_prompt_carries_the_ordered_selection(tmp_path: Path) -> None:
    c, llm = caller(tmp_path, [GOOD])
    propose_concepts(c, SELECTED, unselected_names=OUT)
    prompt = llm.calls[0]["prompt"]
    assert prompt.index("filter_todos") < prompt.index("create_todo")
    assert "<selected_features>" in prompt and "export_csv" not in prompt


def test_beats_still_wrong_after_the_repairs_are_dropped(tmp_path: Path) -> None:
    c, llm = caller(tmp_path, [BAD])
    warnings: list[str] = []
    concepts = propose_concepts(c, SELECTED, warnings=warnings, unselected_names=OUT)
    asked = [x for x in llm.calls if x["prompt"].startswith("Bạn là biên kịch")]
    assert len(asked) == 3  # first try + 2 repairs
    assert all("Demo Xuất báo cáo" not in c.beats and len(c.beats) == 4 for c in concepts)
    assert any("Xuất báo cáo" in w for w in warnings)


def test_a_beat_is_not_dropped_when_fewer_than_four_would_remain() -> None:
    c = VideoConcept.model_validate(concept_json(1, BAD[:4]))
    assert drop_beats(c, {1}) is False and len(c.beats) == 4


def test_budget_and_duration_follow_the_selection_only(tmp_path: Path) -> None:
    c, llm = caller(tmp_path, [GOOD])
    concepts = propose_concepts(c, SELECTED, unselected_names=OUT)
    # hook 4 + cta 4 + before_after 5 + two interaction features 2 * 10 = 33 -> 30 s
    assert {x.duration_s for x in concepts} == {30}


def test_outline_keeps_the_priority_order_of_the_beats() -> None:
    concept = VideoConcept.model_validate(concept_json(1, GOOD))
    outline = outline_from_concept(concept, SELECTED)
    linked = [b.feature_id for b in outline.beats if b.feature_id]
    assert linked == ["filter_todos", "create_todo"]
