import io
import json
from pathlib import Path

import pytest
from jinja2 import UndefinedError
from PIL import Image
from pydantic import BaseModel

from app.core.usage import BudgetExceeded, UsageTracker
from app.llm.images import prepare_image
from app.llm.json_call import JsonCaller, LLMCallError, VisionUnavailable
from app.llm.prompts import PROMPTS, render
from tests.conftest import FakeLLM


class Answer(BaseModel):
    sum: int


def png(size: tuple[int, int], color: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


# --- prompts ------------------------------------------------------------------------------------

SAMPLE_VARS = {
    "page_analyzer": dict(url="u", title="t", headings="h", key_texts="k", elements="e1 | link | A | nav", signals="{}"),
    "product_synthesizer": dict(root_url="u", site_type="landing", title="t", meta_description="m",
                                og_description="o", page_insights_json="[]", sample_files="- sample.jpg: ảnh", delta_json="", known_features="", known_intents=""),
    "concept_proposer": dict(
        confirmed_product_profile_json="{}", selected_features_json="[]", user_notes_or_empty="", recommended_duration_s=30
    ),
    "outline_editor": dict(confirmed_profile_summary="s", concept_json="{}", version=1,
                           outline_json="{}", instruction="sửa"),
    "site_classifier": dict(url="u", title="t", meta_description="m", headings="h", signals="{}", heuristic="x"),
    "shortener": dict(lines_json="[]"),
    "beat_feature_mapper": dict(outline_json="{}", features_json="[]"),
    "script_writer": dict(
        product_profile_json="{}", outline_json="{}", theme_json="{}", scene_catalog_json="{}",
        allowed_icons="check, globe", duration_s=45, target_words=110, flow_json="",
        proof_json="", framework="", product_name="P", home_domain="x.test",
        forbidden_phrases="a", hook_kinds="b", hook_max_words=12, on_screen_max_words=5,
    ),
    "duration_fit": dict(
        direction="ngắn hơn", target_words=110, current_words=80, script_json="{}",
        product_profile_summary="s", forced=False,
    ),
    "scene_writer": dict(
        task_type="rewrite", instruction="i", fields="voiceover", scene_type="hook",
        current_scene_json_or_null="null", prev_scene_summary_or_none="none",
        next_scene_summary_or_none="none", goal="awareness", duration_s=30, headline="h",
        product_profile_summary="s", forced=False, scene_catalog_json="{}", allowed_icons="check",
        proof_json="",
    ),
    "copy_critic": dict(
        persona="p", goal="g", value="v", chapters_summary="c", proof_bank_json_or_empty="",
        script_compact_json="{}",
    ),
    "flow_agent": dict(
        title="t", persona="p", goal="g", expected_steps="a; b", success_signal="s",
        submit_policy="stop", user_notes_or_none="không có", sample_data_json_or_empty="{}",
        steps_so_far="(chưa có)", url="https://x.test/", page_title="T", main_heading="H",
        messages="không có", elements="e1 | button | Apply | - | - | - | - | main", warnings="",
    ),
    "flow_discovery": dict(
        product_profile_summary="p", pages_summary="pg", mode="propose", user_description_or_empty="",
    ),
    "focus_planner": dict(
        phrases_json="[]", actions_json="[]", inventory_json="[]", scene_kind="feature_demo",
        feature_name="f", key_point="k",
    ),
    "edit_planner": dict(
        version=1, script_json="{}", product_profile_json="{}", targets_json="[]",
        instruction="sửa", layouts_by_type="{}",
    ),
}  # fmt: skip


@pytest.mark.parametrize("name", [*PROMPTS, "site_classifier", "shortener"])
def test_every_prompt_renders_with_all_variables_and_mentions_json(name: str) -> None:
    text = render(name, **SAMPLE_VARS[name])
    assert "json" in text.lower()
    assert "{{" not in text  # no unrendered placeholder left behind


@pytest.mark.parametrize("name", [*PROMPTS, "site_classifier", "shortener"])
def test_prompt_with_a_missing_variable_fails(name: str) -> None:
    variables = dict(SAMPLE_VARS[name])
    variables.pop(next(iter(variables)))
    with pytest.raises(UndefinedError):
        render(name, **variables)


def test_verbatim_prompt_comments_are_kept() -> None:
    text = render("page_analyzer", **SAMPLE_VARS["page_analyzer"])
    assert "// mỗi dòng: ref | role | name | vị trí" in text
    assert "// 0-1: trang có đủ nội dung" in text


# --- images -------------------------------------------------------------------------------------


def test_prepare_image_resizes_long_side_to_1280_jpeg() -> None:
    url, digest = prepare_image(png((2560, 1440)))
    assert url.startswith("data:image/jpeg;base64,") and len(digest) == 64
    import base64

    img = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert max(img.size) == 1280 and img.size == (1280, 720)


def test_prepare_image_never_upscales() -> None:
    import base64

    url, _ = prepare_image(png((300, 200)))
    assert Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).size == (300, 200)


