import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.generated.edit_op import EditOp
from app.schemas.generated.edit_plan import EditPlan
from app.schemas.generated.interaction import InteractionRequest
from app.schemas.generated.scene import Scene
from app.schemas.generated.script import Script
from app.schemas.generated.user_response import UserResponse
from app.script.validate import validate_edit_op, validate_script

EXAMPLES = Path(__file__).resolve().parents[3] / "packages" / "script-schema" / "examples"


def load(name: str) -> dict[str, Any]:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def scene_data(scene_type: str) -> dict[str, Any]:
    scenes = load("sample_script.json")["scenes"]
    return copy.deepcopy(next(s for s in scenes if s["type"] == scene_type))


def test_examples_validate() -> None:
    script = Script.model_validate(load("sample_script.json"))
    assert {s.root.type for s in script.scenes} == {"hook", "feature_demo", "before_after", "cta"}
    assert validate_script(script) == []
    UserResponse.model_validate(load("sample_user_response_edit.json"))
    plan = EditPlan.model_validate(load("sample_edit_plan.json"))
    InteractionRequest.model_validate(load("sample_interaction_script_review.json"))
    for op in plan.ops:
        assert validate_edit_op(op, script) == []


def test_hook_with_wrong_layout_fails() -> None:
    data = scene_data("hook")
    data["layout"] = "split_vertical"
    with pytest.raises(ValidationError):
        Scene.model_validate(data)


def test_hook_with_extra_field_fails() -> None:
    data = scene_data("hook")
    data["before_text"] = "x"
    with pytest.raises(ValidationError):
        Scene.model_validate(data)


@pytest.mark.parametrize(
    ("scene_type", "missing"),
    [("before_after", "after_text"), ("before_after", "before_text"), ("feature_demo", "feature")],
)
def test_required_scene_field_missing_fails(scene_type: str, missing: str) -> None:
    data = scene_data(scene_type)
    del data[missing]
    with pytest.raises(ValidationError):
        Scene.model_validate(data)


def test_scene_count_bounds() -> None:
    data = load("sample_script.json")
    for scenes in (data["scenes"][:2], [{**data["scenes"][0], "id": f"x{i}"} for i in range(7)]):
        with pytest.raises(ValidationError):
            Script.model_validate({**data, "scenes": scenes})


def test_unknown_op_fails() -> None:
    with pytest.raises(ValidationError):
        EditOp.model_validate({"op": "explode", "scene_id": "s1"})
    data = load("sample_edit_plan.json")
    data["ops"].append({"op": "explode"})
    with pytest.raises(ValidationError):
        EditPlan.model_validate(data)


def test_duplicate_scene_id_detected() -> None:
    data = load("sample_script.json")
    data["scenes"][1]["id"] = data["scenes"][0]["id"]
    assert validate_script(Script.model_validate(data))


def test_template_fields_defaults_and_limits() -> None:
    data = load("sample_script.json")
    script = Script.model_validate(data)
    assert script.template == "desktop_showcase" and script.badge == "Quản lý dự án"
    assert script.capture.width in (1920, 1440, 1280) and script.capture.viewport == "desktop"
    assert all(s.root.key_point and s.root.icon for s in script.scenes)
    for key in ("template", "capture", "badge", "headline_highlight"):
        data.pop(key)
    bare = Script.model_validate(data)
    assert bare.template == "desktop_frame" and bare.badge is None
    assert bare.capture.height == 720 and bare.headline_highlight is None


@pytest.mark.parametrize(
    "patch",
    [
        {"headline": "x" * 41},
        {"badge": "x" * 25},
        {"template": "tablet_showcase"},
        {"capture": {"viewport": "tv"}},
        {"theme": {**load("sample_script.json")["theme"], "caption_style": "neon"}},
    ],
)
def test_template_fields_reject_bad_values(patch: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(ValidationError):
        Script.model_validate({**load("sample_script.json"), **patch})


def test_headline_is_required_and_karaoke_is_allowed() -> None:
    data = load("sample_script.json")
    del data["headline"]
    with pytest.raises(ValidationError):
        Script.model_validate(data)
    ok = load("sample_script.json")
    ok["theme"]["caption_style"] = "karaoke"
    assert Script.model_validate(ok).theme.caption_style == "karaoke"


def test_scene_key_point_and_icon_limits() -> None:
    for patch in ({"key_point": "x" * 61}, {"icon": "rocket"}):
        data = load("sample_script.json")
        data["scenes"][0].update(patch)
        with pytest.raises(ValidationError):
            Script.model_validate(data)
    data = load("sample_script.json")
    data["scenes"][0].update(key_point=None, icon=None)
    assert Script.model_validate(data).scenes[0].root.icon is None


def test_headline_highlight_must_be_a_substring_of_the_headline() -> None:
    data = load("sample_script.json")
    assert validate_script(Script.model_validate(data)) == []
    data["headline_highlight"] = "không có trong tiêu đề"
    assert validate_script(Script.model_validate(data))
    data["headline_highlight"] = None
    assert validate_script(Script.model_validate(data)) == []


def test_validate_edit_op_blocks_wrong_layout_and_unknown_scene() -> None:
    script = Script.model_validate(load("sample_script.json"))
    bad = EditOp.model_validate(
        {"op": "set", "scene_id": "s4", "field": "layout", "value": "swipe"}
    )
    assert validate_edit_op(bad, script)
    ok = EditOp.model_validate(
        {"op": "set", "scene_id": "s4", "field": "layout", "value": "logo_center"}
    )
    assert validate_edit_op(ok, script) == []
    ghost = EditOp.model_validate({"op": "move", "scene_id": "s1", "after_scene_id": "nope"})
    assert validate_edit_op(ghost, script)


def test_set_field_must_exist_on_scene_type() -> None:
    script = Script.model_validate(load("sample_script.json"))

    def set_op(scene_id: str, field: str) -> EditOp:
        return EditOp.model_validate(
            {"op": "set", "scene_id": scene_id, "field": field, "value": "x"}
        )

    assert validate_edit_op(set_op("s1", "feature"), script)  # hook has no feature
    assert validate_edit_op(set_op("s2", "feature"), script) == []
    for scene in script.scenes:
        assert validate_edit_op(set_op(scene.root.id, "on_screen_text"), script) == []


def test_list_defaults_are_empty_lists() -> None:
    data = scene_data("feature_demo")
    del data["visual"]["actions"]
    scene = Scene.model_validate(data).root
    assert scene.visual.actions == []

    resp = UserResponse.model_validate(
        {"interaction_id": "i", "job_id": "j", "action": "edit", "edit": {"instruction": "x"}}
    )
    assert resp.edit is not None
    assert resp.edit.ops == [] and resp.edit.targets == []
    # defaults must not be shared between instances
    resp.edit.ops.append(EditOp.model_validate({"op": "delete", "scene_id": "s1"}))
    other = UserResponse.model_validate(
        {"interaction_id": "i", "job_id": "j", "action": "edit", "edit": {}}
    )
    assert other.edit is not None and other.edit.ops == []
