"""Footage-first scenes: structure rules, showcase_lite, forced-duration fit, honest duration."""

from pathlib import Path
from typing import Any

import pytest

from app.browser.session import BrowserSession
from app.core.budget import budget_for, oversize_warning
from app.llm.json_call import JsonCaller
from app.proposal.concepts import normalize_concepts
from app.proposal.outline import build_request
from app.schemas.generated.script import Script
from app.schemas.generated.video_concept import VideoConcept
from app.script.fit_duration import (
    FitReport,
    VoiceoverItem,
    apply_voiceovers,
    fit_duration,
    repeat_operations,
)
from app.script.footage import SceneFacts, footage_ratio, structure_issues
from app.script.lite import LiteContext, PageIndex
from app.script.visuals import visual_for_scene
from app.script.writer import DraftScript, soft_issues, write_script
from tests.test_recorder import goto, loc, rec
from tests.test_script_writer import (
    HOME,
    caller_for,
    ctx_for,
    good_output,
    good_scene,
    make_outline,
    make_profile,
    words,
)


def facts(*spec: tuple[str, bool], feature: str | None = None) -> list[SceneFacts]:
    return [
        SceneFacts(t, f"f{i}" if t == "feature_demo" else feature, "từ " * 20, clip)
        for i, (t, clip) in enumerate(spec)
    ]


GOOD = (("hook", False), ("feature_demo", True), ("feature_demo", True), ("cta", False))


# --- structure rules ------------------------------------------------------------------------------


def test_a_clip_heavy_plan_with_one_hook_and_one_cta_has_no_issues() -> None:
    assert structure_issues(facts(*GOOD), 45) == []
    assert footage_ratio(facts(*GOOD)) == pytest.approx(0.5)


def test_hook_in_the_middle_two_before_afters_and_text_only_neighbours_are_reported() -> None:
    plan = facts(("hook", False), ("feature_demo", True), ("hook", False), ("before_after", False))
    plan += facts(("before_after", False), ("cta", False))
    text = " | ".join(structure_issues(plan, 45))
    assert "hook chỉ được dùng cho scene đầu" in text
    assert "tối đa 1 scene before_after" in text
    assert "đều không có cảnh quay liền nhau" in text
    assert "tỷ lệ cảnh quay" in text


def test_the_footage_target_is_lower_for_a_30_second_video() -> None:
    plan = facts(("hook", False), ("feature_demo", True), ("feature_demo", False), ("cta", False))
    assert any("tỷ lệ" in i for i in structure_issues(plan, 45))
    plan[2] = SceneFacts("feature_demo", "f2", "từ " * 20, True)
    assert not any("tỷ lệ" in i for i in structure_issues(plan, 30))


def test_a_feature_filmed_twice_is_reported() -> None:
    plan = [SceneFacts("hook", None, "từ " * 20, False)]
    plan += [SceneFacts("feature_demo", "create", "từ " * 20, True)] * 2
    plan += [SceneFacts("cta", None, "từ " * 20, False)]
    assert any("«create» đã được quay" in i for i in structure_issues(plan, 45))


# --- the writer repairs structure problems twice, then only warns ---------------------------------


def text_heavy() -> dict[str, Any]:
    scenes = [good_scene(1, "hook"), good_scene(2, "feature_demo", feature="create")]
    scenes += [
        good_scene(3, "before_after", before_text="a", after_text="b", layout="split_vertical")
    ]
    scenes += [
        good_scene(4, "before_after", before_text="c", after_text="d", layout="split_vertical")
    ]
    scenes += [good_scene(5, "cta")]
    return good_output(scenes=scenes)


def test_structure_issues_go_back_to_the_writer_and_a_better_draft_is_taken(tmp_path: Path) -> None:
    caller, llm = caller_for(text_heavy(), good_output(), tmp_path=tmp_path)
    ctx = ctx_for(make_outline(feature_ids={}))
    result = write_script(caller, ctx)
    assert len(llm.calls) == 2 and result.attempts == 2
    assert "tối đa 1 scene before_after" in llm.calls[1]["prompt"]


def test_after_two_repairs_the_best_draft_is_kept_with_warnings(tmp_path: Path) -> None:
    caller, llm = caller_for(text_heavy(), tmp_path=tmp_path)
    result = write_script(caller, ctx_for(make_outline(feature_ids={})))
    assert len(llm.calls) == 3
    assert any(w.startswith("chưa đạt:") and "before_after" in w for w in result.warnings)


