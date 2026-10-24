import json
from pathlib import Path
from typing import Any

import pytest

from app.llm.json_call import JsonCaller
from app.schemas.generated.layouts import LAYOUTS_BY_TYPE
from app.schemas.generated.outline import Outline
from app.schemas.generated.product_profile import ProductProfile
from app.schemas.generated.theme import Theme
from app.script import catalog as cat
from app.script.visuals import load_setup_counts, visual_for_scene
from app.script.writer import (
    MAX_REPAIRS,
    WriterContext,
    WriterError,
    build_prompt,
    check_draft,
    target_words,
    write_script,
)
from tests.conftest import FakeLLM, _section
from tests.test_explorer import feature, profile

HOME = "https://todo.example/"
THEME = Theme(
    primary="#4F46E5", accent="#F59E0B", font="Be Vietnam Pro", motion_preset="energetic",
    caption_style="karaoke", music_mood="upbeat", voice_id="v", language="vi",
)  # fmt: skip


def loc(name: str, css: str = "button") -> dict[str, Any]:
    return {"role": "button", "name": name, "css": css}


def step(do: str, name: str | None = None, text: str | None = None, ref: str | None = None) -> dict:  # type: ignore[type-arg]
    return {"do": do, "url": HOME, "ref": ref, "text": text, "locator": loc(name) if name else None}


def feat(fid: str, kind: str | None, steps: list[dict], **extra: Any) -> dict[str, Any]:  # type: ignore[type-arg]
    return {
        **feature(fid, None, steps, url=HOME),
        "name": f"Tính năng {fid}",
        "demo_kind": kind,
        **extra,
    }


def make_profile() -> ProductProfile:
    return profile(
        [
            feat(
                "create",
                "interaction",
                [step("goto"), step("type", "Todo input", "Buy milk", "e1")],
            ),
            feat(
                "filter",
                "interaction",
                [
                    step("goto"),
                    step("type", "Todo input", "Buy milk", "e1"),
                    step("goto"),
                    step("click", "Active"),
                    step("click", "Completed"),
                ],
                requires_setup=True,
            ),  # fmt: skip
            feat("nav", "navigation", [step("goto"), step("click", "Pricing")]),
            feat(
                "story",
                "showcase",
                [],
                showcase_target={
                    "url": HOME + "about",
                    "selector": "#story",
                    "text_quote": "Câu chuyện của chúng tôi",
                },
            ),  # fmt: skip
            feat("broken", "failed", [step("goto")]),
            feat("unchecked", None, []),
        ]
    )


def make_outline(duration: int = 45, feature_ids: dict[int, str] | None = None) -> Outline:
    texts = [
        "Bạn hay quên việc?",
        "Gõ việc rồi nhấn Enter",
        "Lọc việc đang làm",
        "Xem câu chuyện",
        "Thử ngay",
    ]
    links = {1: "create", 2: "filter"} if feature_ids is None else feature_ids
    return Outline.model_validate(
        {
            "concept_id": "c1", "title": "Việc nhanh", "goal": "awareness", "duration_s": duration,
            "feature_ids": ["create", "filter", "nav", "story"],
            "beats": [{"id": f"b{i + 1}", "text": t, "feature_id": links.get(i)} for i, t in enumerate(texts)],
        }
    )  # fmt: skip


def ctx_for(outline: Outline | None = None, setup: dict[str, int] | None = None) -> WriterContext:
    return WriterContext(make_profile(), outline or make_outline(), THEME, HOME, setup or {})


def words(n: int, prefix: str = "từ") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def good_scene(i: int, type_: str, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": f"s{i}", "type": type_, "layout": LAYOUTS_BY_TYPE[type_][0],
        "voiceover": words(18, f"s{i}v"), "on_screen_text": "Chữ ngắn", "key_point": f"Ý chính {i}",
        "icon": cat.ICONS[i % len(cat.ICONS)], "visual": {"mode": "auto"},
    }  # fmt: skip
    return {**base, **extra}


def good_output(**patch: Any) -> dict[str, Any]:
    scenes = [
        good_scene(1, "hook"),
        good_scene(2, "feature_demo", feature="create"),
        good_scene(3, "feature_demo", feature="filter", show_setup=True),
        good_scene(
            4, "before_after", before_text="Rối ren", after_text="Gọn gàng", layout="split_vertical"
        ),
        good_scene(5, "cta"),
    ]
    script = {
        "title": "Việc nhanh", "template": "desktop_showcase", "badge": "QUẢN LÝ VIỆC",
        "headline": "Quản lý công việc nhanh gấp đôi", "headline_highlight": "nhanh gấp đôi",
        "scenes": scenes,
    }  # fmt: skip
    return {
        "script": {**script, **patch},
        "summary": [{"scene_id": f"s{i}", "one_liner": f"Cảnh {i}"} for i in range(1, 6)],
        "warnings": [],
    }


