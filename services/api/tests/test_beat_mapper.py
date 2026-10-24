import json
from pathlib import Path
from typing import Any

from app.llm.json_call import JsonCaller
from app.proposal.beat_mapper import map_beats, needs_mapping, summarize_steps
from app.schemas.generated.outline import Outline
from app.schemas.generated.product_profile import ProductProfile
from tests.conftest import FakeLLM, _section
from tests.test_explorer import feature, profile

URL = "https://todo.example/"


def todo_profile() -> ProductProfile:
    def step(do: str, name: str | None = None, text: str | None = None) -> dict[str, Any]:
        locator = {"name": name} if name else None
        return {"do": do, "url": URL, "text": text, "locator": locator}

    def feat(fid: str, name: str, kind: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
        return {**feature(fid, None, steps, url=URL), "name": name, "demo_kind": kind}

    return profile(
        [
            feat(
                "create-todo",
                "Tạo việc cần làm",
                "interaction",
                [step("type", "What needs to be done?", "Buy milk")],
            ),
            feat("edit-todo", "Sửa việc tại chỗ", "interaction", [step("dblclick", "Buy milk")]),
            feat("filter-todos", "Lọc theo trạng thái", "interaction", [step("click", "Active")]),
            feat("about", "Giới thiệu", "failed", []),
        ]
    )


def todo_outline(**patch: Any) -> Outline:
    """The approved todomvc outline: the middle beats carry no feature_id."""
    data: dict[str, Any] = {
        "concept_id": "overview-fast-add",
        "title": "Thêm việc trong 2 giây, sửa ngay tại chỗ",
        "goal": "awareness",
        "duration_s": 30,
        "feature_ids": ["create-todo", "edit-todo"],
        "version": 2,
        "beats": [
            {
                "id": "b1",
                "text": "Bạn có hay quên những việc cần làm mỗi ngày?",
                "feature_id": None,
            },
            {
                "id": "b2",
                "text": "Gõ 'Buy milk', nhấn Enter — việc xuất hiện ngay trong danh sách.",
            },
            {
                "id": "b3",
                "text": "Muốn sửa? Nhấp đúp vào việc, chỉnh tại chỗ, không cần form riêng.",
            },
            {"id": "b4", "text": "Giao diện tối giản, chỉ tập trung vào danh sách việc cần làm."},
            {"id": "b5", "text": "Thử ngay tại todomvc.com/examples/react/dist"},
        ],
    }
    return Outline.model_validate({**data, **patch})


def caller_for(
    mapping: list[dict[str, Any]] | dict[str, Any], tmp_path: Path
) -> tuple[JsonCaller, FakeLLM]:
    llm = FakeLLM(lambda _p: mapping if isinstance(mapping, dict) else {"mapping": mapping})
    return JsonCaller(llm, cache_dir=tmp_path), llm


def row(beat: str, feature_id: str | None, confidence: float = 0.9) -> dict[str, Any]:
    return {"beat_id": beat, "feature_id": feature_id, "confidence": confidence, "reason": "r"}


def links(outline: Outline) -> dict[str, str | None]:
    return {b.id: b.feature_id for b in outline.beats}


def test_the_todomvc_outline_gets_create_on_b2_and_edit_on_b3_and_nothing_on_the_cta(
    tmp_path: Path,
) -> None:
    caller, _ = caller_for(
        [
            row("b1", "create-todo"),  # the model slips: hook linked
            row("b2", "create-todo"),
            row("b3", "edit-todo"),
            row("b4", None),
            row("b5", "create-todo"),  # the model slips: CTA linked
        ],
        tmp_path,
    )
    result = map_beats(caller, todo_profile(), todo_outline())
    assert links(result.outline) == {
        "b1": None, "b2": "create-todo", "b3": "edit-todo", "b4": None, "b5": None,
    }  # fmt: skip
    assert any("b1" in w for w in result.warnings) and any("b5" in w for w in result.warnings)
    assert result.changes == [
        "Gắn b2 với «Tạo việc cần làm»",
        "Gắn b3 với «Sửa việc tại chỗ»",
    ]
    assert [m["beat_id"] for m in result.mapping] == ["b1", "b2", "b3", "b4", "b5"]
    assert result.outline.version == 2  # linking does not count as an edit


def test_the_prompt_carries_the_outline_and_what_each_feature_demonstrates(tmp_path: Path) -> None:
    caller, llm = caller_for([], tmp_path)
    map_beats(caller, todo_profile(), todo_outline())
    prompt = llm.calls[0]["prompt"]
    assert prompt.startswith("Bạn là trợ lý biên tập video. Nhiệm vụ: gán mỗi beat")
    assert "Gõ 'Buy milk'" in _section(prompt, "outline")
    features = json.loads(_section(prompt, "features").split("{#")[0])
    by_id = {f["id"]: f for f in features}
    assert set(by_id) == {"create-todo", "edit-todo"}  # only the concept's features are offered
    assert by_id["create-todo"]["demo_steps_summary"] == "gõ «Buy milk»"
    assert by_id["edit-todo"]["demo_steps_summary"] == "nhấp đúp «Buy milk»"
    assert by_id["edit-todo"]["demo_kind"] == "interaction"
    assert "tối đa 2 beat" in prompt and "confidence" in prompt


def test_unknown_or_out_of_concept_features_are_dropped_with_a_warning(tmp_path: Path) -> None:
    caller, _ = caller_for(
        [
            row("b2", "ghost"),
            row("b3", "filter-todos"),
            row("b4", "edit-todo"),
            row("b9", "edit-todo"),
        ],
        tmp_path,
    )
    result = map_beats(caller, todo_profile(), todo_outline())
    assert links(result.outline) == {
        "b1": None,
        "b2": None,
        "b3": None,
        "b4": "edit-todo",
        "b5": None,
    }
    text = " ".join(result.warnings)
    assert "ghost" in text and "filter-todos" in text and "b9" in text


def test_low_confidence_leaves_the_beat_empty(tmp_path: Path) -> None:
    caller, _ = caller_for([row("b2", "create-todo", 0.3), row("b3", "edit-todo", 0.5)], tmp_path)
    result = map_beats(caller, todo_profile(), todo_outline())
    assert links(result.outline)["b2"] is None and links(result.outline)["b3"] == "edit-todo"


def test_a_feature_may_be_used_by_at_most_two_beats_keeping_the_most_confident(
    tmp_path: Path,
) -> None:
    caller, _ = caller_for(
        [
            row("b2", "create-todo", 0.6),
            row("b3", "create-todo", 0.95),
            row("b4", "create-todo", 0.8),
        ],
        tmp_path,
    )
    result = map_beats(caller, todo_profile(), todo_outline())
    assert links(result.outline) == {
        "b1": None, "b2": None, "b3": "create-todo", "b4": "create-todo", "b5": None,
    }  # fmt: skip
    assert any("b2" in w and "2 beat" in w for w in result.warnings)


def test_links_already_set_are_kept_and_count_toward_the_limit(tmp_path: Path) -> None:
    outline = todo_outline()
    outline.beats[1].feature_id = "create-todo"  # set by the user
    outline.beats[2].feature_id = "create-todo"
    caller, _ = caller_for(
        [row("b2", "edit-todo"), row("b3", "edit-todo"), row("b4", "create-todo")], tmp_path
    )
    result = map_beats(caller, todo_profile(), outline)
    assert links(result.outline)["b2"] == links(result.outline)["b3"] == "create-todo"
    assert links(result.outline)["b4"] is None  # create-todo is already used twice


def test_only_the_beats_an_edit_touched_are_linked(tmp_path: Path) -> None:
    caller, _ = caller_for([row("b2", "create-todo"), row("b3", "edit-todo")], tmp_path)
    result = map_beats(caller, todo_profile(), todo_outline(), only_beats={"b3"})
    assert links(result.outline) == {
        "b1": None,
        "b2": None,
        "b3": "edit-todo",
        "b4": None,
        "b5": None,
    }


def test_a_link_on_the_hook_or_cta_is_removed(tmp_path: Path) -> None:
    outline = todo_outline()
    outline.beats[0].feature_id = "create-todo"
    outline.beats[-1].feature_id = "edit-todo"
    caller, _ = caller_for([row("b2", "create-todo")], tmp_path)
    result = map_beats(caller, todo_profile(), outline)
    assert (
        result.outline.beats[0].feature_id is None and result.outline.beats[-1].feature_id is None
    )
    assert any("b1" in c for c in result.changes) and any("b5" in c for c in result.changes)


def test_without_concept_feature_ids_every_product_feature_is_allowed(tmp_path: Path) -> None:
    caller, llm = caller_for([row("b2", "filter-todos")], tmp_path)
    result = map_beats(caller, todo_profile(), todo_outline(feature_ids=[]))
    assert links(result.outline)["b2"] == "filter-todos"
    offered = json.loads(_section(llm.calls[0]["prompt"], "features").split("{#")[0])
    assert len(offered) == 4


def test_needs_mapping_only_looks_at_the_middle_beats() -> None:
    assert needs_mapping(todo_outline())
    done = todo_outline()
    for b in done.beats[1:-1]:
        b.feature_id = "create-todo"
    assert not needs_mapping(done)


def test_summarize_steps_covers_the_step_kinds() -> None:
    p = todo_profile()
    assert summarize_steps(p.features[2]) == "nhấp «Active»"
    assert summarize_steps(p.features[3]) == ""
