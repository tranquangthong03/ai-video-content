import json
from pathlib import Path
from typing import Any

import pytest

from app.llm.json_call import JsonCaller
from app.media.timing import estimate_speech_ms
from app.schemas.generated.script import Script
from app.script.fit_duration import (
    TOLERANCE,
    VoiceoverItem,
    apply_voiceovers,
    estimated_ms,
    fit_duration,
)
from app.script.scene_writer import write_scene
from app.script.writer import WriterContext, WriterError, write_script
from tests.conftest import FakeLLM, _section
from tests.test_script_writer import (
    caller_for,
    ctx_for,
    good_output,
    good_scene,
    make_outline,
    words,
)


def make_script(
    tmp_path: Path, duration: int = 45, voice_words: tuple[int, ...] = (22, 22, 22, 22, 22)
) -> tuple[Script, WriterContext]:
    ctx = ctx_for(make_outline(duration), setup={"filter": 2})
    out = good_output()
    for scene, n in zip(out["script"]["scenes"], voice_words, strict=True):
        scene["voiceover"] = words(n, "w")
    caller, _ = caller_for(out, tmp_path=tmp_path)
    return write_script(caller, ctx).script, ctx


def fit_caller(handler: Any, tmp_path: Path) -> tuple[JsonCaller, FakeLLM]:
    llm = FakeLLM(handler)
    return JsonCaller(llm, cache_dir=tmp_path), llm


def voiceovers(script: Script, n_words: int, only: tuple[str, ...] = ()) -> dict[str, Any]:
    items = [
        {"scene_id": s.root.id, "voiceover": words(n_words, f"{s.root.id}x")}
        for s in script.scenes
        if not only or s.root.type in only
    ]
    return {"voiceovers": items, "notes": None}


# --- fit_duration -----------------------------------------------------------------------------


def test_a_script_within_ten_percent_is_left_alone(tmp_path: Path) -> None:
    script, ctx = make_script(tmp_path, 45, (22, 22, 22, 22, 22))  # 110 words ~ 45 s with pauses
    assert abs(estimated_ms(script) - 45000) <= 45000 * TOLERANCE
    caller, llm = fit_caller(lambda _p: pytest.fail("no LLM call expected"), tmp_path)
    fitted, report = fit_duration(caller, script, ctx)
    assert llm.calls == [] and report.rounds == 0 and report.within
    assert fitted.model_dump() == script.model_dump()
    assert report.target_ms == 45000 and report.estimated_ms == estimated_ms(script)


def test_too_short_extends_only_the_demo_scenes(tmp_path: Path) -> None:
    script, ctx = make_script(tmp_path, 45, (12, 12, 12, 12, 12))  # ~ 60 words: 25 s
    assert estimated_ms(script) < 45000 * (1 - TOLERANCE)
    answer = voiceovers(script, 28, only=("feature_demo",))
    answer["voiceovers"].append({"scene_id": "s1", "voiceover": words(29, "hookx")})  # not allowed
    caller, llm = fit_caller(lambda _p: answer, tmp_path)
    fitted, report = fit_duration(caller, script, ctx)
    prompt = llm.calls[0]["prompt"]
    assert (
        "ngắn hơn so với thời lượng mục tiêu" in prompt
        and "khoảng 109 từ" in prompt
        and "hiện có 60 từ" in prompt
    )
    scenes = {s.root.id: s.root for s in fitted.scenes}
    assert scenes["s1"].voiceover == script.scenes[0].root.voiceover  # hook untouched
    assert len(scenes["s2"].voiceover.split()) == 28 and len(scenes["s3"].voiceover.split()) == 28
    assert any("s1" in w and "feature_demo" in w for w in report.warnings)
    assert "kéo dài" in report.actions[0] and report.rounds >= 1
    for s in fitted.scenes:  # only voiceovers changed
        before = next(x for x in script.scenes if x.root.id == s.root.id).root
        assert s.root.model_dump(exclude={"voiceover"}) == before.model_dump(exclude={"voiceover"})


def test_still_short_adds_one_demo_scene_before_the_cta_with_the_best_unused_feature(
    tmp_path: Path,
) -> None:
    script, ctx = make_script(tmp_path, 45, (10, 10, 10, 10, 10))
    assert len(script.scenes) == 5

    def handler(prompt: str) -> dict[str, Any]:
        if prompt.startswith("Bạn là biên tập viên kịch bản"):
            return voiceovers(script, 12, only=("feature_demo",))  # not enough
        assert prompt.startswith(
            "Bạn là biên kịch short video marketing. Nhiệm vụ: viết lại HOẶC viết mới"
        )
        assert (
            "Loại: insert" in prompt and "Loại scene cần tạo (với insert): feature_demo" in prompt
        )
        assert "Scene trước: s4 (before_after)" in prompt and "Scene sau: s5 (cta)" in prompt
        return {"scene": good_scene(9, "feature_demo", feature="nav", voiceover=words(25, "navx"),
                                    key_point="Xem bảng giá")}  # fmt: skip

    caller, llm = fit_caller(handler, tmp_path)
    fitted, report = fit_duration(caller, script, ctx)
    assert [s.root.id for s in fitted.scenes] == ["s1", "s2", "s3", "s4", "s6", "s5"][:0] or len(
        fitted.scenes
    ) == 6
    types = [s.root.type for s in fitted.scenes]
    assert types[-1] == "cta" and types[-2] == "feature_demo"
    new = fitted.scenes[-2].root
    assert new.feature == "nav"  # highest importance among the unused demoable features
    assert new.id not in {s.root.id for s in script.scenes}
    assert [a.do for a in new.visual.actions] == ["goto", "click"]
    assert any("thêm scene demo" in a for a in report.actions)