def caller_for(*outputs: dict[str, Any], tmp_path: Path) -> tuple[JsonCaller, FakeLLM]:
    queue = list(outputs)
    llm = FakeLLM(lambda _p: queue.pop(0) if len(queue) > 1 else queue[0])
    return JsonCaller(llm, cache_dir=tmp_path), llm


# --- visuals come from the verified data ------------------------------------------------------


def visual(fid: str | None, scene_type: str = "feature_demo", **kw: Any):  # type: ignore[no-untyped-def]
    feature_obj = {f.id: f for f in make_profile().features}.get(fid or "")
    return visual_for_scene(scene_type, feature_obj, HOME, scene_id="s2", **kw)


def test_interaction_actions_are_the_verified_steps_with_their_locators() -> None:
    result = visual("create")
    v = result.visual
    assert v["mode"] == "recording" and v["setup"] == [] and v["show_setup"] is False
    assert [a["do"] for a in v["actions"]] == ["goto", "type"]
    typed = v["actions"][1]
    assert typed["text"] == "Buy milk" and typed["locator"]["name"] == "Todo input"
    assert typed["locator"]["css"] == "button" and typed["target"] == "Todo input"
    assert result.warnings == []


def test_clicks_are_marked_for_zoom() -> None:
    v = visual("nav").visual
    assert [(a["do"], a["zoom"]) for a in v["actions"][1:]] == [("click", True)]


def test_setup_steps_are_split_off_and_the_reload_goto_dropped() -> None:
    result = visual("filter", setup_len=2, show_setup=True)
    v = result.visual
    assert [a["do"] for a in v["setup"]] == ["goto", "type"]
    assert [(a["do"], a.get("target")) for a in v["actions"]] == [
        ("click", "Active"),
        ("click", "Completed"),
    ]
    assert v["show_setup"] is True  # the writer chose to show the setup


def test_show_setup_defaults_to_false_and_needs_a_setup() -> None:
    assert visual("filter", setup_len=2).visual["show_setup"] is False
    result = visual("create", show_setup=True)  # no setup to show
    assert result.visual["show_setup"] is False


def test_an_unsplittable_setup_means_all_steps_are_actions_with_a_warning() -> None:
    result = visual("filter", setup_len=None, show_setup=True)
    assert result.visual["setup"] == [] and result.visual["show_setup"] is False
    assert [a["do"] for a in result.visual["actions"]] == ["goto", "type", "goto", "click", "click"]
    assert any("setup" in w for w in result.warnings)


def test_showcase_is_goto_scroll_to_and_highlight_for_1800_ms() -> None:
    v = visual("story").visual
    assert v["mode"] == "recording"
    goto, scroll, highlight = v["actions"]
    assert goto == {"do": "goto", "url": HOME + "about"}
    assert scroll["do"] == "scroll_to" and scroll["locator"]["css"] == "#story"
    assert highlight["do"] == "highlight" and highlight["ms"] == 1800
    assert highlight["locator"]["text"].startswith("Câu chuyện")


@pytest.mark.parametrize("fid", ["broken", "unchecked", None])
def test_features_that_cannot_be_demonstrated_become_a_home_page_screenshot(
    fid: str | None,
) -> None:
    result = visual(fid)
    assert result.visual == {"mode": "screenshot", "page": HOME, "actions": []}
    assert result.warnings and "s2" in result.warnings[0]


def test_other_scene_types() -> None:
    assert visual(None, "hook").visual["mode"] == "screenshot"
    assert visual(None, "cta").visual["mode"] == "template"
    assert visual(None, "before_after").visual["mode"] == "template"


def test_setup_counts_come_from_the_explore_pages_and_must_match_the_steps(tmp_path: Path) -> None:
    pages = tmp_path / "pages"
    pages.mkdir()
    setup = [
        {"do": "goto", "url": HOME, "ref": None, "text": None},
        {"do": "type", "url": HOME, "ref": "e1", "text": "Buy milk"},
    ]
    (pages / "1.json").write_text(json.dumps({"url": HOME, "setup_steps": []}), encoding="utf-8")
    (pages / "2.json").write_text(json.dumps({"url": HOME, "setup_steps": setup}), encoding="utf-8")
    assert load_setup_counts(tmp_path, make_profile()) == {"filter": 2}
    setup[1]["text"] = "something else"
    (pages / "2.json").write_text(json.dumps({"url": HOME, "setup_steps": setup}), encoding="utf-8")
    assert load_setup_counts(tmp_path, make_profile()) == {}


