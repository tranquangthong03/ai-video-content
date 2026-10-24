from app.media.timing import (
    EstimatedTimer,
    SpeechTimer,
    estimate_captions,
    estimate_speech_ms,
)


def words(n: int) -> str:
    return " ".join(f"từ{i}" for i in range(n))


def test_speech_estimate_is_words_over_2_5_per_second_plus_a_pause() -> None:
    assert estimate_speech_ms(words(10)) == 4000 + 250
    assert estimate_speech_ms(words(25)) == 10000 + 250


def test_speech_estimate_has_a_floor_of_1500_ms() -> None:
    assert estimate_speech_ms("") == 1500 + 250
    assert estimate_speech_ms("một hai") == 1500 + 250  # 0.8 s would be shorter
    assert estimate_speech_ms(words(4)) == 1600 + 250


def test_captions_group_three_to_five_words_and_cover_the_span() -> None:
    caps = estimate_captions(words(13), 1000, 6200)
    sizes = [len(c["words"]) for c in caps]
    assert all(3 <= s <= 5 for s in sizes) and sum(sizes) == 13
    assert caps[0]["start_ms"] == 1000 and caps[-1]["end_ms"] == 6200
    for a, b in zip(caps, caps[1:], strict=False):
        assert a["end_ms"] == b["start_ms"]
    for c in caps:
        assert c["text"] == " ".join(w["text"] for w in c["words"])
        assert (
            c["words"][0]["start_ms"] == c["start_ms"] and c["words"][-1]["end_ms"] == c["end_ms"]
        )


def test_captions_break_at_punctuation_once_a_group_has_three_words() -> None:
    caps = estimate_captions("Bạn hay quên việc, hãy thử ngay hôm nay nhé", 0, 4000)
    # the trailing single word is rebalanced into the previous group so that no group has < 3 words
    assert [c["text"] for c in caps] == ["Bạn hay quên việc,", "hãy thử ngay", "hôm nay nhé"]


def test_a_comma_too_early_does_not_cut_a_group_below_three_words() -> None:
    caps = estimate_captions("Ôi, thật tuyệt vời quá đi mất", 0, 3000)
    assert [c["text"] for c in caps] == ["Ôi, thật tuyệt vời", "quá đi mất"]


def test_word_time_is_proportional_to_length() -> None:
    caps = estimate_captions("a bbbbbbbb c", 0, 1000)
    w = caps[0]["words"]
    assert w[1]["end_ms"] - w[1]["start_ms"] > 4 * (w[0]["end_ms"] - w[0]["start_ms"])
    assert w[-1]["end_ms"] == 1000


def test_short_and_empty_text() -> None:
    assert estimate_captions("", 0, 1000) == []
    caps = estimate_captions("một hai", 100, 900)
    assert len(caps) == 1 and caps[0]["start_ms"] == 100 and caps[0]["end_ms"] == 900


def test_estimated_timer_follows_the_interface_tts_will_use() -> None:
    timer: SpeechTimer = EstimatedTimer()
    timing = timer.timing(words(10))
    assert timing.duration_ms == estimate_speech_ms(words(10))
    assert len(timing.words) == 10
    assert timing.words[0].start_ms == 0
    assert (
        timing.words[-1].end_ms == timing.duration_ms - 250
    )  # the pause comes after the last word
