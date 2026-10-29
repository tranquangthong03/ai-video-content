"""Storyboard changes by a sentence: redo (keep nothing) or modify (keep the valid leading steps);
the user's own actions stay the goal of the flow."""

import json
from pathlib import Path

import pytest

from app.core.required_actions import detect, enforce, required_for, validate
from app.flows.storyboard import classify_edit, keep_prefix
from app.schemas.generated.core_flow import CoreFlow
from tests.test_flow_storyboard import make_run

EDITS = json.loads(
    (Path(__file__).parent / "fixtures" / "storyboard_edits.json").read_text("utf-8")
)


@pytest.mark.parametrize("case", EDITS, ids=[c["instruction"][:30] for c in EDITS])
def test_the_sentence_is_a_redo_or_a_change_and_keeps_the_right_prefix(case: dict) -> None:
    run = make_run(tail=False)
    assert classify_edit(case["instruction"]) == case["intent"]
    assert keep_prefix(run, case["instruction"]) == case["keep"]


def test_a_change_never_keeps_a_blank_step_or_what_follows_it() -> None:
    run = make_run(tail=False)
    run.steps[2].blank = True  # step 3: the page stayed empty
    assert keep_prefix(run, "thêm bước xem My Leave") == 2
    run.steps[2].blank = False
    run.steps[3].no_effect = True
    assert keep_prefix(run, "đổi nội dung Comment") == 1  # step 5 lies behind the bad step 4


def test_redo_wins_over_a_named_step_unless_it_only_redoes_a_step() -> None:
    run = make_run(tail=False)
    assert classify_edit("làm lại bước 3") == "modify"
    assert keep_prefix(run, "làm lại bước 4") == 3
    assert classify_edit("bắt đầu lại, bỏ bước 4") == "redo"


def flow(**kw: object) -> CoreFlow:
    data = {
        "id": "f", "title": "Xem chi tiết một mục", "persona": "Khách", "goal": "Xem chi tiết",
        "start_url": "https://x.io/", "expected_steps": ["Mở danh sách", "Mở một mục"],
        "success_signal": "Thấy chi tiết", "needs_submit": False, "value": "v",
    }  # fmt: skip
    return CoreFlow.model_validate({**data, **kw})


def test_commit_verbs_of_the_description_are_found_vi_and_en() -> None:
    assert detect("Chọn một chiếc laptop và thêm vào giỏ hàng") == ["them vao gio"]
    assert detect("Pick a lamp, add to cart and then check out") == ["add to cart", "check out"]
    assert detect("Xem danh sách các dự án") == []


def test_a_model_proposed_action_not_in_the_description_is_dropped() -> None:
    desc = "Chọn laptop và thêm vào giỏ"
    assert validate(["thêm vào giỏ", "đặt hàng", ""], desc) == ["thêm vào giỏ"]
    assert required_for(desc, ["đặt hàng"]) == ["them vao gio"]


def test_the_flow_keeps_the_users_action_even_when_the_model_dropped_it() -> None:
    f = flow()
    desc = "Chọn một chiếc laptop và thêm vào giỏ hàng"
    notes = enforce(f, desc)
    assert f.required_actions == ["them vao gio"]
    assert any("Thực hiện" in s for s in f.expected_steps) and desc in f.goal
    assert notes and "them vao gio" in notes[0]


def test_a_flow_that_already_says_the_action_is_left_alone() -> None:
    f = flow(expected_steps=["Mở danh sách", "Thêm vào giỏ hàng"], goal="Thêm vào giỏ")
    before = list(f.expected_steps)
    assert enforce(f, "thêm vào giỏ") == [] and f.expected_steps == before
