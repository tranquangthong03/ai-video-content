"""goal_status is computed by code from the actions the user asked for and the real steps."""

from typing import Any

from app.core.commit_verbs import commit_group, is_strong_commit
from app.core.goal_status import goal_status
from app.schemas.generated.core_flow import CoreFlow
from app.schemas.generated.flow_run import FlowRun


def flow(required: list[str]) -> CoreFlow:
    return CoreFlow.model_validate(
        {
            "id": "f", "title": "Mua một món", "persona": "Khách", "goal": "Thêm vào giỏ",
            "start_url": "https://x.io/", "expected_steps": ["Mở danh mục", "Thêm vào giỏ"],
            "success_signal": "Giỏ có món", "needs_submit": True, "value": "v",
            "required_actions": required,
        }
    )  # fmt: skip


def run(rows: list[tuple[str, str]], status: str, **flags: Any) -> FlowRun:
    steps = [
        {
            "i": i, "action": {"do": do}, "target_text": name, "note": f"Bước {i}",
            **(flags if i == flags.get("at", -1) else {}),
        }
        for i, (do, name) in enumerate(rows, start=1)
    ]  # fmt: skip
    for s in steps:
        s.pop("at", None)
    return FlowRun.model_validate(
        {"flow_id": "f", "status": status, "steps": steps, "chapters": []}
    )


VIEW_ONLY = [("goto", ""), ("navigate", "Laptops"), ("navigate", "MacBook Pro")]
CART = ["them vao gio"]


def test_a_flow_that_only_views_a_detail_is_not_reached_whatever_the_model_says() -> None:
    assert goal_status(flow(CART), run(VIEW_ONLY, "reached_goal")) == "not_reached"


def test_stopping_at_the_matching_button_is_stopped_before_submit() -> None:
    rows = [*VIEW_ONLY, ("hover", "Add to cart"), ("highlight", "Add to cart")]
    assert goal_status(flow(CART), run(rows, "stopped_before_submit")) == "stopped_before_submit"


def test_stopping_at_another_button_is_not_the_goal() -> None:
    rows = [*VIEW_ONLY, ("hover", "Buy now"), ("highlight", "Buy now")]
    assert goal_status(flow(CART), run(rows, "stopped_before_submit")) == "not_reached"


def test_the_commit_really_done_is_reached() -> None:
    rows = [*VIEW_ONLY, ("click", "Add to cart")]
    assert goal_status(flow(CART), run(rows, "reached_goal")) == "reached"


def test_a_blank_or_no_effect_step_before_the_stop_means_not_reached() -> None:
    rows = [*VIEW_ONLY, ("hover", "Add to cart"), ("highlight", "Add to cart")]
    assert goal_status(flow(CART), run(rows, "stopped_before_submit", at=3, blank=True)) == (
        "not_reached"
    )
    rows = [*VIEW_ONLY, ("click", "Add to cart")]
    assert goal_status(flow(CART), run(rows, "reached_goal", at=4, no_effect=True)) == "not_reached"


def test_without_a_named_action_the_end_of_the_run_decides() -> None:
    assert goal_status(flow([]), run(VIEW_ONLY, "reached_goal")) == "reached"
    assert goal_status(flow([]), run(VIEW_ONLY, "partial")) == "not_reached"
    rows = [*VIEW_ONLY, ("hover", "Save"), ("highlight", "Save")]
    assert goal_status(flow([]), run(rows, "stopped_before_submit")) == "stopped_before_submit"


def test_the_same_commitment_in_other_words_matches() -> None:
    assert commit_group("Add to cart") == commit_group("Thêm vào giỏ") == "cart"
    assert commit_group("Đặt hàng") == commit_group("Place order") == "order"
    assert commit_group("Lưu") == commit_group("Save changes") == "save"
    assert is_strong_commit("Add to basket") and not is_strong_commit("Save")
