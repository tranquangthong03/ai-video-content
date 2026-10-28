"""The marketing brief: cleaning, the proof bank, the prompts, the avoid list and the asking step."""

from pathlib import Path
from typing import Any

import pytest

from app.core import brief as bf
from app.llm.json_call import JsonCaller
from app.pipeline.frontend import ScriptedFrontend
from app.pipeline.proposal_run import ProposalRunner
from app.schemas.generated.marketing_brief import MarketingBrief
from app.script.critic import prompt_for
from app.script.proof import ProofBank, build_proof_bank, supported_values
from app.script.writer import build_prompt, check_scene
from tests.conftest import FakeLLM
from tests.test_critic import made_script
from tests.test_flow_script import writer_ctx

BRIEF = MarketingBrief.model_validate(
    {
        "audience": "  Phòng nhân sự   doanh nghiệp nhỏ ",
        "main_benefit": "Tạo hồ sơ trong vài phút",
        "secondary_benefits": ["Không giấy tờ", "không giấy tờ", ""],
        "proof_points": [
            {"value": "40%", "claim": "Giảm 40% thời gian nhập hồ sơ"},
            {"value": "abc", "claim": "không có số"},
            {"value": "3", "unit": "phút", "claim": ""},
            {
                "value": "2.8",
                "unit": "MB",
                "claim": "Ảnh gốc nặng 2.8MB",
                "source_note": "đo nội bộ",
            },
        ],
        "offer": "Mã nguồn mở, dùng miễn phí",
        "cta_text": "Dùng thử ngay",
        "cta_url": "https://www.hr.example.com/start",
        "tone": "gần gũi",
        "avoid": ["rẻ nhất", "Rẻ Nhất"],
    }
)


def test_cleaning_splits_a_number_from_its_unit_and_drops_what_cannot_be_used() -> None:
    clean = bf.clean_brief(BRIEF)
    assert clean.audience == "Phòng nhân sự doanh nghiệp nhỏ"
    assert clean.secondary_benefits == ["Không giấy tờ", "không giấy tờ"]  # (empty dropped)
    assert [(p.value, p.unit) for p in clean.proof_points] == [("40", "%"), ("2.8", "MB")]
    assert clean.avoid == ["rẻ nhất", "Rẻ Nhất"]


def test_an_empty_brief_is_a_skip_and_a_resumed_job_does_not_ask_again(tmp_path: Path) -> None:
    assert bf.is_empty(None) and bf.is_empty(MarketingBrief()) and not bf.is_empty(BRIEF)
    assert not bf.asked(tmp_path)
    bf.save_brief(tmp_path, MarketingBrief())
    assert bf.asked(tmp_path) and bf.load_brief(tmp_path) is None
    bf.save_brief(tmp_path, bf.clean_brief(BRIEF))
    assert bf.load_brief(tmp_path).main_benefit == "Tạo hồ sơ trong vài phút"  # type: ignore[union-attr]


def test_the_cta_address_is_the_short_domain() -> None:
    assert bf.cta_domain(BRIEF) == "hr.example.com"
    assert bf.cta_domain(MarketingBrief(cta_url="shop.test/x")) == "shop.test"
    assert bf.cta_domain(MarketingBrief()) is None and bf.cta_domain(None) is None


def test_the_users_numbers_come_first_in_the_proof_bank_with_source_user() -> None:
    bank = build_proof_bank(None, brief=bf.clean_brief(BRIEF))
    first = bank.numbers[0]
    assert (first.value, first.unit, first.source, first.kind) == ("40", "%", "user", "benefit")
    assert "40" in supported_values(bank, benefit_only=True)
    assert bank.offers[0].id == "user" and bank.offers[0].label == "Mã nguồn mở, dùng miễn phí"
    assert "Giảm 40% thời gian nhập hồ sơ" in bank.quotes
    assert build_proof_bank(None).numbers == []  # no brief: nothing changes