# --- catalog ---------------------------------------------------------------------------------------


def test_icons_and_catalog_come_from_the_schema() -> None:
    assert set(cat.ICONS) == {"check", "globe", "bolt", "link", "star", "users", "chart", "lock",
                              "sparkles", "code", "image", "edit", "filter", "upload"}  # fmt: skip
    catalog = cat.scene_catalog()
    for t, layouts in LAYOUTS_BY_TYPE.items():
        assert catalog[t]["layouts"] == list(layouts)
    assert (
        "feature" in catalog["feature_demo"]["fields"]
        and "feature" not in catalog["hook"]["fields"]
    )
    assert "before_text" in catalog["before_after"]["fields"]
    assert "visual" not in catalog["hook"]["fields"]


def test_target_words_leave_room_for_each_scenes_pause() -> None:
    assert target_words(45, 5) == 109
    assert target_words(30, 4) == 72


# --- the writer ------------------------------------------------------------------------------------


def test_prompt_carries_what_the_writer_needs() -> None:
    prompt = build_prompt(ctx_for())
    assert prompt.startswith("Bạn là biên kịch short video marketing (TikTok/YouTube Shorts)")
    assert "Thời lượng mục tiêu: 45 giây" in prompt and "khoảng 109 từ" in prompt
    profile_json = json.loads(_section(prompt, "product"))
    by_id = {f["id"]: f for f in profile_json["features"]}
    assert (
        by_id["create"]["demo_steps"] == "gõ «Buy milk»"
        and by_id["filter"]["requires_setup"] is True
    )
    assert "locator" not in _section(prompt, "product")
    assert json.loads(_section(prompt, "outline"))["beats"][1]["feature_id"] == "create"
    assert "check" in _section(prompt, "allowed_icons") and "feature_demo" in _section(
        prompt, "scene_catalog"
    )


def test_a_good_draft_becomes_a_script_with_code_made_visuals(tmp_path: Path) -> None:
    caller, llm = caller_for(good_output(), tmp_path=tmp_path)
    result = write_script(caller, ctx_for(setup={"filter": 2}))
    s = result.script
    assert result.attempts == 1 and len(llm.calls) == 1
    assert s.template == "desktop_showcase" and s.goal == "awareness" and s.target_duration_s == 45
    assert s.theme.primary == "#4F46E5" and s.headline_highlight == "nhanh gấp đôi"
    assert [x.root.id for x in s.scenes] == ["s1", "s2", "s3", "s4", "s5"]
    assert [x.root.visual.mode for x in s.scenes] == [
        "screenshot",
        "recording",
        "recording",
        "template",
        "template",
    ]
    filt = s.scenes[2].root
    assert [a.do for a in filt.visual.setup] == ["goto", "type"] and filt.visual.show_setup is True
    assert [a.do for a in filt.visual.actions] == ["click", "click"]
    assert [x["one_liner"] for x in result.summary] == [f"Cảnh {i}" for i in range(1, 6)]


def test_the_models_own_visual_and_ids_are_ignored(tmp_path: Path) -> None:
    out = good_output()
    out["script"]["scenes"][1]["visual"] = {
        "mode": "recording",
        "actions": [{"do": "click", "target": "bịa"}],
    }
    out["script"]["scenes"][1]["id"] = "weird"
    caller, _ = caller_for(out, tmp_path=tmp_path)
    s = write_script(caller, ctx_for()).script
    assert s.scenes[1].root.id == "s2"
    assert all(a.target != "bịa" for a in s.scenes[1].root.visual.actions)


def test_failed_features_get_a_screenshot_and_a_warning(tmp_path: Path) -> None:
    out = good_output()
    out["script"]["scenes"][3] = good_scene(4, "feature_demo", feature="broken")
    caller, _ = caller_for(out, tmp_path=tmp_path)
    result = write_script(caller, ctx_for())
    assert result.script.scenes[3].root.visual.mode == "screenshot"
    assert any("broken" in w for w in result.warnings)