def test_soft_issues_count_failed_features_as_clips_only_when_pointing_is_available() -> None:
    ctx = ctx_for(make_outline(feature_ids={1: "create", 2: "broken"}))
    scenes = [good_scene(1, "hook"), good_scene(2, "feature_demo", feature="create")]
    scenes += [
        good_scene(3, "feature_demo", feature="broken"),
        good_scene(4, "feature_demo", feature="nav"),
    ]
    scenes += [good_scene(5, "cta")]
    draft = DraftScript.model_validate(good_output(scenes=scenes)["script"])
    assert not any("liền nhau" in i for i in soft_issues(draft, ctx))
    ctx.lite = None
    # without showcase_lite a failed feature has nothing to record, so it is no clip
    assert footage_ratio_of(draft, ctx) < 0.8


def footage_ratio_of(draft: DraftScript, ctx: Any) -> float:
    from app.script.writer import scene_facts

    return footage_ratio(scene_facts(draft, ctx))


# --- showcase_lite: hover, outline, never click ----------------------------------------------------


def lite_ctx(index: PageIndex | None = None) -> LiteContext:
    return LiteContext(make_profile(), index or PageIndex(), HOME)


def test_a_failed_feature_is_pointed_at_with_hovers_and_one_outline_but_no_click() -> None:
    result = visual_for_scene(
        "feature_demo", make_profile().features[4], HOME, scene_id="s3", lite=lite_ctx()
    )
    visual = result.visual
    kinds = [a["do"] for a in visual["actions"]]
    assert visual["mode"] == "recording" and kinds[0] == "goto"
    assert kinds.count("highlight") == 1 and kinds[-1] == "highlight"
    assert set(kinds) <= {"goto", "hover", "highlight"} and "click" not in kinds
    assert visual["actions"][-1]["text"] == "group" and not visual["show_setup"]


def test_data_dependent_controls_get_a_hidden_setup_with_different_sample_text() -> None:
    element = {
        "ref": "s1e3", "role": "link", "name": "Active", "text": "Active",
        "locator": {"role": "link", "name": "Active", "css": "a"},
    }  # fmt: skip
    profile = make_profile()
    broken = profile.features[4]
    broken.evidence[0].ref = "s1e3"
    index = PageIndex({PageIndex.key(HOME): {"url": HOME, "elements": [element]}})
    result = visual_for_scene(
        "feature_demo", broken, HOME, scene_id="s3", lite=LiteContext(profile, index, HOME)
    )
    visual = result.visual
    typed = [a for a in visual["setup"] if a["do"] == "type"]
    assert typed and typed[0]["text"] != "Buy milk"  # not the text the earlier demo typed
    assert visual["show_setup"] is False
    assert [a["do"] for a in visual["actions"]] == ["hover", "highlight"]


