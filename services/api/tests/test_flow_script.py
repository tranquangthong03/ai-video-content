import json
from pathlib import Path
from typing import Any

import pytest

from app.core.flow_ctx import FlowCtx
from app.flows.discovery import PageSummary
from app.llm.json_call import JsonCaller
from app.pipeline.flow_run import FALLBACK_FILE, FlowJob, nav_by_url, run_core_flow
from app.pipeline.frontend import ScriptedFrontend
from app.pipeline.proposal_run import ProposalRunner
from app.proposal.flow_outline import (
    build_flow_ctx,
    estimate_duration_s,
    flow_profile,
    outline_from_flow,
)
from app.schemas.generated.core_flow import CoreFlow
from app.schemas.generated.theme import Theme
from app.script.writer import (
    DraftScene,
    DraftScript,
    WriterContext,
    build_prompt,
    check_draft,
    write_script,
)
from tests.conftest import FakeLLM
from tests.test_explorer import profile
from tests.test_flow_agent import FILL, make_caller, step
from tests.test_flow_storyboard import make_run
from tests.test_select_flow import flow_dict

THEME = Theme(
    primary="#4F46E5", accent="#F59E0B", font="Be Vietnam Pro", motion_preset="energetic",
    caption_style="minimal", music_mood="upbeat", voice_id="v", language="vi",
)  # fmt: skip
HOME = "https://hr.example.com/dashboard"


def the_flow(**kw: Any) -> CoreFlow:
    return CoreFlow.model_validate(
        flow_dict("leave", start_url=HOME, persona="Nhân viên", goal="Xin nghỉ 2 ngày", **kw)
    )


def the_ctx(status: str = "stopped_before_submit") -> Any:
    run = make_run(status)
    return the_flow(), run, build_flow_ctx(the_flow(), run, HOME)


# --- the outline and the pseudo-features -----------------------------------------------------


def test_the_outline_is_hook_one_beat_per_chapter_and_cta() -> None:
    flow, run, ctx = the_ctx()
    outline = outline_from_flow(flow, run, ctx)
    assert [b.id for b in outline.beats] == ["b1", "b2", "b3", "b4"]
    assert [b.feature_id for b in outline.beats] == [None, "c1", "c2", None]
    assert "kết quả" in outline.beats[2].text and flow.success_signal in outline.beats[2].text
    assert outline.feature_ids == ["c1", "c2"] and outline.concept_id == "flow:leave"
    assert outline.duration_s == 30 and 4 <= len(outline.beats) <= 6


def test_four_chapters_still_fit_the_six_scene_limit_and_long_flows_get_longer_videos() -> None:
    flow, run, _ = the_ctx()
    run.chapters = [run.chapters[0].model_copy(update={"id": f"c{n}"}) for n in range(1, 5)]
    for s in run.steps:
        s.chapter_id = f"c{(s.i - 1) % 4 + 1}"
    ctx = build_flow_ctx(flow, run, HOME)
    assert len(outline_from_flow(flow, run, ctx).beats) == 6
    run.steps = run.steps * 4  # many steps -> a longer video, never beyond 60 s
    assert estimate_duration_s(run) in (45, 60)


def test_the_flow_profile_has_one_demoable_feature_per_chapter() -> None:
    _, _, ctx = the_ctx()
    p = flow_profile(profile([]), ctx)
    assert [(f.id, f.name, f.demo_kind) for f in p.features] == [
        ("c1", "Mở form", "interaction"), ("c2", "Điền thông tin", "interaction"),
    ]  # fmt: skip


def test_each_chapter_visual_is_a_recording_of_its_own_steps_and_the_ends_are_plain() -> None:
    _, _, ctx = the_ctx()
    v1, v2 = ctx.visuals["c1"], ctx.visuals["c2"]
    assert v1["mode"] == "recording" and [a["do"] for a in v1["actions"]] == ["goto", "navigate"]
    assert [a["do"] for a in v2["actions"]] == ["select", "pick_date", "type", "hover", "highlight"]
    assert all("locator" in a for a in v2["actions"])
    assert ctx.hook_visual["actions"] == [{"do": "goto", "url": HOME}]
    assert ctx.cta_visual["page"] == HOME


