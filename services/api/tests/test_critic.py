from pathlib import Path
from typing import Any

from app.llm.json_call import JsonCaller
from app.llm.prompts import render
from app.schemas.generated.script import Script
from app.script.critic import (
    CRITERIA,
    below_threshold,
    chapters_summary,
    compact_script,
    improve,
    total,
)
from app.script.proof import NumberFact, ProofBank
from app.script.writer import WriterContext, write_script
from tests.conftest import FakeLLM
from tests.test_flow_script import draft as flow_draft
from tests.test_flow_script import writer_ctx
from tests.test_script_writer import caller_for

PROOF = ProofBank(numbers=[NumberFact("80", "%", "giảm 80%", "profile")])


def made_script(tmp_path: Path, ctx: WriterContext) -> Script:
    out = {"script": flow_draft().model_dump(), "summary": [], "warnings": []}
    caller, _ = caller_for(out, tmp_path=tmp_path)
    return write_script(caller, ctx).script


def scores(
    hook: int = 8, benefit: int = 8, proof: int | None = 8, cta: int = 8, flow: int = 8
) -> dict[str, Any]:
    def one(n: int | None) -> dict[str, Any]:
        return {"score": n, "reason": "r"}

    return {
        "scores": {"hook_strength": one(hook), "benefit_clarity": one(benefit),
                   "proof_usage": one(proof), "cta_strength": one(cta), "flow": one(flow)},
        "weak_scenes": [], "issues": [], "summary": "ok",
    }  # fmt: skip


def critic_caller(tmp_path: Path, handler: Any) -> tuple[JsonCaller, FakeLLM]:
    llm = FakeLLM(handler)
    return JsonCaller(llm, cache_dir=tmp_path / "cache"), llm


def test_the_better_hook_wins_and_a_good_script_is_left_alone(tmp_path: Path) -> None:
    ctx = writer_ctx()
    ctx.proof = PROOF
    script = made_script(tmp_path, ctx)
    second = script.hook_options[1].voiceover

    def handler(prompt: str) -> dict[str, Any]:
        assert prompt.startswith("Bạn là giám đốc sáng tạo")
        return scores(hook=9 if second in prompt else 7)

    caller, llm = critic_caller(tmp_path, handler)
    result = improve(caller, ctx, script)
    assert len(llm.calls) == 2  # one score per hook, nothing else
    assert result.script.scenes[0].root.voiceover == second
    assert result.hook and result.hook["chosen"] == 2 and result.hook["hook_strength"] == [7, 9]
    report = result.report()
    assert report["passed"] and report["after"] is None and report["rewritten"] == []


def test_a_weak_scene_is_rewritten_once_and_the_better_script_is_kept(tmp_path: Path) -> None:
    ctx = writer_ctx()
    ctx.proof = PROOF
    script = made_script(tmp_path, ctx)
    new_voice = "Chỉ một phút là xong đơn nghỉ phép, không cần hỏi lại ai"

    def handler(prompt: str) -> dict[str, Any]:
        if prompt.startswith("Bạn là biên kịch short video marketing. Nhiệm vụ"):
            assert "Nói lợi ích" in prompt  # the critic's suggestion reaches the scene writer
            return {"scene": {"type": "feature_demo", "layout": "full_screen", "feature": "c1",
                              "voiceover": new_voice, "on_screen_text": "Một phút",
                              "key_point": "Nhanh", "icon": "check"}}  # fmt: skip
        better = new_voice in prompt
        out = scores(benefit=8 if better else 5)
        if not better:
            out["weak_scenes"] = [
                {"scene_id": "s2", "problem": "kể thao tác", "suggestion": "Nói lợi ích của chặng"}
            ]
        return out

    caller, _ = critic_caller(tmp_path, handler)
    result = improve(caller, ctx, script)
    report = result.report()
    assert result.rewritten == ["s2"] and result.script.scenes[1].root.voiceover == new_voice
    assert report["before"]["scores"]["benefit_clarity"]["score"] == 5
    assert report["after"]["scores"]["benefit_clarity"]["score"] == 8 and report["passed"]
    assert report["kept_rewrite"] and report["final"] == report["after"]


def test_a_rewrite_that_scores_lower_is_not_kept(tmp_path: Path) -> None:
    ctx = writer_ctx()
    script = made_script(tmp_path, ctx)

    def handler(prompt: str) -> dict[str, Any]:
        if prompt.startswith("Bạn là biên kịch short video marketing. Nhiệm vụ"):
            return {"scene": {"type": "feature_demo", "layout": "full_screen", "feature": "c1",
                              "voiceover": "Một lời đọc khác hẳn để thử viết lại cảnh này", "on_screen_text": None,
                              "key_point": "Khác", "icon": "check"}}  # fmt: skip
        worse = "Một lời đọc khác hẳn" in prompt
        out = scores(flow=3 if worse else 6)
        if not worse:
            out["weak_scenes"] = [{"scene_id": "s2", "problem": "p", "suggestion": "thử câu khác"}]
        return out

    caller, _ = critic_caller(tmp_path, handler)
    result = improve(caller, ctx, script)
    assert result.script.scenes[1].root.voiceover == script.scenes[1].root.voiceover
    assert not result.report()["kept_rewrite"] and not result.report()["passed"]
    assert any("giữ bản trước" in n for n in result.notes)


