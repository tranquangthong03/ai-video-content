import pytest
from pydantic import ValidationError

from app.schemas.generated.action import BrowserAction
from app.schemas.generated.core_flow import CoreFlow
from app.schemas.generated.flow_run import FlowRun
from app.schemas.generated.interaction import InteractionRequest
from app.schemas.generated.script import Script

THEME = {
    "primary": "#4F46E5",
    "accent": "#F59E0B",
    "font": "Be Vietnam Pro",
    "motion_preset": "energetic",
    "caption_style": "minimal",
    "music_mood": "upbeat",
    "voice_id": "v",
    "language": "vi",
}
FLOW = {
    "id": "leave", "title": "Xin nghỉ phép", "persona": "Nhân viên", "goal": "Xin nghỉ 2 ngày",
    "start_url": "https://x.test/leave", "expected_steps": ["Mở Leave", "Chọn ngày"],
    "success_signal": "Form đã điền", "needs_submit": True, "value": "Xin nghỉ trong 1 phút",
}  # fmt: skip


def test_core_flow_defaults_and_bounds() -> None:
    flow = CoreFlow.model_validate(FLOW)
    assert flow.source == "proposed" and flow.confidence == 0.7 and flow.related_feature_ids == []
    with pytest.raises(ValidationError):
        CoreFlow.model_validate({**FLOW, "expected_steps": []})
    with pytest.raises(ValidationError):
        CoreFlow.model_validate({**FLOW, "confidence": 1.5})
    with pytest.raises(ValidationError):
        CoreFlow.model_validate({**FLOW, "extra": 1})


@pytest.mark.parametrize("do", ["select", "check", "pick_date", "navigate"])
def test_the_new_actions_are_browser_actions(do: str) -> None:
    assert BrowserAction.model_validate({"do": do, "text": "Annual"}).do == do


def test_flow_run_round_trip() -> None:
    run = FlowRun.model_validate({
        "flow_id": "leave", "status": "stopped_before_submit",
        "steps": [{"i": 1, "action": {"do": "pick_date", "text": "2026-11-02"}, "chapter_id": "c1"}],
        "chapters": [{"id": "c1", "title": "Điền thông tin", "step_ids": [1]}],
    })  # fmt: skip
    assert run.submit_policy == "stop" and run.steps[0].note == "" and run.sample_data == {}
    assert FlowRun.model_validate(run.model_dump(mode="json")) == run
    with pytest.raises(ValidationError):
        FlowRun.model_validate({"flow_id": "x", "status": "done", "steps": [], "chapters": []})


def test_the_new_interaction_kinds_carry_flows_and_the_review() -> None:
    base = {"interaction_id": "i", "job_id": "j", "message": "m", "allowed_actions": ["answer"]}
    ask = InteractionRequest.model_validate({
        **base, "kind": "select_flow", "flows": [FLOW], "flow_select": {"max": 2, "default": ["leave"]},
    })  # fmt: skip
    assert ask.flows and ask.flows[0].id == "leave" and ask.flow_select
    review = InteractionRequest.model_validate({
        **base, "kind": "flow_storyboard_review",
        "flow_review": {"flow_id": "leave", "status": "partial", "steps": [], "chapters": []},
    })  # fmt: skip
    assert review.flow_review and review.flow_review.status == "partial"


def test_script_and_scenes_know_their_flow_and_chapter() -> None:
    scene = {
        "id": "s1", "type": "feature_demo", "layout": "full_screen", "feature": "leave",
        "voiceover": "x", "visual": {"mode": "recording"}, "chapter_id": "c1",
    }  # fmt: skip
    script = Script.model_validate({
        "title": "t", "goal": "awareness", "aspect_ratio": "9:16", "target_duration_s": 30,
        "headline": "h", "theme": THEME, "flow_id": "leave",
        "scenes": [{**scene, "id": f"s{i}"} for i in range(3)],
    })  # fmt: skip
    assert script.flow_id == "leave" and script.scenes[0].root.chapter_id == "c1"