def test_the_prompts_carry_the_brief_only_when_there_is_one(tmp_path: Path) -> None:
    ctx = writer_ctx()
    script = made_script(tmp_path, ctx)
    assert "<marketing_brief>" not in build_prompt(ctx)
    assert "<marketing_brief>" not in prompt_for(ctx, script)
    ctx.brief = bf.clean_brief(BRIEF)
    prompt = build_prompt(ctx)
    assert "<marketing_brief>" in prompt and "Giảm 40% thời gian" in prompt
    assert "Cấm các cụm sáo rỗng:" in prompt and "rẻ nhất" in prompt.split("Cấm các cụm")[1]
    critic = prompt_for(ctx, script)
    assert "<marketing_brief>" in critic and "Có brief: chấm" in critic


def test_a_phrase_the_user_asked_to_avoid_is_an_error_in_every_scene() -> None:
    ctx = writer_ctx()
    ctx.brief = bf.clean_brief(BRIEF)
    from tests.test_flow_script import draft as flow_draft

    scene = flow_draft().scenes[1]
    scene = scene.model_copy(
        update={"voiceover": "Đây là cách rẻ nhất để nhập hồ sơ nhanh hơn nhé"}
    )
    errors = check_scene(scene, "scene 2", ctx.features, avoid=ctx.avoid)
    assert any("rẻ nhất" in e for e in errors)
    assert not any("rẻ nhất" in e for e in check_scene(scene, "scene 2", ctx.features))


def proposal(tmp_path: Path, answers: dict[str, Any], llm: FakeLLM) -> ProposalRunner:
    caller = JsonCaller(llm, cache_dir=tmp_path / "cache")
    return ProposalRunner(
        "job",
        tmp_path,
        caller,
        ScriptedFrontend(answers),
        explore_more=lambda *_: None,  # type: ignore[arg-type,return-value]
    )


SUGGEST = {
    "audience": ["a1", "a2", "a3"],
    "main_benefit": ["b1", "b2", "b3"],
    "offer": ["o1", "o2", "o3"],
}


def test_asking_skips_silently_in_auto_mode_and_costs_no_llm_call(tmp_path: Path) -> None:
    llm = FakeLLM(lambda _p: SUGGEST)
    runner = proposal(tmp_path, {}, llm)
    assert runner.marketing_brief(writer_ctx().profile, None) is None
    assert llm.calls == [] and bf.asked(tmp_path)
    assert runner.marketing_brief(writer_ctx().profile, None) is None  # asked once


def test_a_brief_given_with_the_job_is_used_without_asking(tmp_path: Path) -> None:
    llm = FakeLLM(lambda _p: SUGGEST)
    got = proposal(tmp_path, {}, llm).marketing_brief(writer_ctx().profile, None, BRIEF)
    assert got is not None and got.proof_points[0].value == "40" and llm.calls == []
    assert bf.load_brief(tmp_path) == got


def test_the_card_has_three_ideas_per_field_and_the_answer_is_cleaned_and_saved(
    tmp_path: Path,
) -> None:
    llm = FakeLLM(lambda _p: SUGGEST)
    answer = {"action": "answer", "brief": BRIEF.model_dump()}
    runner = proposal(tmp_path, {"marketing_brief": [answer]}, llm)
    got = runner.marketing_brief(writer_ctx().profile, None)
    assert got is not None and got.audience == "Phòng nhân sự doanh nghiệp nhỏ"
    assert len(llm.calls) == 1 and "json" in llm.calls[0]["prompt"].lower()
    asked = (tmp_path / "interactions.jsonl").read_text(encoding="utf-8")
    assert '"marketing_brief"' in asked and "a1" in asked and "Chỉ nhập số liệu có thật" in asked