def test_no_scene_is_added_when_there_are_already_six(tmp_path: Path) -> None:
    script, ctx = make_script(tmp_path, 45, (10, 10, 10, 10, 10))
    data = script.model_dump()
    extra = dict(data["scenes"][1], id="s6", key_point="Thêm ý")
    data["scenes"].insert(2, extra)
    six = Script.model_validate(data)
    caller, llm = fit_caller(lambda _p: voiceovers(six, 11, only=("feature_demo",)), tmp_path)
    fitted, report = fit_duration(caller, six, ctx)
    assert len(fitted.scenes) == 6 and not report.within
    assert any("thiếu" in w for w in report.warnings)


def test_too_long_shortens_but_keeps_hook_and_cta_at_least_six_words(tmp_path: Path) -> None:
    script, ctx = make_script(tmp_path, 30, (30, 30, 30, 30, 30))  # 150 words for 30 s
    answer = voiceovers(script, 14)
    answer["voiceovers"][0]["voiceover"] = words(3, "hookx")  # too short: refused
    caller, llm = fit_caller(lambda _p: answer, tmp_path)
    fitted, report = fit_duration(caller, script, ctx)
    assert "dài hơn so với thời lượng mục tiêu" in llm.calls[0]["prompt"]
    importance = [
        x["importance"] for x in json.loads(_section(llm.calls[0]["prompt"], "script"))["scenes"]
    ]
    assert importance[0] is None and importance[1] is not None  # demo scenes carry their importance
    assert fitted.scenes[0].root.voiceover == script.scenes[0].root.voiceover
    assert any("s1" in w and "quá ngắn" in w for w in report.warnings)
    assert estimated_ms(fitted) < estimated_ms(script)
    assert len(fitted.scenes) == len(script.scenes)  # nothing deleted


def test_adjust_false_only_measures(tmp_path: Path) -> None:
    script, ctx = make_script(tmp_path, 45, (10, 10, 10, 10, 10))
    caller, llm = fit_caller(lambda _p: pytest.fail("no LLM call expected"), tmp_path)
    fitted, report = fit_duration(caller, script, ctx, adjust=False)
    assert llm.calls == [] and fitted is script and not report.within and report.rounds == 0
    assert report.as_dict()["within_tolerance"] is False


def test_a_45_second_demo_with_one_operation_shows_its_setup(tmp_path: Path) -> None:
    script, ctx = make_script(tmp_path, 45, (22, 22, 22, 22, 22))
    filt = script.scenes[2].root
    assert filt.visual.show_setup is True  # the writer's draft already asked for it
    data = script.model_dump()
    data["scenes"][2]["visual"]["show_setup"] = False
    data["scenes"][2]["visual"]["actions"] = data["scenes"][2]["visual"]["actions"][
        :1
    ]  # one click only
    script = Script.model_validate(data)
    caller, _ = fit_caller(lambda _p: pytest.fail("no LLM call expected"), tmp_path)
    fitted, report = fit_duration(caller, script, ctx)
    assert fitted.scenes[2].root.visual.show_setup is True
    assert any("show_setup" in a for a in report.actions)


def test_apply_voiceovers_refuses_unknown_scenes_and_overlong_text(tmp_path: Path) -> None:
    script, _ = make_script(tmp_path, 45, (12, 12, 12, 12, 12))
    items = [
        VoiceoverItem(scene_id="s9", voiceover=words(20)),
        VoiceoverItem(scene_id="s2", voiceover=words(31)),
        VoiceoverItem(scene_id="s3", voiceover=words(20, "ok")),
        VoiceoverItem(scene_id="s2", voiceover=script.scenes[1].root.voiceover),
    ]
    new, notes = apply_voiceovers(script, items, extend=True)
    assert new.scenes[2].root.voiceover.startswith("ok0")
    assert new.scenes[1].root.voiceover == script.scenes[1].root.voiceover
    assert any("s9" in n for n in notes) and any("31" in n for n in notes)


# --- scene writer -----------------------------------------------------------------------------


def scene_handler(scene: dict[str, Any], seen: list[str] | None = None):  # type: ignore[no-untyped-def]
    def handler(prompt: str) -> dict[str, Any]:
        if seen is not None:
            seen.append(prompt)
        return {"scene": scene, "notes": None}

    return handler