def test_showcase_lite_on_the_fixture_site_hovers_the_filters_and_clicks_nothing(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    visual = {
        "mode": "recording",
        "show_setup": False,
        "setup": [
            goto(site, "/todo.html"),
            {"do": "type", "locator": loc("#new"), "text": "Gọi điện cho khách hàng"},
        ],
        "actions": [
            {"do": "hover", "locator": loc("#filters a:nth-of-type(2)"), "target": "Active", "ms": 300},
            {"do": "hover", "locator": loc("#filters a:nth-of-type(3)"), "target": "Completed", "ms": 300},
            {"do": "highlight", "locator": loc("#filters a:nth-of-type(3)"), "text": "group", "ms": 1800},
        ],
    }  # fmt: skip
    r = rec(browser_session, site, tmp_path, visual, speech_ms=6000)
    assert r.kind == "recording" and r.warnings == [] and r.steps_failed == 0
    shown = [e for e in r.click_log if e["t_ms"] >= r.setup_end_ms]
    kinds = [e["type"] for e in shown]
    assert kinds.count("hover") == 2 and kinds.count("highlight") == 1 and "click" not in kinds
    hover_gap = [e["t_ms"] for e in shown if e["type"] == "hover"]
    assert hover_gap[1] - hover_gap[0] >= 900  # slow, deliberate movement between the two


def test_when_nothing_can_be_pointed_at_the_scene_falls_back_to_a_still_page(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    visual = {
        "mode": "recording",
        "actions": [
            goto(site, "/todo.html"),
            {"do": "hover", "locator": loc("#nope"), "target": "x", "ms": 300},
            {"do": "highlight", "locator": loc("#nope"), "text": "group", "ms": 1800},
        ],
    }
    r = rec(browser_session, site, tmp_path, visual, speech_ms=3000)
    assert r.kind == "fallback_screenshot" and r.image_path is not None


# --- honest duration -------------------------------------------------------------------------------


def concept(duration: int = 60) -> VideoConcept:
    return VideoConcept.model_validate(
        {
            "id": "c1", "angle": "overview", "title": "t", "goal": "awareness", "hook_example": "h",
            "feature_ids": ["create"], "beats": ["a", "b", "c", "d"], "duration_s": duration,
            "why": "w", "recommended": True,
        }
    )  # fmt: skip


def test_concepts_always_carry_the_recommended_duration_not_the_models_pick() -> None:
    profile = make_profile()  # 2 interaction + 1 navigation + 1 showcase = 13 + 10 + 10 + 6 + 5
    out = normalize_concepts([concept(60), concept(30)], profile)
    assert {c.duration_s for c in out} == {30}  # budget 44 -> 30


def test_the_outline_request_warns_when_the_video_is_longer_than_the_product_can_fill() -> None:
    profile = make_profile()
    long_request = build_request("j", make_outline(60), profile=profile)
    assert "tính năng trình diễn được" in long_request.message and "60s" in long_request.message
    assert "trình diễn được" not in build_request("j", make_outline(30), profile=profile).message
    assert oversize_warning(30, budget_for(profile)) is None


def test_forced_duration_lets_every_scene_grow_within_the_agreed_caps() -> None:
    script = scripted_script(60)
    items = [
        VoiceoverItem(scene_id="s2", voiceover=words(35)),
        VoiceoverItem(scene_id="s1", voiceover=words(20)),
        VoiceoverItem(scene_id="s5", voiceover=words(21)),
    ]
    grown, notes = apply_voiceovers(script, items, extend=True, forced=True)
    by_id = {s.root.id: s.root.voiceover.split() for s in grown.scenes}
    assert len(by_id["s2"]) == 35 and len(by_id["s1"]) == 20 and len(by_id["s5"]) == 18
    assert any("s5" in n and "vượt 20" in n for n in notes)
    plain, plain_notes = apply_voiceovers(script, items, extend=True, forced=False)
    assert len(plain.scenes[0].root.voiceover.split()) == 18  # hook untouched
    assert any("chỉ được kéo dài scene feature_demo" in n for n in plain_notes)
    assert any("s2" in n and "vượt 30" in n for n in plain_notes)


def test_repeat_operations_adds_the_verified_typing_step_with_other_texts() -> None:
    script = scripted_script(60)
    report = FitReport(60000, 40000, 40000)
    more = repeat_operations(script, report)
    scene = next(s.root for s in more.scenes if s.root.id == "s2")
    typed = [a for a in scene.visual.actions if a.do == "type"]
    assert len(typed) == 3 and len({a.text for a in typed}) == 3
    assert typed[0].locator == typed[1].locator  # same verified element, nothing new invented
    assert report.actions and "lặp" in report.actions[0]
    again = repeat_operations(more, FitReport(60000, 40000, 40000))
    added = [
        a.text
        for s in again.scenes
        for a in s.root.visual.actions
        if a.do == "type" and a.text != "Buy milk"  # the fixture's own sample text
    ]
    assert len(added) == len(set(added))  # a sample text is never reused


def test_a_forced_video_is_stretched_by_longer_voiceovers_and_repeated_steps(
    tmp_path: Path,
) -> None:
    ctx = ctx_for(make_outline(60))
    ctx.forced = True
    assert ctx.demo_max_words == 35
    script = scripted_script(60)
    long_words = {"s2": words(35), "s3": words(35), "s1": words(20), "s5": words(20)}

    def answer(_prompt: str) -> dict[str, Any]:
        return {"voiceovers": [{"scene_id": k, "voiceover": v} for k, v in long_words.items()]}

    from tests.conftest import FakeLLM

    caller = JsonCaller(FakeLLM(answer), cache_dir=tmp_path)
    fitted, report = fit_duration(caller, script, ctx)
    assert any("lặp" in a for a in report.actions)
    assert report.estimated_ms > report.initial_ms
    assert "35 từ" in caller.llm.calls[0]["prompt"] and "20 từ" in caller.llm.calls[0]["prompt"]  # type: ignore[attr-defined]
    assert fitted.scenes[1].root.voiceover.split().__len__() == 35


def scripted_script(duration: int) -> Script:
    """A script made by the real writer from the fixture profile (visuals included)."""
    from app.script.writer import build_script

    draft = DraftScript.model_validate(good_output()["script"])
    ctx = ctx_for(make_outline(duration))
    script, _ = build_script(draft, ctx)
    return script.model_copy(update={"target_duration_s": duration})
