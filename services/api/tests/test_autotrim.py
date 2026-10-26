from pathlib import Path
from typing import Any

import pytest

from app.core.trim_text import trim_chars, trim_highlight, trim_lines, trim_words, words_of
from app.script import catalog as cat
from app.script.writer import DraftScript, WriterError, write_script
from tests.test_script_writer import caller_for, ctx_for, good_output, words

# --- the pure cuts ---------------------------------------------------------------------------------


def test_text_over_the_character_limit_is_cut_at_a_word_boundary() -> None:
    badge = "QUẢN LÝ CÔNG VIỆC NHANH GỌN"  # 27 characters
    assert len(badge) > 24
    out = trim_chars(badge, 24)
    assert out == "QUẢN LÝ CÔNG VIỆC NHANH" and len(out) <= 24
    assert (
        badge.startswith(out) and badge[len(out)] == " "
    )  # the next thing was a space: no word cut


def test_a_25_character_badge_is_cut_to_24_or_less() -> None:
    badge = "Tiết kiệm thời gian ngay!"
    assert len(badge) == 25
    out = trim_chars(badge, 24)
    assert len(out) <= 24 and out == "Tiết kiệm thời gian ngay"


def test_dangling_punctuation_is_dropped_and_short_text_is_untouched() -> None:
    assert trim_chars("Nhanh, gọn, đẹp - và rẻ hơn", 15) == "Nhanh, gọn, đẹp"
    assert trim_chars("  ngắn  ", 24) == "ngắn"
    assert trim_chars("x" * 50, 10) == "x" * 10  # one endless word: hard cut


def test_voiceover_over_the_word_limit_loses_its_last_sentences() -> None:
    text = f"{words(10, 'a')}. {words(10, 'b')}. {words(10, 'c')}."
    out = trim_words(text, 25)
    assert words_of(out) <= 25 and out.endswith("b9.") and "c0" not in out


def test_a_single_long_sentence_loses_its_last_clauses_then_words() -> None:
    sentence = f"{words(8, 'a')}, {words(8, 'b')}, {words(8, 'c')}."
    out = trim_words(sentence, 18)
    assert out == f"{words(8, 'a')}, {words(8, 'b')}." and words_of(out) <= 18
    flat = trim_words(words(40), 12)
    assert words_of(flat) == 12 and flat.endswith(".")


def test_a_highlight_survives_only_while_it_is_part_of_the_headline() -> None:
    assert trim_highlight("Quản lý nhanh gấp đôi", "nhanh gấp đôi") == "nhanh gấp đôi"
    assert trim_highlight("Quản lý nhanh", "nhanh gấp đôi") is None
    assert trim_highlight("x", None) is None
    assert trim_lines("a\n\nb\nc", 2) == "a\nb"


# --- the writer never fails for form ----------------------------------------------------------------


def run(tmp_path: Path, **patch: Any):  # type: ignore[no-untyped-def]
    caller, llm = caller_for(
        good_output(**patch), tmp_path=tmp_path
    )  # the same bad draft each time
    return write_script(caller, ctx_for()), llm


def test_a_badge_of_25_characters_does_not_fail_the_job(tmp_path: Path) -> None:
    result, llm = run(tmp_path, badge="Tiết kiệm thời gian ngay!")
    assert len(llm.calls) == 3  # the model had its two repairs first
    assert result.script.badge == "Tiết kiệm thời gian ngay"
    assert any(w.startswith("auto_trimmed: badge") and "→" in w for w in result.warnings)


def test_a_headline_cut_that_loses_the_highlight_makes_the_highlight_null(tmp_path: Path) -> None:
    headline = "Quản lý công việc của cả đội trong một ngày nhanh gấp đôi"  # 58 chars
    result, _ = run(tmp_path, headline=headline, headline_highlight="nhanh gấp đôi")
    assert len(result.script.headline) <= cat.HEADLINE_MAX
    assert result.script.headline_highlight is None
    assert any("headline_highlight" in w for w in result.warnings)


def test_a_highlight_inside_the_kept_part_stays(tmp_path: Path) -> None:
    headline = "Nhanh gấp đôi cho cả đội làm việc cùng nhau mỗi ngày"
    result, _ = run(tmp_path, headline=headline, headline_highlight="Nhanh gấp đôi")
    assert result.script.headline_highlight == "Nhanh gấp đôi"


def test_every_scene_field_is_brought_within_its_limit(tmp_path: Path) -> None:
    draft = good_output()["script"]
    draft["scenes"][0].update(
        voiceover=f"{words(20, 'x')}. {words(20, 'y')}.",
        on_screen_text=words(9),
        key_point="k" * 80,
        icon="not-an-icon",
    )
    draft["scenes"][1].update(voiceover=words(60))
    caller, _ = caller_for({**good_output(), "script": draft}, tmp_path=tmp_path)
    result = write_script(caller, ctx_for())
    s1, s2 = result.script.scenes[0].root, result.script.scenes[1].root
    assert cat.word_count(s1.voiceover) <= cat.HOOK_MAX_WORDS and s1.voiceover.startswith("x0 ")
    assert cat.word_count(s1.on_screen_text or "") <= cat.ON_SCREEN_MAX_WORDS
    assert len(s1.key_point or "") <= cat.KEY_POINT_MAX and s1.icon in cat.ICONS
    assert cat.word_count(s2.voiceover) <= cat.DEMO_VOICEOVER_MAX_WORDS
    kinds = [w.split(" ")[1] for w in result.warnings if w.startswith("auto_trimmed")]
    assert {"scene", "badge"} >= set(kinds[:1]) or kinds  # one note per cut


def test_a_missing_key_point_is_filled_and_a_short_voiceover_only_warns(tmp_path: Path) -> None:
    draft = good_output(badge="x" * 30)["script"]  # forces the final stage
    draft["scenes"][2].update(key_point=None, voiceover="Ngắn quá.")
    caller, _ = caller_for({**good_output(), "script": draft}, tmp_path=tmp_path)
    result = write_script(caller, ctx_for())
    assert result.script.scenes[2].root.key_point
    assert any(w.startswith("auto_filled: scene 3 key_point") for w in result.warnings)


def test_structure_errors_still_fail_with_a_clear_reason(tmp_path: Path) -> None:
    bad = good_output()
    bad["script"]["scenes"][1]["feature"] = "no_such_feature"
    caller, _ = caller_for(bad, tmp_path=tmp_path)
    with pytest.raises(WriterError) as e:
        write_script(caller, ctx_for())
    assert any("không có trong product" in x for x in e.value.errors)


def test_the_draft_type_is_still_a_draft_script() -> None:
    assert DraftScript.model_validate(good_output()["script"]).scenes