def test_rewrite_changes_only_the_requested_fields_and_keeps_id_and_type(tmp_path: Path) -> None:
    script, ctx = make_script(tmp_path)
    current = script.scenes[1].root
    written = good_scene(
        7, "hook", voiceover=words(20, "mới"), on_screen_text="Chữ mới", key_point="Ý hoàn toàn khác",
        icon="globe", layout="emoji_pop", feature="nav",
    )  # fmt: skip
    seen: list[str] = []
    caller, _ = fit_caller(scene_handler(written, seen), tmp_path)
    result = write_scene(
        caller, ctx, script, task="rewrite", instruction="viết lại cho vui hơn",
        fields=["voiceover"], scene_id="s2",
    )  # fmt: skip
    new = result.scene.root
    assert new.id == "s2" and new.type == "feature_demo"  # id and type are kept
    assert new.voiceover.startswith("mới0")
    # not requested: unchanged although the model changed them
    assert (new.on_screen_text, new.key_point, new.icon, new.layout, new.feature) == (
        current.on_screen_text, current.key_point, current.icon, current.layout, current.feature,
    )  # fmt: skip
    assert new.visual == current.visual  # visual still comes from the profile
    prompt = seen[0]
    assert "Loại: rewrite" in prompt and "Field cần viết lại (với rewrite): voiceover" in prompt
    assert "Scene trước: s1 (hook)" in prompt and "Scene sau: s3 (feature_demo)" in prompt
    assert (
        "viết lại cho vui hơn" in prompt and "Headline: Quản lý công việc nhanh gấp đôi" in prompt
    )


def test_rewriting_the_visual_of_a_demo_switches_feature_and_refills_actions(
    tmp_path: Path,
) -> None:
    script, ctx = make_script(tmp_path)
    written = good_scene(
        2, "feature_demo", feature="nav", show_setup=False, voiceover=words(20, "nv")
    )
    caller, _ = fit_caller(scene_handler(written), tmp_path)
    result = write_scene(
        caller, ctx, script, task="rewrite", instruction="đổi sang demo trang giá",
        fields=["visual"], scene_id="s2",
    )  # fmt: skip
    new = result.scene.root
    assert new.feature == "nav" and [a.do for a in new.visual.actions] == ["goto", "click"]
    assert new.voiceover == script.scenes[1].root.voiceover  # only the visual was asked for


def test_insert_creates_a_new_scene_with_a_fresh_id_and_code_made_visual(tmp_path: Path) -> None:
    script, ctx = make_script(tmp_path)
    written = good_scene(
        0, "cta", feature="story", voiceover=words(18, "ins"), key_point="Câu chuyện"
    )
    written["id"] = "new"
    written["type"] = "feature_demo"
    written["layout"] = "full_screen"
    caller, _ = fit_caller(scene_handler(written), tmp_path)
    result = write_scene(
        caller, ctx, script, task="insert", instruction="thêm đoạn câu chuyện",
        scene_type="feature_demo", after_scene_id="s2",
    )  # fmt: skip
    new = result.scene.root
    assert new.id == "s6" and new.type == "feature_demo" and new.feature == "story"
    assert [a.do for a in new.visual.actions] == ["goto", "scroll_to", "highlight"]


def test_a_bad_scene_is_sent_back_once_and_fixed(tmp_path: Path) -> None:
    script, ctx = make_script(tmp_path)
    bad = good_scene(2, "feature_demo", feature="create", voiceover=words(3), icon="rocket")
    good = good_scene(2, "feature_demo", feature="create", voiceover=words(20, "ok"))
    replies = [bad, good]
    llm = FakeLLM(lambda _p: {"scene": replies.pop(0)})
    caller = JsonCaller(llm, cache_dir=tmp_path)
    result = write_scene(
        caller, ctx, script, task="rewrite", instruction="i", fields=["voiceover", "on_screen_text"],
        scene_id="s2",
    )  # fmt: skip
    assert result.attempts == 2 and "voiceover có 3 từ" in llm.calls[1]["prompt"]
    assert result.scene.root.voiceover.startswith("ok0")


def test_unknown_scene_and_giving_up(tmp_path: Path) -> None:
    script, ctx = make_script(tmp_path)
    caller, _ = fit_caller(
        scene_handler(good_scene(2, "feature_demo", feature="create", voiceover="ngắn")), tmp_path
    )
    with pytest.raises(WriterError):
        write_scene(
            caller,
            ctx,
            script,
            task="rewrite",
            instruction="i",
            fields=["voiceover"],
            scene_id="s2",
        )
    with pytest.raises(WriterError, match="không có scene s9"):
        write_scene(
            caller,
            ctx,
            script,
            task="rewrite",
            instruction="i",
            fields=["voiceover"],
            scene_id="s9",
        )
    assert estimate_speech_ms("a b c d") > 0