# --- JsonCaller ---------------------------------------------------------------------------------


def test_call_repairs_invalid_output_and_counts_tokens(tmp_path: Path) -> None:
    replies = iter(['{"sum": "x"}', "not json", '{"sum": 5}'])
    llm = FakeLLM(lambda _: next(replies))
    tracker = UsageTracker()
    caller = JsonCaller(llm, tracker=tracker, cache_dir=tmp_path)
    assert caller.call("t", "tính json", Answer).sum == 5
    assert len(llm.calls) == 3 and llm.calls[2]["n_msgs"] == 5  # two repair rounds appended
    assert tracker.steps["t"] == {"input": 300, "output": 150, "calls": 3}
    log = (tmp_path / "llm-log.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(log[-1])["attempts"] == 3 and json.loads(log[-1])["ok"] is True


def test_call_gives_up_after_two_repairs(tmp_path: Path) -> None:
    llm = FakeLLM(lambda _: "nope")
    caller = JsonCaller(llm, cache_dir=tmp_path)
    with pytest.raises(LLMCallError):
        caller.call("t", "json", Answer)
    assert len(llm.calls) == 3  # first try + 2 repairs


def test_call_requires_the_word_json(tmp_path: Path) -> None:
    caller = JsonCaller(FakeLLM(lambda _: {"sum": 1}), cache_dir=tmp_path)
    with pytest.raises(ValueError, match="json"):
        caller.call("t", "no keyword here", Answer)


def test_cache_hit_skips_the_model(tmp_path: Path) -> None:
    llm = FakeLLM(lambda _: {"sum": 2})
    caller = JsonCaller(llm, cache_enabled=True, cache_dir=tmp_path)
    assert caller.call("t", "json a", Answer).sum == 2
    assert caller.call("t", "json a", Answer).sum == 2
    assert len(llm.calls) == 1
    caller.call("t", "json b", Answer)  # different prompt -> different key
    assert len(llm.calls) == 2


def test_cache_key_includes_image_hash(tmp_path: Path) -> None:
    llm = FakeLLM(lambda _: {"sum": 2})
    caller = JsonCaller(llm, cache_enabled=True, cache_dir=tmp_path)
    caller.call("t", "json", Answer, images=[png((64, 64), (255, 0, 0))])
    caller.call("t", "json", Answer, images=[png((64, 64), (0, 0, 255))])
    caller.call("t", "json", Answer, images=[png((64, 64), (255, 0, 0))])
    assert len(llm.calls) == 2


def test_images_use_the_vision_model_and_fail_without_one(tmp_path: Path) -> None:
    llm = FakeLLM(lambda _: {"sum": 1})
    JsonCaller(llm, cache_dir=tmp_path).call("t", "json", Answer, images=[png((64, 64))])
    assert llm.calls[0]["model"] == "fake-vision" and llm.calls[0]["images"] is True
    blind = JsonCaller(FakeLLM(lambda _: {"sum": 1}, vision_model=None), cache_dir=tmp_path)
    assert not blind.can_see_images
    with pytest.raises(VisionUnavailable):
        blind.call("t", "json", Answer, images=[png((64, 64))])


def test_token_ceiling_stops_before_the_next_call(tmp_path: Path) -> None:
    llm = FakeLLM(lambda _: {"sum": 1})
    caller = JsonCaller(llm, tracker=UsageTracker(max_tokens=200), cache_dir=tmp_path)
    caller.call("a", "json 1", Answer)  # uses 150
    caller.call("a", "json 2", Answer)  # still < 200 at check time, ends at 300
    with pytest.raises(BudgetExceeded):
        caller.call("a", "json 3", Answer)
    assert len(llm.calls) == 2
