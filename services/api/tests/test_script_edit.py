import json
from pathlib import Path
from typing import Any

import pytest

from app.llm.json_call import JsonCaller
from app.schemas.generated.edit_op import EditOp
from app.schemas.generated.script import Script
from app.script.apply import apply_ops
from app.script.diff import diff_scripts
from app.script.edit import apply_edit, apply_global
from app.script.versions import ScriptStore
from app.script.writer import WriterContext, build_prompt
from tests.conftest import FakeLLM, _section
from tests.test_fit_and_scene_writer import make_script
from tests.test_script_writer import good_scene, words


def op(**kw: Any) -> EditOp:
    return EditOp.model_validate(kw)


@pytest.fixture
def base(tmp_path: Path) -> tuple[Script, WriterContext]:
    return make_script(tmp_path)


def dumps(script: Script) -> dict[str, str]:
    return {s.root.id: json.dumps(s.root.model_dump(), sort_keys=True) for s in script.scenes}


# --- apply_ops --------------------------------------------------------------------------------


def test_set_changes_one_field_and_leaves_every_other_scene_byte_identical(
    base: tuple[Script, WriterContext],
) -> None:
    script, ctx = base
    res = apply_ops(
        script, [op(op="set", scene_id="s3", field="voiceover", value="Lời đọc mới hoàn toàn")], ctx
    )
    assert res.errors == [] and res.llm_tasks == [] and not res.needs_full_regen
    before, after = dumps(script), dumps(res.script)
    assert (
        after["s3"] != before["s3"]
        and res.script.scenes[2].root.voiceover == "Lời đọc mới hoàn toàn"
    )
    assert {k: v for k, v in after.items() if k != "s3"} == {
        k: v for k, v in before.items() if k != "s3"
    }
    assert res.script.headline == script.headline and res.script.theme == script.theme
    assert res.changes == ["Scene s3: đặt lời đọc = «Lời đọc mới hoàn toàn»"]


def test_set_on_screen_text_empty_clears_it_and_layout_is_validated(
    base: tuple[Script, WriterContext],
) -> None:
    script, ctx = base
    res = apply_ops(script, [op(op="set", scene_id="s1", field="on_screen_text", value="")], ctx)
    assert res.script.scenes[0].root.on_screen_text is None
    ok = apply_ops(script, [op(op="set", scene_id="s1", field="layout", value="emoji_pop")], ctx)
    assert ok.script.scenes[0].root.layout == "emoji_pop"
    bad = apply_ops(script, [op(op="set", scene_id="s1", field="layout", value="swipe")], ctx)
    assert bad.script is script and any("layout 'swipe'" in e for e in bad.errors)


def test_set_feature_refills_the_visual_from_the_profile(
    base: tuple[Script, WriterContext],
) -> None:
    script, ctx = base
    res = apply_ops(script, [op(op="set", scene_id="s2", field="feature", value="nav")], ctx)
    scene = res.script.scenes[1].root
    assert scene.feature == "nav" and [a.do for a in scene.visual.actions] == ["goto", "click"]
    unknown = apply_ops(script, [op(op="set", scene_id="s2", field="feature", value="ghost")], ctx)
    assert any("ghost" in e for e in unknown.errors) and unknown.script is script
    on_hook = apply_ops(script, [op(op="set", scene_id="s1", field="feature", value="nav")], ctx)
    assert any("does not exist on scene s1" in e for e in on_hook.errors)


def test_unknown_scene_is_an_error_and_nothing_changes(base: tuple[Script, WriterContext]) -> None:
    script, ctx = base
    res = apply_ops(
        script,
        [op(op="delete", scene_id="s9"), op(op="move", scene_id="s9", after_scene_id=None)],
        ctx,
    )
    assert len(res.errors) == 2 and dumps(res.script) == dumps(script) and res.changes == []