def test_a_draft_over_the_limits_is_sent_back_with_the_errors_and_fixed_on_the_second_try(
    tmp_path: Path,
) -> None:
    bad = good_output(headline="x" * 50, headline_highlight="nhanh gấp đôi", badge="B" * 30)
    bad["script"]["scenes"][0]["voiceover"] = words(45)
    bad["script"]["scenes"][1]["key_point"] = "k" * 70
    caller, llm = caller_for(bad, good_output(), tmp_path=tmp_path)
    result = write_script(caller, ctx_for())
    assert result.attempts == 2 and len(llm.calls) == 2
    second = llm.calls[1]["prompt"]
    assert "<previous_output>" in second and "Kịch bản trên còn lỗi" in second
    for expected in (
        "headline dài 50",
        "badge dài 30",
        "scene 1: voiceover có 45 từ",
        "key_point dài 70",
    ):
        assert expected in second, expected
    assert [len(h) > 0 for h in result.errors_history] == [True, False]


def test_it_gives_up_after_two_repairs(tmp_path: Path) -> None:
    bad = good_output(headline="x" * 50)
    caller, llm = caller_for(bad, tmp_path=tmp_path)
    with pytest.raises(WriterError) as e:
        write_script(caller, ctx_for())
    assert len(llm.calls) == MAX_REPAIRS + 1
    assert any("headline" in x for x in e.value.errors)


def test_a_demoable_beat_must_become_a_feature_demo_of_its_feature() -> None:
    ctx = ctx_for()
    draft = good_output()["script"]
    draft["scenes"][1] = good_scene(2, "feature_demo", feature="nav")  # beat 2 shows «create»
    from app.script.writer import DraftScript

    errors = check_draft(DraftScript.model_validate(draft), ctx)
    assert any("beat b2" in e and "create" in e for e in errors)
    draft["scenes"][1] = good_scene(2, "hook")
    assert any("feature_demo" in e for e in check_draft(DraftScript.model_validate(draft), ctx))


def test_beats_of_failed_features_do_not_force_a_feature_demo() -> None:
    ctx = ctx_for(make_outline(feature_ids={1: "broken", 2: "unchecked"}))
    from app.script.writer import DraftScript

    draft = DraftScript.model_validate(good_output()["script"])
    draft.scenes[1] = DraftScript.model_validate(
        {
            "headline": "h",
            "scenes": [
                good_scene(2, "before_after", before_text="a", after_text="b", layout="swipe")
            ],
        }
    ).scenes[0]
    draft.scenes[2] = draft.scenes[1].model_copy(update={"key_point": "Ý khác"})
    assert not any("trình diễn" in e for e in check_draft(draft, ctx))


@pytest.mark.parametrize(
    ("patch", "expected"),
    [
        ({"layout": "nope"}, "layout «nope»"),
        ({"voiceover": words(4)}, "voiceover có 4 từ"),
        ({"voiceover": words(31)}, "voiceover có 31 từ"),
        ({"on_screen_text": words(7)}, "on_screen_text quá 6 từ"),
        ({"key_point": ""}, "thiếu key_point"),
        ({"icon": "rocket"}, "icon «rocket»"),
        ({"icon": None}, "icon «None»"),
        ({"feature": "create"}, "chỉ feature_demo mới có field feature"),
        ({"before_text": "x"}, "chỉ before_after"),
    ],
)
def test_each_limit_is_reported_in_words_the_model_can_act_on(
    patch: dict[str, Any], expected: str
) -> None:
    from app.script.writer import DraftScript

    draft = good_output()["script"]
    draft["scenes"][0] = {**draft["scenes"][0], **patch}
    errors = check_draft(DraftScript.model_validate(draft), ctx_for())
    assert any(expected in e for e in errors), errors


def test_scene_count_order_and_duplicate_key_points() -> None:
    from app.script.writer import DraftScript

    draft = good_output()["script"]
    draft["scenes"] = draft["scenes"][:4]
    assert any(
        "cần đúng 5 scene" in e for e in check_draft(DraftScript.model_validate(draft), ctx_for())
    )
    draft = good_output()["script"]
    draft["scenes"][4]["type"] = "hook"
    draft["scenes"][4]["layout"] = "emoji_pop"
    draft["scenes"][3]["key_point"] = draft["scenes"][2]["key_point"].upper()
    errors = check_draft(DraftScript.model_validate(draft), ctx_for())
    assert any("scene cuối phải là cta" in e for e in errors)
    assert any("trùng" in e for e in errors)


def test_a_highlight_that_is_not_in_the_headline_is_an_error() -> None:
    from app.script.writer import DraftScript

    draft = good_output(headline_highlight="không có trong tiêu đề")["script"]
    assert any("chuỗi con" in e for e in check_draft(DraftScript.model_validate(draft), ctx_for()))