def test_the_context_round_trips_through_the_job_dir(tmp_path: Path) -> None:
    _, _, ctx = the_ctx()
    ctx.save(tmp_path)
    assert FlowCtx.load(tmp_path) == ctx and FlowCtx.load(tmp_path / "nope") is None
    assert "visuals" not in json.loads(ctx.prompt_json())  # the model never sees the visuals


# --- the script writer in flow mode ----------------------------------------------------------


def writer_ctx() -> WriterContext:
    flow, run, ctx = the_ctx()
    return WriterContext(
        flow_profile(profile([]), ctx), outline_from_flow(flow, run, ctx), THEME, HOME, flow=ctx
    )


def draft(*, demo_types: tuple[str, str] = ("feature_demo", "feature_demo")) -> DraftScript:
    words = "một hai ba bốn năm sáu bảy tám chín mười"
    base = {"voiceover": words, "key_point": "ý", "icon": "check"}
    return DraftScript(
        title="Xin nghỉ phép", badge="HR", headline="Xin nghỉ trong một phút",
        scenes=[
            DraftScene(type="hook", layout="big_text_over_blur", on_screen_text="Nghỉ phép?", **{**base, "key_point": "k0"}),
            DraftScene(type=demo_types[0], layout="full_screen", feature="c1", **{**base, "key_point": "k1"}),  # type: ignore[arg-type]
            DraftScene(type=demo_types[1], layout="full_screen", feature="c2", **{**base, "key_point": "k2"}),  # type: ignore[arg-type]
            DraftScene(type="cta", layout="button_pulse", on_screen_text="Thử ngay", **{**base, "key_point": "k3"}),
        ],
    )  # fmt: skip


def test_the_prompt_carries_the_flow_and_the_benefit_rule_only_in_flow_mode() -> None:
    prompt = build_prompt(writer_ctx())
    assert "<flow>" in prompt and '"persona": "Nhân viên"' in prompt
    assert "KHÔNG kể lại từng thao tác" in prompt and "không dùng before_after" in prompt
    assert "demo_steps của feature" not in prompt  # the old "describe what is on screen" rule
    plain = writer_ctx()
    plain.flow = None
    old = build_prompt(plain)
    assert "<flow>" not in old and "demo_steps của feature" in old


def test_a_chapter_beat_must_be_a_feature_demo_of_that_chapter() -> None:
    ctx = writer_ctx()
    assert check_draft(draft(), ctx) == []
    bad = draft()
    bad.scenes[1].feature = "c2"
    assert any("feature = c1" in e for e in check_draft(bad, ctx))


def test_the_script_gets_the_flow_id_chapter_ids_and_the_chapter_visuals() -> None:
    llm = FakeLLM(lambda _p: {"script": draft().model_dump(), "summary": [], "warnings": []})
    result = write_script(JsonCaller(llm), writer_ctx())
    script = result.script
    assert script.flow_id == "leave"
    scenes = [s.root for s in script.scenes]
    assert [getattr(s, "chapter_id", None) for s in scenes] == [None, "c1", "c2", None]
    demo = scenes[2]
    assert [a.do for a in demo.visual.actions] == [
        "select",
        "pick_date",
        "type",
        "hover",
        "highlight",
    ]
    assert scenes[0].visual.page == HOME
    assert not any("không có" in w for w in result.warnings)


# --- the whole flow route --------------------------------------------------------------------


@pytest.fixture
def job(tmp_path: Path, site: str) -> FlowJob:
    return FlowJob(
        tmp_path / "job",
        site + "/flow_home.html",
        site + "/flow_home.html",
        None,
        None,
        lambda _e: None,
    )