def test_delete_move_and_the_three_scene_floor(base: tuple[Script, WriterContext]) -> None:
    script, ctx = base
    res = apply_ops(script, [op(op="delete", scene_id="s4")], ctx)
    assert [s.root.id for s in res.script.scenes] == ["s1", "s2", "s3", "s5"]
    moved = apply_ops(script, [op(op="move", scene_id="s5", after_scene_id=None)], ctx)
    assert [s.root.id for s in moved.script.scenes] == ["s5", "s1", "s2", "s3", "s4"]
    after = apply_ops(script, [op(op="move", scene_id="s2", after_scene_id="s4")], ctx)
    assert [s.root.id for s in after.script.scenes] == ["s1", "s3", "s4", "s2", "s5"]
    assert dumps(after.script)["s2"] == dumps(script)["s2"]  # moving does not touch the scene
    floor = apply_ops(script, [op(op="delete", scene_id=i) for i in ("s2", "s3", "s4")], ctx)
    assert len(floor.script.scenes) == 3  # the third delete would leave only two scenes
    assert any("ít nhất 3 scene" in e for e in floor.errors)
    hook = apply_ops(script, [op(op="delete", scene_id="s1")], ctx)
    assert any("hook" in w for w in hook.warnings)


def test_move_after_an_unknown_scene_is_refused_and_restores_the_order(
    base: tuple[Script, WriterContext],
) -> None:
    script, ctx = base
    res = apply_ops(script, [op(op="move", scene_id="s2", after_scene_id="s9")], ctx)
    assert [s.root.id for s in res.script.scenes] == [s.root.id for s in script.scenes]
    assert res.errors


def test_set_theme(base: tuple[Script, WriterContext]) -> None:
    script, ctx = base
    res = apply_ops(
        script,
        [
            op(op="set_theme", field="primary", value="#0f766e"),
            op(op="set_theme", field="motion_preset", value="calm"),
            op(op="set_theme", field="caption_style", value="minimal"),
        ],
        ctx,
    )
    assert (res.script.theme.primary, res.script.theme.motion_preset, res.script.theme.caption_style) == (
        "#0F766E", "calm", "minimal",
    )  # fmt: skip
    assert dumps(res.script) == dumps(script)
    bad = apply_ops(script, [op(op="set_theme", field="primary", value="xanh")], ctx)
    assert (
        any("#RRGGBB" in e for e in bad.errors) and bad.script.theme.primary == script.theme.primary
    )
    assert apply_ops(script, [op(op="set_theme", field="music_mood", value="disco")], ctx).errors


def test_rewrite_and_insert_become_llm_tasks_and_set_global_asks_for_a_full_rewrite(
    base: tuple[Script, WriterContext],
) -> None:
    script, ctx = base
    res = apply_ops(
        script,
        [
            op(op="rewrite", scene_id="s2", fields=["voiceover"], instruction="vui hơn"),
            op(
                op="insert",
                after_scene_id="s2",
                scene_type="feature_demo",
                instruction="thêm demo giá",
            ),
            op(op="set_global", field="tone", value="hài hước"),
        ],
        ctx,
    )
    assert [t["kind"] for t in res.llm_tasks] == ["rewrite", "insert"]
    assert res.llm_tasks[0] == {
        "kind": "rewrite",
        "scene_id": "s2",
        "fields": ["voiceover"],
        "instruction": "vui hơn",
    }
    assert res.llm_tasks[1]["after_scene_id"] == "s2" and res.needs_full_regen
    assert res.global_ops == [{"field": "tone", "value": "hài hước"}]
    assert dumps(res.script) == dumps(script)  # nothing applied deterministically
    new_script, changes, tasks, regen = res.unpack()
    assert new_script is res.script and len(changes) == 3 and len(tasks) == 2 and regen


def test_ops_apply_in_order(base: tuple[Script, WriterContext]) -> None:
    script, ctx = base
    res = apply_ops(
        script,
        [op(op="delete", scene_id="s2"), op(op="set", scene_id="s2", field="voiceover", value="x")],
        ctx,
    )
    assert len(res.script.scenes) == 4 and any("s2" in e for e in res.errors)


# --- apply_edit (planner + scene writer) -----------------------------------------------------------


def planner_and_writer(
    plan: dict[str, Any], scene: dict[str, Any] | None = None, seen: list[str] | None = None
):  # type: ignore[no-untyped-def]
    def handler(prompt: str) -> dict[str, Any]:
        if seen is not None:
            seen.append(prompt)
        if prompt.startswith('Bạn là "Edit Planner"'):
            return plan
        assert prompt.startswith("Bạn là biên kịch short video marketing. Nhiệm vụ: viết lại HOẶC")
        return {"scene": scene}

    return handler