def test_skip_keeps_the_old_behaviour(tmp_path: Path) -> None:
    llm = FakeLLM(lambda _p: SUGGEST)
    runner = proposal(tmp_path, {"marketing_brief": [{"action": "skip"}]}, llm)
    assert runner.marketing_brief(writer_ctx().profile, None) is None
    assert bf.load_brief(tmp_path) is None and bf.asked(tmp_path)


def test_the_ideas_fall_back_to_generic_ones_when_the_model_fails(tmp_path: Path) -> None:
    from app.proposal.brief_suggest import suggest

    caller = JsonCaller(FakeLLM(lambda _p: "not json"), cache_dir=tmp_path / "cache")
    got, warning = suggest(caller, writer_ctx().profile)
    assert warning and got.offer  # generic offers, the card still opens


@pytest.mark.parametrize("kind", ["tool", "web_app", "landing"])
def test_generic_offers_exist_for_every_kind_of_site(kind: str) -> None:
    from app.proposal.brief_suggest import DEFAULT_OFFERS, GENERIC_OFFERS

    assert GENERIC_OFFERS.get(kind, DEFAULT_OFFERS)
    assert ProofBank().is_empty


# --- the card is built from the approved run: chapters live on FlowRun, not on CoreFlow ---------


def test_the_brief_card_reads_chapters_from_the_approved_run_not_from_the_flow(
    tmp_path: Path,
) -> None:
    from app.schemas.generated.core_flow import CoreFlow
    from tests.test_flow_storyboard import make_run
    from tests.test_select_flow import flow_dict

    flow = CoreFlow.model_validate(flow_dict("f1", title="Xin nghỉ phép"))
    run = make_run(chapters=[{"id": "c1", "title": "Mở form", "step_ids": [1, 2]}])
    llm = FakeLLM(lambda _p: SUGGEST)
    runner = proposal(tmp_path, {"marketing_brief": [{"action": "skip"}]}, llm)
    runner.marketing_brief(writer_ctx().profile, flow, None, run)
    assert "Mở form" in llm.calls[0]["prompt"] and "Xin nghỉ phép" in llm.calls[0]["prompt"]
    assert not hasattr(flow, "chapters")  # the mistake this test guards against


def test_the_flow_route_hands_the_approved_run_to_the_brief_step(
    site: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("playwright")
    from app.pipeline.proposal_run import ProposalRunner as PR

    seen: list[object] = []
    real = PR.marketing_brief

    def spy(self: PR, profile, flow, given=None, run=None):  # type: ignore[no-untyped-def]
        seen.append(run)
        return real(self, profile, flow, given, run)

    monkeypatch.setattr(PR, "marketing_brief", spy)
    from app.flows.discovery import PageSummary
    from app.pipeline.flow_run import run_core_flow
    from tests.test_explorer import profile as mk_profile
    from tests.test_flow_agent import FILL, step
    from tests.test_infeasible_route import route

    pages = [PageSummary(url=site + "/flow_apply.html", title="Apply", purpose="Form")]
    plan = [*FILL, step("stop_before_submit", "Apply")]
    job, runner, _d, _s, agent = route(tmp_path, site, plan, [("Điền form", "/flow_apply.html")])
    result = run_core_flow(job, runner, runner.caller, mk_profile([]), pages, agent_caller=agent)
    assert result is not None and seen and seen[0] is not None
    assert seen[0].chapters  # type: ignore[attr-defined]


def test_mypy_finds_no_flow_attribute_mistakes() -> None:
    """CoreFlow (the choice) has no chapters/steps; FlowRun (what the agent did) has them."""
    import subprocess
    import sys

    api = Path(__file__).resolve().parents[1]
    out = subprocess.run(
        [sys.executable, "-m", "mypy", "app/flows", "app/proposal", "app/pipeline", "app/script"],
        cwd=api, capture_output=True, text=True, timeout=900,
    )  # fmt: skip
    bad = [ln for ln in out.stdout.splitlines() if "CoreFlow" in ln or "FlowRun" in ln]
    assert not bad, "\n".join(bad)
