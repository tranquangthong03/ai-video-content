from pathlib import Path
from typing import Any

from app.llm.json_call import JsonCaller
from app.script import narrative as nar
from app.script.apply import apply_ops
from app.script.proof import NumberFact, Offer, ProofBank
from app.script.writer import DraftScript, build_prompt, check_draft, write_script
from tests.conftest import FakeLLM
from tests.test_flow_script import draft as flow_draft
from tests.test_flow_script import writer_ctx
from tests.test_script_edit import op
from tests.test_script_writer import caller_for


class Opt:
    def __init__(self, kind: str, voiceover: str, on_screen_text: str | None = None) -> None:
        self.kind, self.voiceover, self.on_screen_text = kind, voiceover, on_screen_text


# --- pure checks ------------------------------------------------------------------------------


def test_empty_phrases_are_found_without_regard_to_accents_or_case() -> None:
    assert nar.forbidden_in("Một GIẢI PHÁP TOÀN DIỆN cho bạn") == ["giải pháp toàn diện"]
    assert nar.forbidden_in("Nâng tầm và hoàn hảo") == ["nâng tầm", "hoàn hảo"]
    assert nar.forbidden_in("Xin nghỉ trong một phút") == []


def test_a_hook_is_short_and_does_not_open_with_the_product_name() -> None:
    ok = "Xin nghỉ phép mà mất cả buổi sáng?"
    assert nar.hook_line_issues("h", ok, "Nghỉ phép?", "OrangeHRM") == []
    long = " ".join(["từ"] * 13)
    assert any("13 từ" in e for e in nar.hook_line_issues("h", long, None, "X"))
    assert any(
        "tên sản phẩm" in e
        for e in nar.hook_line_issues("h", "OrangeHRM giúp bạn nghỉ phép", None, "OrangeHRM")
    )
    assert any(
        "quá 5 từ" in e for e in nar.hook_line_issues("h", ok, "một hai ba bốn năm sáu", "X")
    )


def test_two_hooks_of_different_kinds_and_a_number_hook_only_with_a_real_number() -> None:
    a = Opt("pain_question", "Xin nghỉ phép mà mất cả buổi sáng?")
    b = Opt("result_first", "Đơn nghỉ phép xong trong một phút")
    assert nar.hook_option_issues([a, b], "X", has_numbers=False, required=True) == []
    assert any(
        "đúng 2" in e for e in nar.hook_option_issues([a], "X", has_numbers=False, required=True)
    )
    assert nar.hook_option_issues([a], "X", has_numbers=False, required=False) == []
    same = nar.hook_option_issues(
        [a, Opt("pain_question", "Vẫn mất cả buổi sáng để xin nghỉ?")],
        "X",
        has_numbers=False,
        required=True,
    )
    assert any("khác kiểu" in e for e in same)
    shock = Opt("shocking_number", "Giảm hẳn một nửa dung lượng ảnh")
    assert any(
        "shocking_number" in e
        for e in nar.hook_option_issues([a, shock], "X", has_numbers=True, required=True)
    )
    shock = Opt("shocking_number", "Giảm 80% dung lượng ảnh của bạn")
    assert nar.hook_option_issues([a, shock], "X", has_numbers=True, required=True) == []
    assert any(
        "shocking_number" in e
        for e in nar.hook_option_issues([a, shock], "X", has_numbers=False, required=True)
    )


def test_a_cta_that_reads_out_a_url_is_found() -> None:
    assert nar.reads_a_url("Vào https://hr.example.com/signup/free ngay") and nar.reads_a_url(
        "www.x.com"
    )
    assert not nar.reads_a_url("Thử miễn phí tại hr.example.com")


# --- the writer in flow mode ------------------------------------------------------------------

PROOF = ProofBank(
    numbers=[NumberFact("80", "%", "giảm 80%", "profile")],
    offers=[Offer("free", "miễn phí", "Free")],
)


def output(**patch_scene: Any) -> dict[str, Any]:
    script = flow_draft().model_dump()
    for i, text in patch_scene.items():
        script["scenes"][int(i[1:]) - 1]["voiceover"] = text
    return {"script": script, "summary": [], "warnings": []}


def test_the_script_carries_framework_hook_options_and_the_hook_scene_shows_the_first(
    tmp_path: Path,
) -> None:
    ctx = writer_ctx()
    caller, _ = caller_for(output(), tmp_path=tmp_path)
    result = write_script(caller, ctx)
    script = result.script
    assert script.framework == "pain_journey_result"
    assert [o.kind for o in script.hook_options] == ["pain_question", "result_first"]
    hook = script.scenes[0].root
    assert hook.voiceover == script.hook_options[0].voiceover
    assert hook.on_screen_text == script.hook_options[0].on_screen_text


def test_a_hook_option_is_required_in_flow_mode_and_the_draft_is_checked(tmp_path: Path) -> None:
    ctx = writer_ctx()
    bad = DraftScript.model_validate({**flow_draft().model_dump(), "hook_options": []})
    assert any("hook_options" in e for e in check_draft(bad, ctx))
    worse = flow_draft().model_copy(deep=True)
    worse.scenes[1].voiceover = "Một giải pháp toàn diện cho việc xin nghỉ phép của bạn mỗi ngày"
    assert any("giải pháp toàn diện" in e for e in check_draft(worse, ctx))


def test_an_unsourced_number_is_sent_back_once_then_the_code_removes_it(tmp_path: Path) -> None:
    ctx = writer_ctx()
    ctx.proof = PROOF
    with_number = "Tiết kiệm 95% thời gian xin nghỉ phép mỗi ngày cho bạn nhé"
    caller, llm = caller_for(output(s2=with_number), output(s2=with_number), tmp_path=tmp_path)
    result = write_script(caller, ctx)
    assert "95%" in llm.calls[1]["prompt"] and "không có trong proof_bank" in llm.calls[1]["prompt"]
    said = result.script.scenes[1].root.voiceover
    assert "95" not in said and "Tiết kiệm" in said
    assert any(w.startswith("auto_stripped: scene 2 voiceover") for w in result.warnings)