def test_a_rewrite_instruction_changes_only_the_target_scene(
    base: tuple[Script, WriterContext], tmp_path: Path
) -> None:
    script, ctx = base
    plan = {
        "status": "ok",
        "ops": [
            {
                "op": "rewrite",
                "scene_id": "s3",
                "fields": ["voiceover"],
                "instruction": "nhấn mạnh tốc độ",
            }
        ],
    }
    scene = good_scene(3, "feature_demo", feature="filter", voiceover=words(20, "nhanh"))
    seen: list[str] = []
    llm = FakeLLM(planner_and_writer(plan, scene, seen))
    out = apply_edit(
        JsonCaller(llm, cache_dir=tmp_path),
        script,
        ctx,
        instruction="scene 3: nhấn mạnh tốc độ",
        version=2,
    )
    assert out.errors == [] and out.changed and out.changes == ["Viết lại voiceover của scene s3"]
    before, after = dumps(script), dumps(out.script)
    assert after["s3"] != before["s3"] and out.script.scenes[2].root.voiceover.startswith("nhanh0")
    assert {k: v for k, v in after.items() if k != "s3"} == {
        k: v for k, v in before.items() if k != "s3"
    }
    assert out.script.scenes[2].root.visual == script.scenes[2].root.visual
    planner_prompt = seen[0]
    assert (
        '<current_script version="2">' in planner_prompt
        and "scene 3: nhấn mạnh tốc độ" in planner_prompt
    )
    assert '"full_screen"' in planner_prompt  # layouts_by_type comes from the generated table
    assert "locator" not in planner_prompt  # no raw visuals in the planner input


def test_an_insert_instruction_adds_one_scene_at_the_requested_place(
    base: tuple[Script, WriterContext], tmp_path: Path
) -> None:
    script, ctx = base
    plan = {
        "status": "ok",
        "ops": [
            {
                "op": "insert",
                "after_scene_id": "s3",
                "scene_type": "feature_demo",
                "instruction": "thêm trang giá",
            }
        ],
    }
    scene = good_scene(
        0, "feature_demo", feature="nav", voiceover=words(18, "gia"), key_point="Trang giá"
    )
    llm = FakeLLM(planner_and_writer(plan, scene))
    out = apply_edit(
        JsonCaller(llm, cache_dir=tmp_path),
        script,
        ctx,
        instruction="thêm demo trang giá sau scene 3",
    )
    ids = [s.root.id for s in out.script.scenes]
    assert ids == ["s1", "s2", "s3", "s6", "s4", "s5"]
    old = dumps(script)
    assert all(dumps(out.script)[i] == old[i] for i in old)  # existing scenes byte-identical


def test_clarification_and_rejection_come_back_without_changing_the_script(
    base: tuple[Script, WriterContext], tmp_path: Path
) -> None:
    script, ctx = base
    ask = {
        "status": "needs_clarification",
        "clarification": {
            "question": "Sửa scene nào?",
            "options": [{"id": "s2", "label": "Scene 2"}, {"id": "s3", "label": "Scene 3"}],
        },
    }
    out = apply_edit(
        JsonCaller(FakeLLM(lambda _p: ask), cache_dir=tmp_path),
        script,
        ctx,
        instruction="sửa đoạn demo",
    )
    assert out.clarification is not None and [o.id for o in out.clarification.options] == [
        "s2",
        "s3",
    ]
    assert out.script is script and not out.changed
    reject = {
        "status": "ok",
        "ops": [],
        "rejected": [
            {
                "request": "demo thanh toán",
                "reason": "không có trong sản phẩm",
                "suggestion": "Lọc việc",
            }
        ],
    }
    out = apply_edit(
        JsonCaller(FakeLLM(lambda _p: reject), cache_dir=tmp_path),
        script,
        ctx,
        instruction="demo thanh toán",
    )
    assert (
        out.rejected == ["demo thanh toán — không có trong sản phẩm (gợi ý: Lọc việc)"]
        and not out.changed
    )


def test_explicit_ops_skip_the_planner(base: tuple[Script, WriterContext], tmp_path: Path) -> None:
    script, ctx = base
    llm = FakeLLM(lambda _p: pytest.fail("planner must not be called"))
    out = apply_edit(
        JsonCaller(llm, cache_dir=tmp_path), script, ctx,
        ops=[op(op="set", scene_id="s1", field="voiceover", value="Câu mở đầu do tôi viết")],
    )  # fmt: skip
    assert llm.calls == [] and out.script.scenes[0].root.voiceover == "Câu mở đầu do tôi viết"