def proposal_for(job: FlowJob, site: str) -> ProposalRunner:
    job.job_dir.mkdir(parents=True, exist_ok=True)
    found = flow_dict(
        "leave", start_url=site + "/flow_apply.html", title="Xin nghỉ phép", persona="Nhân viên",
        goal="Xin nghỉ 2 ngày", success_signal="Form đã điền",
    )  # fmt: skip
    llm = FakeLLM(lambda _p: {"flows": [found]})
    return ProposalRunner(
        "j", job.job_dir, JsonCaller(llm, cache_dir=job.job_dir / "c"), ScriptedFrontend({}),
        explore_more=lambda _u, _d: profile([]),
    )  # fmt: skip


def pages_for(site: str) -> list[PageSummary]:
    return [
        PageSummary(url=site + "/flow_home.html", title="Dashboard", purpose="Tổng quan"),
        PageSummary(url=site + "/flow_apply.html", title="Apply Leave", purpose="Xin nghỉ"),
    ]


def test_the_route_runs_the_agent_reviews_and_writes_the_outline(job: FlowJob, site: str) -> None:
    proposal = proposal_for(job, site)
    agent, llm = make_caller(job.job_dir.parent / "a", [*FILL, step("stop_before_submit", "Apply")])
    result = run_core_flow(
        job, proposal, proposal.caller, profile([]), pages_for(site), agent_caller=agent
    )
    assert result is not None and result.run.status == "stopped_before_submit"
    assert [f.demo_kind for f in result.profile.features] == ["interaction"] * len(
        result.ctx.chapters
    )
    assert result.outline.beats[0].id == "b1" and result.outline.beats[-1].feature_id is None
    assert FlowCtx.load(job.job_dir) == result.ctx
    saved = json.loads((job.job_dir / "outline_approved.json").read_text("utf-8"))
    assert saved["concept_id"] == "flow:leave"
    assert (job.job_dir / "flow" / "flow_approved.json").is_file() and llm.calls


def test_when_the_agent_fails_the_old_route_is_taken_and_not_asked_again(
    job: FlowJob, site: str
) -> None:
    proposal = proposal_for(job, site)
    agent, _ = make_caller(job.job_dir.parent / "a", [step("give_up", reason="không thấy form")])
    flow_fail = run_core_flow(
        job, proposal, proposal.caller, profile([]), pages_for(site), agent_caller=agent
    )
    # one step (the opening page) is not a flow: partial with fewer than two steps falls back
    assert flow_fail is None
    assert (job.job_dir / FALLBACK_FILE).is_file()
    assert any("chuyển sang quay từng tính năng" in w for w in proposal.warnings)
    again = run_core_flow(job, proposal, proposal.caller, profile([]), pages_for(site))
    assert again is None  # no agent, no questions


def test_a_second_flow_is_reported_as_not_built(job: FlowJob, site: str) -> None:
    proposal = proposal_for(job, site)
    other = flow_dict("other", start_url=site + "/flow_apply.html", title="Xem đơn")
    mine = flow_dict("leave", start_url=site + "/flow_apply.html", title="Xin nghỉ")
    proposal.flow_caller = JsonCaller(
        FakeLLM(lambda _p: {"flows": [mine, other]}), cache_dir=job.job_dir / "c2"
    )
    proposal.frontend = ScriptedFrontend(
        {"select_flow": [{"action": "answer", "answers": {"selected_flows": ["leave", "other"]}}]}
    )
    agent, _ = make_caller(job.job_dir.parent / "a", [*FILL, step("stop_before_submit", "Apply")])
    result = run_core_flow(
        job, proposal, proposal.caller, profile([]), pages_for(site), agent_caller=agent
    )
    assert result is not None
    assert any("Luồng phụ" in w and "Xem đơn" in w for w in proposal.warnings)


def test_nav_entries_come_from_the_pages_menu_links() -> None:
    class El:
        def __init__(self, name: str, region: str, role: str = "link") -> None:
            self.name, self.region, self.role = name, region, role

    class Pg:
        url = "u"
        elements = [
            El("Leave", "nav"),
            El("Leave", "nav"),
            El("Buy", "main"),
            El("Home", "header"),
            El("Go", "nav", "button"),
        ]

    assert nav_by_url([Pg()]) == {"u": ["Leave", "Home"]}
