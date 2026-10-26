"""Marketing scorecard: did the finished video keep the promises of the plan (pure function).

Each line is pass / fail / na (nothing to judge) / info (shown, not counted). It is written into
report.json after the render and shown next to the video on the review page.
"""

from typing import Any

from app.script import catalog as cat
from app.script.proof import NumberFact, Offer, ProofBank, proof_used

MAX_STATIC_S = 3.0
MIN_FOOTAGE = 0.6
MIN_STEPS_IN_CLIP = 0.8
MIN_CRITIC = 7
HOOK_LOOK_MS = 2000  # the first two seconds decide whether the viewer stays
CLOSE = ("tight", "medium")


def proof_from_dict(data: dict[str, Any] | None) -> ProofBank:
    """The proof bank as it was saved in script_report.json."""
    if not data:
        return ProofBank()
    return ProofBank(
        numbers=[NumberFact(**n) for n in data.get("numbers", [])],
        quotes=list(data.get("quotes", [])),
        offers=[Offer(**o) for o in data.get("offers", [])],
        audience_pains=list(data.get("audience_pains", [])),
    )


def line(
    key: str, label: str, target: str, value: Any, status: str, note: str = ""
) -> dict[str, Any]:
    return {
        "id": key,
        "label": label,
        "target": target,
        "value": value,
        "status": status,
        "note": note,
    }


def judge(ok: bool | None) -> str:
    return "na" if ok is None else ("pass" if ok else "fail")


def build_scorecard(
    report: dict[str, Any],
    *,
    hook_text: str | None,
    hook_close: bool | None,
    said: str,
    proof: ProofBank | None = None,
    critic: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The lines of the scorecard and how many pass.

    hook_close: the camera is tight/medium on something during the first two seconds (None = no
    footage to judge). said: all voice-over and on-screen texts of the video, for proof_used."""
    lines: list[dict[str, Any]] = []
    words = cat.word_count(hook_text)
    hook_ok = (
        None if hook_close is None else bool(hook_close and 0 < words <= cat.ON_SCREEN_MAX_WORDS)
    )
    lines.append(line(
        "hook_visual", "Hook: khung gần + chữ ngắn trong 2 giây đầu",
        f"khung tight/medium, chữ ≤ {cat.ON_SCREEN_MAX_WORDS} từ",
        f"{'gần' if hook_close else 'xa'}, {words} từ", judge(hook_ok),
    ))  # fmt: skip

    static = report.get("max_static_shot_s")
    lines.append(line(
        "max_static_shot_s", "Không cảnh nào đứng yên quá lâu", f"≤ {MAX_STATIC_S} s", static,
        judge(None if static is None else static <= MAX_STATIC_S),
    ))  # fmt: skip

    dead = report.get("dead_frames_ms")
    lines.append(line(
        "dead_frames_ms", "Không có khung hình chết", "0 ms", dead,
        judge(None if dead is None else dead == 0),
    ))  # fmt: skip

    cards = report.get("text_cards")
    lines.append(line(
        "fullscreen_text_ratio", "Thẻ chữ toàn màn hình", "mỗi thẻ ≤ 3 s, tổng ≤ 15%",
        None if cards is None else f"{round(cards['ratio'] * 100)}%, max {cards['longest_ms']}ms",
        judge(None if cards is None else bool(cards["ok"])),
    ))  # fmt: skip

    final = (critic or {}).get("final") or (critic or {}).get("before")
    if final:
        for key, label in (
            ("hook_strength", "Critic: hook"),
            ("benefit_clarity", "Critic: lợi ích"),
            ("cta_strength", "Critic: kêu gọi"),
        ):
            score = final["scores"][key]["score"]
            lines.append(line(f"critic_{key}", label, f"≥ {MIN_CRITIC}", score,
                              judge(None if score is None else score >= MIN_CRITIC)))  # fmt: skip
    else:
        lines.append(line("critic", "Critic hook / lợi ích / kêu gọi", f"≥ {MIN_CRITIC}", None,
                          "na", "chưa chấm (không phải video theo luồng, hoặc lỗi)"))  # fmt: skip

    if proof is None or proof.is_empty:
        lines.append(
            line("proof_used", "Dùng bằng chứng thật", "có", None, "na", "không có proof bank")
        )
    else:
        used = proof_used(said, proof)
        lines.append(
            line("proof_used", "Dùng bằng chứng thật", "có", "có" if used else "không", judge(used))
        )

    footage = report.get("footage_ratio")
    lines.append(line(
        "footage_ratio", "Tỉ lệ cảnh quay thật", f"≥ {round(MIN_FOOTAGE * 100)}%",
        None if footage is None else f"{round(footage * 100)}%",
        judge(None if footage is None else footage >= MIN_FOOTAGE),
    ))  # fmt: skip

    steps = (report.get("flow") or {}).get("steps_in_clip")
    lines.append(line(
        "steps_in_clip", "Bước thao tác có trong video", f"≥ {round(MIN_STEPS_IN_CLIP * 100)}%",
        None if steps is None else f"{round(steps * 100)}%",
        judge(None if steps is None else steps >= MIN_STEPS_IN_CLIP),
    ))  # fmt: skip

    lines.append(line("audio_present", "Âm thanh", "—", "chưa có (M2)", "info"))

    counted = [x for x in lines if x["status"] in ("pass", "fail")]
    return {
        "lines": lines,
        "passed": sum(1 for x in counted if x["status"] == "pass"),
        "failed": sum(1 for x in counted if x["status"] == "fail"),
        "total": len(counted),
        "all_passed": bool(counted) and all(x["status"] == "pass" for x in counted),
    }


def hook_is_close(track: list[dict[str, Any]], lead_ms: int, rate: float) -> bool | None:
    """True when every focus entry that starts inside the first 2 s of the scene is tight/medium.
    `track` is on the clip axis (entries start at `lead_ms`); None when there is no track."""
    if not track:
        return None
    early = [e for e in track if (e["t_ms"] - lead_ms) / (rate or 1.0) < HOOK_LOOK_MS]
    return bool(early) and all(e["framing"] in CLOSE for e in early)