def test_invalid_planner_ops_are_reported_not_applied(
    base: tuple[Script, WriterContext], tmp_path: Path
) -> None:
    script, ctx = base
    plan = {
        "status": "ok",
        "ops": [
            {"op": "set", "scene_id": "s1", "field": "layout", "value": "swipe"},
            {"op": "delete", "scene_id": "s5"},
        ],
    }
    out = apply_edit(
        JsonCaller(FakeLLM(lambda _p: plan), cache_dir=tmp_path), script, ctx, instruction="x"
    )
    assert [s.root.id for s in out.script.scenes] == ["s1", "s2", "s3", "s4"]
    assert any("swipe" in w for w in out.warnings)


def test_set_global_updates_the_brief_for_a_full_rewrite(
    base: tuple[Script, WriterContext],
) -> None:
    script, ctx = base
    new_ctx, warnings = apply_global(
        ctx,
        [
            {"field": "duration", "value": "60 giây"},
            {"field": "goal", "value": "conversion"},
            {"field": "tone", "value": "hài hước"},
            {"field": "audience", "value": "sinh viên"},
            {"field": "cta", "value": "Tải ngay hôm nay"},
            {"field": "features", "value": ["create", "ghost"]},
        ],
    )
    o = new_ctx.outline
    assert (o.duration_s, o.goal, o.feature_ids) == (60, "conversion", ["create"])
    assert o.beats[-1].text == "Tải ngay hôm nay" and o.beats[0].text == ctx.outline.beats[0].text
    assert new_ctx.notes == ["tone: hài hước", "audience: sinh viên"] and any(
        "ghost" in w for w in warnings
    )
    assert ctx.outline.duration_s == 45 and ctx.notes == []  # the original context is untouched
    prompt = build_prompt(new_ctx)
    assert "Thời lượng mục tiêu: 60 giây" in prompt
    assert "<user_notes>" in prompt and "tone: hài hước" in _section(prompt, "user_notes")
    assert "<user_notes>" not in build_prompt(ctx)
    _, warn = apply_global(ctx, [{"field": "duration", "value": "50"}])
    assert warn and "30/45/60" in warn[0]


# --- versions and diff ------------------------------------------------------------------------


def test_versions_are_linear_and_revert_copies_forward(
    base: tuple[Script, WriterContext], tmp_path: Path
) -> None:
    script, ctx = base
    store = ScriptStore(tmp_path)
    assert store.latest() is None and store.versions() == []
    assert store.save(script) == 1
    edited = apply_ops(
        script, [op(op="set", scene_id="s1", field="voiceover", value="Câu mới")], ctx
    ).script
    assert store.save(edited) == 2
    assert store.revert(1) == 3
    assert store.versions() == [1, 2, 3] and (tmp_path / "scripts" / "v3.json").is_file()
    assert store.load(3).model_dump() == store.load(1).model_dump() != store.load(2).model_dump()
    with pytest.raises(KeyError):
        store.load(9)


def test_diff_lists_changes_in_vietnamese(base: tuple[Script, WriterContext]) -> None:
    script, ctx = base
    assert diff_scripts(script, script) == []
    res = apply_ops(
        script,
        [
            op(op="set", scene_id="s1", field="voiceover", value="Câu mở đầu mới"),
            op(op="delete", scene_id="s4"),
            op(op="move", scene_id="s5", after_scene_id="s1"),
            op(op="set_theme", field="primary", value="#0F766E"),
            op(op="set", scene_id="s2", field="feature", value="nav"),
        ],
        ctx,
    )
    lines = diff_scripts(script, res.script)
    text = "\n".join(lines)
    assert "Scene s1: đổi lời đọc" in text and "Câu mở đầu mới" in text
    assert "Xóa scene s4 (before_after)" in text
    assert "Đổi màu chủ đạo: #4F46E5 → #0F766E" in text
    assert "Scene s2: đổi tính năng «create» → «nav»" in text
    assert "Đổi thứ tự các scene: s1 → s5 → s2 → s3" in text
    assert "Scene s2: đổi thao tác quay" in text
    inserted = Script.model_validate({**res.script.model_dump(), "headline": "Tiêu đề khác"})
    assert "Đổi tiêu đề: «Quản lý công việc nhanh gấp đôi» → «Tiêu đề khác»" in diff_scripts(
        res.script, inserted
    )