def test_a_number_that_the_proof_bank_has_is_kept_without_any_repair(tmp_path: Path) -> None:
    ctx = writer_ctx()
    ctx.proof = PROOF
    sourced = "Giảm 80% thời gian xin nghỉ phép mỗi ngày cho bạn nhé thật nhanh"
    caller, llm = caller_for(output(s2=sourced), tmp_path=tmp_path)
    result = write_script(caller, ctx)
    assert "80%" in result.script.scenes[1].root.voiceover
    assert not any("không có trong proof_bank" in c["prompt"] for c in llm.calls)
    assert not any(w.startswith("auto_stripped") for w in result.warnings)


def test_choosing_a_hook_option_is_a_plain_edit_without_the_model(tmp_path: Path) -> None:
    ctx = writer_ctx()
    caller, _ = caller_for(output(), tmp_path=tmp_path)
    script = write_script(caller, ctx).script
    res = apply_ops(script, [op(op="set", scene_id="s1", field="hook_option", value="2")], ctx)
    assert res.errors == [] and res.llm_tasks == []
    second = script.hook_options[1]
    assert res.script.scenes[0].root.voiceover == second.voiceover
    assert res.script.hook_options == script.hook_options  # both stay available
    by_kind = apply_ops(
        res.script, [op(op="set", scene_id="s1", field="hook_option", value="pain_question")], ctx
    )
    assert by_kind.script.scenes[0].root.voiceover == script.hook_options[0].voiceover
    assert apply_ops(
        script, [op(op="set", scene_id="s1", field="hook_option", value="3")], ctx
    ).errors
    assert apply_ops(
        script, [op(op="set", scene_id="s2", field="hook_option", value="1")], ctx
    ).errors


def test_the_prompt_has_the_marketing_rules_the_proof_and_the_framework() -> None:
    ctx = writer_ctx()
    ctx.proof = PROOF
    prompt = build_prompt(ctx)
    assert "<proof_bank>" in prompt and "miễn phí" in prompt
    assert "<framework>pain_journey_result</framework>" in prompt
    assert (
        "hook_options" in prompt and "giải pháp toàn diện" in prompt and "hr.example.com" in prompt
    )
    ctx.proof = None
    assert "<proof_bank>" not in build_prompt(ctx)


def test_a_hook_option_that_stays_too_long_is_cut_by_code_not_failed(tmp_path: Path) -> None:
    ctx = writer_ctx()
    out = output()
    long = "Xin nghỉ phép mà vẫn mất cả buổi sáng chờ duyệt rồi còn phải hỏi lại nhiều lần nữa"
    out["script"]["hook_options"][1]["voiceover"] = long
    out["script"]["hook_options"][1]["on_screen_text"] = "một hai ba bốn năm sáu bảy"
    caller, _ = caller_for(out, tmp_path=tmp_path)
    result = write_script(caller, ctx)  # (three attempts keep the long line: the code trims it)
    second = result.script.hook_options[1]
    assert len(second.voiceover.split()) <= 12 and len((second.on_screen_text or "").split()) <= 5
    assert any(w.startswith("auto_trimmed: hook_options[2] voiceover") for w in result.warnings)


def test_a_hook_over_the_limit_is_rewritten_once_by_the_model_before_the_code_cuts_it(
    tmp_path: Path,
) -> None:
    ctx = writer_ctx()
    out = output()
    long = "Bạn mất bao lâu để dựng sơ đồ nghiệp vụ rồi gửi đồng nghiệp xem thử ngay hôm nay"
    out["script"]["hook_options"][0]["voiceover"] = long
    out["script"]["scenes"][0]["voiceover"] = long
    short = "Dựng sơ đồ nghiệp vụ mất bao lâu?"

    def handler(prompt: str) -> dict[str, Any]:
        if prompt.startswith(
            "Bạn là biên kịch short video marketing (TikTok/Reels/Shorts). Viết lại"
        ):
            return {"text": short}
        return out

    llm = FakeLLM(handler)
    caller = JsonCaller(llm, cache_dir=tmp_path)
    result = write_script(caller, ctx)
    assert result.script.hook_options[0].voiceover == short
    assert result.script.scenes[0].root.voiceover == short  # the scene shows the first option
    assert any(w.startswith("auto_rewritten: hook") for w in result.warnings)
    assert sum(1 for c in llm.calls if "Viết lại câu mở đầu" in c["prompt"]) >= 1


def test_when_the_rewrite_is_still_too_long_the_cut_takes_over_without_a_dangling_end(
    tmp_path: Path,
) -> None:
    ctx = writer_ctx()
    out = output()
    long = "Bạn mất bao lâu để dựng sơ đồ nghiệp vụ rồi gửi cho đồng nghiệp xem thử ngay hôm nay"
    out["script"]["hook_options"][0]["voiceover"] = long
    out["script"]["scenes"][0]["voiceover"] = long

    def handler(prompt: str) -> dict[str, Any]:
        if "Viết lại câu mở đầu" in prompt:
            return {"text": long}  # the model did not shorten it
        return out

    result = write_script(JsonCaller(FakeLLM(handler), cache_dir=tmp_path), ctx)
    hook = result.script.hook_options[0].voiceover
    assert len(hook.rstrip(".").split()) <= 12
    assert hook.rstrip(".").split()[-1] not in {"cho", "rồi", "để", "và", "một"}
