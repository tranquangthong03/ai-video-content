from pathlib import Path
from typing import Any

from app.core.timing import estimate_captions
from app.llm.json_call import JsonCaller
from app.producer.focus_plan import (
    compact_inventory,
    phrases_from_captions,
    plan_focus,
    validate_plan,
)
from app.schemas.generated.focus_plan import FocusPlan
from tests.conftest import FakeLLM


def item(id: str, kind: str, text: str, region: str = "main", new: bool = False) -> dict[str, Any]:
    return {
        "id": id, "role": kind, "tag": "div", "text": text, "kind": kind, "region": region,
        "is_new": new, "bbox": {"x": 0, "y": 0, "w": 100, "h": 40},
    }  # fmt: skip


INV = [
    {
        "t_ms": 300,
        "items": [item("e1", "input", "New todo"), item("e9", "sidebar", "React", "aside")],
    },
    {
        "t_ms": 2500,
        "items": [item("e1", "input", "New todo"), item("e2", "list_item", "Mua sữa", new=True)],
    },
]
ACTIONS = [{"t_ms": 800, "end_ms": 2200, "do": "type", "target_text": "", "item_id": "e1"}]
PHRASES = [{"from_ms": 0, "to_ms": 2000, "text": "Gõ Mua sữa vào ô"}]
GOOD = {
    "plan": [
        {"from_ms": 0, "to_ms": 1000, "item_id": None, "framing": "establish", "reason": "định hướng"},
        {"from_ms": 1000, "to_ms": 2500, "item_id": "e1", "framing": "tight", "reason": "ô nhập"},
        {"from_ms": 2500, "to_ms": 4500, "item_id": "e2", "framing": "medium", "reason": "kết quả"},
    ]
}  # fmt: skip
BAD = {"plan": [{"from_ms": 0, "to_ms": 4500, "item_id": "e404", "framing": "tight", "reason": ""}]}


def call(tmp_path: Path, answers: list[dict[str, Any]]):  # type: ignore[no-untyped-def]
    queue = list(answers)
    llm = FakeLLM(lambda _p: queue.pop(0) if len(queue) > 1 else queue[0])
    result = plan_focus(
        JsonCaller(llm, cache_dir=tmp_path), scene_kind="feature_demo", feature_name="Thêm việc",
        key_point="Gõ và Enter", phrases=PHRASES, actions=ACTIONS, inventory=INV, duration_ms=4500,
    )  # fmt: skip
    return result, llm


def test_a_valid_plan_comes_back_as_dicts_after_one_call(tmp_path: Path) -> None:
    result, llm = call(tmp_path, [GOOD])
    assert result.attempts == 1 and result.errors == []
    assert result.plan is not None and result.plan[1]["item_id"] == "e1"
    assert len(llm.calls) == 1


def test_the_prompt_carries_phrases_actions_inventory_and_the_scene(tmp_path: Path) -> None:
    _, llm = call(tmp_path, [GOOD])
    prompt = llm.calls[0]["prompt"]
    for expected in ("Gõ Mua sữa vào ô", '"item_id": "e1"', "Mua sữa", "Thêm việc", "Gõ và Enter"):
        assert expected in prompt
    assert '"bbox"' not in prompt  # coordinates stay out of the model's view


def test_an_item_that_is_not_in_the_inventory_gets_one_repair_round(tmp_path: Path) -> None:
    result, llm = call(tmp_path, [BAD, GOOD])
    assert result.plan is not None and result.attempts == 2
    assert "e404" in llm.calls[1]["prompt"]  # the error was sent back


def test_a_plan_that_stays_wrong_is_dropped(tmp_path: Path) -> None:
    result, llm = call(tmp_path, [BAD])
    assert result.plan is None and result.attempts == 2 and len(llm.calls) == 2
    assert any("e404" in e for e in result.errors)


def test_validation_catches_order_overrun_and_establish_with_an_item() -> None:
    plan = FocusPlan.model_validate(
        {
            "plan": [
                {"from_ms": 0, "to_ms": 2000, "item_id": "e1", "framing": "establish"},
                {"from_ms": 1000, "to_ms": 9000, "item_id": None, "framing": "wide"},
            ]
        }
    )
    errors = validate_plan(plan, INV, 4500)
    assert any("establish" in e for e in errors)
    assert any("overlap" in e for e in errors)
    assert any("past the clip" in e for e in errors)
    assert validate_plan(FocusPlan.model_validate({"plan": []}), INV, 4500) == ["plan is empty"]


def test_no_inventory_means_no_call(tmp_path: Path) -> None:
    llm = FakeLLM(lambda _p: GOOD)
    result = plan_focus(
        JsonCaller(llm, cache_dir=tmp_path), scene_kind="hook", feature_name="", key_point="k",
        phrases=[], actions=[], inventory=[], duration_ms=3000,
    )  # fmt: skip
    assert result.plan is None and llm.calls == []


def test_identical_snapshots_are_dropped_and_the_rest_thinned() -> None:
    same = [{"t_ms": t, "items": [item("e1", "input", "x")]} for t in range(0, 5000, 500)]
    assert len(compact_inventory(same)) == 1
    many = [{"t_ms": t, "items": [item(f"e{t}", "input", "x")]} for t in range(40)]
    assert len(compact_inventory(many)) == 14


def test_phrases_follow_the_caption_groups_on_the_clip_axis() -> None:
    captions = estimate_captions("Gõ Mua sữa vào ô nhập rồi nhấn Enter", 0, 3000)
    phrases = phrases_from_captions(captions, rate=1.0)
    assert [p["text"] for p in phrases] == [c["text"] for c in captions]
    fast = phrases_from_captions(captions, rate=1.15)
    assert fast[-1]["to_ms"] == round(captions[-1]["end_ms"] * 1.15)
