from pathlib import Path

from app.llm.json_call import JsonCaller
from app.proposal.wordlimit import (
    cut_words,
    enforce_concepts,
    enforce_outline,
    shorten,
    word_count,
)
from app.schemas.generated.outline import Outline
from app.schemas.generated.video_concept import VideoConcept
from tests.conftest import FakeLLM, scripted_handler

LONG = " ".join(f"từ{i}" for i in range(20))  # 20 words


def caller(tmp_path: Path, handler=scripted_handler) -> tuple[JsonCaller, FakeLLM]:  # type: ignore[no-untyped-def]
    llm = FakeLLM(handler)
    return JsonCaller(llm, cache_dir=tmp_path), llm


def test_word_count_and_cut() -> None:
    assert word_count("một hai  ba\nbốn") == 4
    assert cut_words("một, hai, ba, bốn", 3) == "một, hai, ba"
    assert cut_words("ngắn thôi", 5) == "ngắn thôi"


def test_nothing_over_the_limit_means_no_llm_call(tmp_path: Path) -> None:
    c, llm = caller(tmp_path)
    assert shorten(c, {"a": ("ngắn gọn", 15)}, "outline") == ({}, [])
    assert llm.calls == []


def test_only_the_lines_over_the_limit_go_to_the_llm_once(tmp_path: Path) -> None:
    c, llm = caller(tmp_path)
    fixed, warnings = shorten(c, {"short": ("ngắn gọn", 15), "long": (LONG, 15)}, "outline")
    assert set(fixed) == {"long"} and warnings == []
    assert word_count(fixed["long"]) <= 15
    assert len(llm.calls) == 1
    assert "ngắn gọn" not in llm.calls[0]["prompt"].split("<lines>")[1]  # not sent: it is fine


def test_still_too_long_after_the_llm_is_cut_with_a_warning(tmp_path: Path) -> None:
    c, _ = caller(tmp_path, lambda p: {"lines": [{"id": "x", "text": LONG}]})
    fixed, warnings = shorten(c, {"x": (LONG, 15)}, "outline")
    assert word_count(fixed["x"]) == 15
    assert len(warnings) == 1 and "x" in warnings[0] and "15" in warnings[0]


def test_llm_failure_falls_back_to_cutting(tmp_path: Path) -> None:
    c, _ = caller(tmp_path, lambda p: "not json")
    fixed, warnings = shorten(c, {"x": (LONG, 15)}, "outline")
    assert word_count(fixed["x"]) == 15 and len(warnings) >= 1


def concept(hook: str, beats: list[str]) -> VideoConcept:
    return VideoConcept.model_validate(
        {"id": "c1", "angle": "overview", "title": "t", "goal": "awareness", "hook_example": hook,
         "feature_ids": [], "beats": beats, "duration_s": 30, "why": "w", "recommended": True}
    )  # fmt: skip


def test_concept_hook_limit_is_12_and_beats_15(tmp_path: Path) -> None:
    c, llm = caller(tmp_path)
    hook13 = " ".join(["h"] * 13)
    ok_hook = " ".join(["h"] * 12)
    concepts = [concept(hook13, ["một", LONG, "ba", "bốn"]), concept(ok_hook, ["a", "b", "c", "d"])]
    concepts[1].id = "c2"
    warnings = enforce_concepts(c, concepts)
    assert word_count(concepts[0].hook_example) <= 12
    assert word_count(concepts[0].beats[1]) <= 15
    assert concepts[0].beats[0] == "một" and concepts[1].hook_example == ok_hook  # untouched
    assert warnings == [] and len(llm.calls) == 1


def test_outline_beats_over_15_words_are_shortened_and_reported(tmp_path: Path) -> None:
    c, _ = caller(tmp_path)
    outline = Outline.model_validate(
        {"concept_id": "c1", "title": "t", "goal": "awareness", "duration_s": 30, "feature_ids": [],
         "beats": [{"id": "b1", "text": "mở đầu"}, {"id": "b2", "text": LONG}, {"id": "b3", "text": "cta"}]}
    )  # fmt: skip
    changes, warnings = enforce_outline(c, outline)
    assert [b.id for b in outline.beats] == ["b1", "b2", "b3"]
    assert outline.beats[0].text == "mở đầu" and outline.beats[2].text == "cta"
    assert word_count(outline.beats[1].text) <= 15
    assert len(changes) == 1 and "b2" in changes[0] and warnings == []