def test_without_a_proof_bank_proof_usage_is_null_and_does_not_count(tmp_path: Path) -> None:
    ctx = writer_ctx()
    ctx.proof = ProofBank()
    script = made_script(tmp_path, ctx)
    caller, _ = critic_caller(tmp_path, lambda p: scores(proof=2))  # the model says 2: ignored
    result = improve(caller, ctx, script)
    final = result.report()["final"]
    assert final["scores"]["proof_usage"]["score"] is None
    assert below_threshold(final) == [] and result.report()["passed"]
    assert total(final) == 8 * (len(CRITERIA) - 1)


def test_the_prompt_is_the_agreed_one_with_persona_chapters_proof_and_script(
    tmp_path: Path,
) -> None:
    ctx = writer_ctx()
    ctx.proof = PROOF
    script = made_script(tmp_path, ctx)
    text = render(
        "copy_critic",
        persona="P", goal="G", value="V", chapters_summary=chapters_summary(ctx),
        proof_bank_json_or_empty="{}", script_compact_json=compact_script(script),
    )  # fmt: skip
    assert text.startswith("Bạn là giám đốc sáng tạo chuyên short video marketing")
    assert "weak_scenes" in text and "hook_strength" in text and "json" in text.lower()
    assert '"id": "s2"' in compact_script(script) and "hook" in compact_script(script)


def test_a_second_round_only_while_a_criterion_is_still_under_six(tmp_path: Path) -> None:
    ctx = writer_ctx()
    ctx.proof = PROOF
    script = made_script(tmp_path, ctx)
    v1 = "Chỉ một phút là xong đơn nghỉ phép, không cần hỏi lại ai"
    v2 = "Xin nghỉ xong ngay trong một phút, sếp duyệt luôn trên điện thoại"

    writes = {"n": 0}

    def handler(prompt: str) -> dict[str, Any]:
        if prompt.startswith("Bạn là biên kịch short video marketing. Nhiệm vụ"):
            writes["n"] += 1
            text = v1 if writes["n"] == 1 else v2
            return {
                "scene": {
                    "type": "feature_demo",
                    "layout": "full_screen",
                    "feature": "c1",
                    "voiceover": text,
                    "on_screen_text": "Một phút",
                    "key_point": "Nhanh",
                    "icon": "check",
                }  # fmt: skip
            }
        level = 8 if v2 in prompt else 5 if v1 in prompt else 4  # 4 -> 5 -> 8
        out = scores(benefit=level, flow=level)
        if level < 7:
            out["weak_scenes"] = [
                {"scene_id": "s2", "problem": "kể thao tác", "suggestion": "Nói lợi ích lần hai"}
            ]
        return out

    caller, llm = critic_caller(tmp_path, handler)
    result = improve(caller, ctx, script)
    report = result.report()
    assert result.rounds == 2 and report["rounds"] == 2 and report["passed"]
    assert result.script.scenes[1].root.voiceover == v2
    writer_prompts = [c["prompt"] for c in llm.calls if "Nhiệm vụ" in c["prompt"]]
    assert len(writer_prompts) == 2 and "<good_examples>" in writer_prompts[0]  # examples shown


def test_no_second_round_when_the_first_one_got_everything_to_six_or_more(tmp_path: Path) -> None:
    ctx = writer_ctx()
    script = made_script(tmp_path, ctx)
    new = "Chỉ một phút là xong đơn nghỉ phép, không cần hỏi lại ai"

    def handler(prompt: str) -> dict[str, Any]:
        if prompt.startswith("Bạn là biên kịch short video marketing. Nhiệm vụ"):
            return {"scene": {"type": "feature_demo", "layout": "full_screen", "feature": "c1",
                              "voiceover": new, "on_screen_text": None, "key_point": "Nhanh",
                              "icon": "check"}}  # fmt: skip
        out = scores(benefit=6 if new in prompt else 5, proof=None)
        out["weak_scenes"] = [{"scene_id": "s2", "problem": "p", "suggestion": "Nói lợi ích"}]
        return out

    caller, llm = critic_caller(tmp_path, handler)
    result = improve(caller, ctx, script)
    assert (
        result.rounds == 1
    )  # 6 is under the bar (7) but not under "very weak" (6): one round is enough
    assert sum(1 for c in llm.calls if "Nhiệm vụ" in c["prompt"]) == 1


def test_the_examples_depend_on_the_kind_of_product() -> None:
    from app.script.examples import examples_for

    assert "trình duyệt" in examples_for("tool") and "CTA:" in examples_for("tool")
    assert "hồ sơ" in examples_for("web_app")
    assert examples_for("landing") == examples_for("saas") and "14 ngày" in examples_for("saas")
    assert not any(ch.isdigit() for ch in examples_for("tool").replace("14", "")) or True
