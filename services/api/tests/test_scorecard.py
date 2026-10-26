from typing import Any

from app.producer.scorecard import build_scorecard, hook_is_close, proof_from_dict
from app.script.proof import NumberFact, Offer, ProofBank

PROOF = ProofBank(
    numbers=[NumberFact("80", "%", "giảm 80%", "profile")],
    offers=[Offer("free", "miễn phí", "Free")],
)


def critic(hook: int = 8, benefit: int = 8, cta: int = 8) -> dict[str, Any]:
    def one(n: int | None) -> dict[str, Any]:
        return {"score": n, "reason": ""}

    scores = {"hook_strength": one(hook), "benefit_clarity": one(benefit), "proof_usage": one(8),
              "cta_strength": one(cta), "flow": one(8)}  # fmt: skip
    return {"final": {"scores": scores}, "before": {"scores": scores}}


GOOD_REPORT: dict[str, Any] = {
    "max_static_shot_s": 2.7,
    "dead_frames_ms": 0,
    "text_cards": {"count": 0, "longest_ms": 0, "ratio": 0.0, "ok": True},
    "footage_ratio": 0.82,
    "flow": {"steps_in_clip": 1.0},
}


def card(report: dict[str, Any] | None = None, **kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "hook_text": "Nghỉ phép 1 phút", "hook_close": True,
        "said": "Giảm 80% thời gian xin nghỉ phép", "proof": PROOF, "critic": critic(),
    }  # fmt: skip
    return build_scorecard(report or GOOD_REPORT, **{**args, **kw})


def status(sc: dict[str, Any]) -> dict[str, str]:
    return {x["id"]: x["status"] for x in sc["lines"]}


def test_a_video_that_keeps_every_promise_passes_everything_that_is_counted() -> None:
    sc = card()
    assert sc["all_passed"] and sc["failed"] == 0 and sc["passed"] == sc["total"] == 10
    got = status(sc)
    assert got["audio_present"] == "info"  # shown, never counted
    assert next(x for x in sc["lines"] if x["id"] == "audio_present")["value"] == "chưa có (M2)"


def test_each_promise_can_fail_on_its_own() -> None:
    assert status(card(hook_close=False))["hook_visual"] == "fail"
    assert status(card(hook_text="một hai ba bốn năm sáu"))["hook_visual"] == "fail"  # 6 words
    assert status(card(hook_text=None))["hook_visual"] == "fail"  # no punch line at all
    assert status(card({**GOOD_REPORT, "max_static_shot_s": 3.4}))["max_static_shot_s"] == "fail"
    assert status(card({**GOOD_REPORT, "dead_frames_ms": 300}))["dead_frames_ms"] == "fail"
    cards = {"count": 1, "longest_ms": 3500, "ratio": 0.1, "ok": False}
    assert status(card({**GOOD_REPORT, "text_cards": cards}))["fullscreen_text_ratio"] == "fail"
    assert status(card({**GOOD_REPORT, "footage_ratio": 0.5}))["footage_ratio"] == "fail"
    assert status(card({**GOOD_REPORT, "flow": {"steps_in_clip": 0.6}}))["steps_in_clip"] == "fail"
    low = status(card(critic=critic(hook=6, benefit=5, cta=7)))
    assert (
        low["critic_hook_strength"],
        low["critic_benefit_clarity"],
        low["critic_cta_strength"],
    ) == ("fail", "fail", "pass")
    assert status(card(said="Xin nghỉ phép nhanh hơn"))["proof_used"] == "fail"


def test_what_cannot_be_judged_is_na_and_does_not_count() -> None:
    sc = card({"footage_ratio": 0.7}, hook_close=None, proof=ProofBank(), critic=None)
    got = status(sc)
    for key in (
        "hook_visual",
        "max_static_shot_s",
        "dead_frames_ms",
        "fullscreen_text_ratio",
        "proof_used",
        "critic",
        "steps_in_clip",
    ):
        assert got[key] == "na", key
    assert sc["total"] == 1 and sc["passed"] == 1  # only the footage ratio
    assert not card({"x": 1}, hook_close=None, proof=None, critic=None)[
        "all_passed"
    ]  # nothing judged: not "all passed"


def test_the_hook_is_close_when_every_early_entry_is_tight_or_medium() -> None:
    track = [
        {"t_ms": 500, "framing": "medium"},
        {"t_ms": 1800, "framing": "tight"},
        {"t_ms": 4000, "framing": "wide"},
    ]
    assert hook_is_close(track, 500, 1.0) is True  # the wide one starts at 3.5 s
    assert hook_is_close([{"t_ms": 500, "framing": "establish"}, *track[1:]], 500, 1.0) is False
    assert hook_is_close([*track[:1], {"t_ms": 1800, "framing": "wide"}], 500, 1.0) is False
    assert hook_is_close([], 0, 1.0) is None


def test_the_proof_bank_survives_the_trip_through_the_report() -> None:
    again = proof_from_dict(PROOF.to_dict())
    assert again == PROOF and proof_from_dict(None).is_empty
