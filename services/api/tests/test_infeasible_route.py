"""The flow route when a flow cannot be done on the account. (Its own module: the route opens its
own browser, which cannot live next to the shared one of the module-scoped fixture.)"""

import json
from pathlib import Path
from typing import Any

import pytest

from app.flows.discovery import PageSummary
from app.llm.json_call import JsonCaller
from app.pipeline.flow_run import FALLBACK_FILE, INFEASIBLE_FILE, FlowJob, run_core_flow
from app.pipeline.frontend import ScriptedFrontend
from app.pipeline.proposal_run import ProposalRunner
from tests.conftest import FakeLLM
from tests.test_explorer import profile
from tests.test_flow_agent import FILL, make_caller, step
from tests.test_select_flow import flow_dict

MESSAGE = "No Leave Types with Leave Balance"


# --- the route: give up, ask again, go on with another flow --------------------------------------


@pytest.fixture
def pages(site: str) -> list[PageSummary]:
    return [
        PageSummary(url=site + "/empty_state.html", title="Apply Leave", purpose="Xin nghỉ"),
        PageSummary(url=site + "/flow_apply.html", title="Apply Leave form", purpose="Form"),
        PageSummary(url=site + "/flow_home.html", title="Dashboard", purpose="Tổng quan"),
    ]


def route(
    tmp_path: Path, site: str, plan: list[dict[str, Any]], titles: list[tuple[str, str]]
) -> tuple[FlowJob, ProposalRunner, FakeLLM, list[Any], JsonCaller]:
    """titles: (title, page) of the flows discovery offers every time (the card hides the failed)."""
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    offered = [
        flow_dict(f"f{i}", title=t, start_url=site + page, persona="Nhân viên", goal=f"g{i}")
        for i, (t, page) in enumerate(titles)
    ]
    discovery = FakeLLM(lambda _p: {"flows": offered})
    seen: list[Any] = []

    class Spy(ScriptedFrontend):
        def ask(self, request: Any) -> Any:
            seen.append(request)
            return super().ask(request)

    proposal = ProposalRunner(
        "j", job_dir, JsonCaller(discovery, cache_dir=tmp_path / "c"), Spy({}),
        explore_more=lambda _u, _d: profile([]),
    )  # fmt: skip
    agent, _ = make_caller(tmp_path / "a", plan)
    home = site + "/flow_home.html"
    job = FlowJob(job_dir, home, home, None, None, lambda _e: None)
    return job, proposal, discovery, seen, agent


def test_a_flow_the_account_cannot_do_is_given_up_marked_and_the_next_one_is_filmed(
    site: str, pages: list[PageSummary], tmp_path: Path
) -> None:
    plan = [
        step("give_up", reason="no form", reason_kind="no_data", quote=MESSAGE),
        *FILL, step("stop_before_submit", "Apply"),
    ]  # fmt: skip
    titles = [
        ("Nhân viên xin nghỉ phép", "/empty_state.html"),
        ("Điền form nghỉ phép", "/flow_apply.html"),
    ]
    job, proposal, discovery, seen, agent = route(tmp_path, site, plan, titles)
    result = run_core_flow(job, proposal, proposal.caller, profile([]), pages, agent_caller=agent)
    assert result is not None and result.run.status == "stopped_before_submit"
    assert result.run.flow_id == "f1" and result.outline.title == "Điền form nghỉ phép"
    saved = json.loads((job.job_dir / INFEASIBLE_FILE).read_text("utf-8"))
    assert [(i["flow"]["id"], i["why"]) for i in saved] == [("f0", MESSAGE)]
    cards = [r for r in seen if r.kind == "select_flow"]
    assert len(cards) == 2 and cards[0].flow_select.infeasible == {}
    assert cards[1].flow_select.infeasible == {"f0": MESSAGE} and cards[1].flow_select.default == [
        "f1"
    ]
    assert "không khả thi trên tài khoản này" in cards[1].message
    assert len(discovery.calls) == 2 and "<infeasible>" in discovery.calls[1]["prompt"]
    assert any("không khả thi" in w for w in proposal.warnings)
    assert not (job.job_dir / FALLBACK_FILE).exists()


def test_it_switches_flow_at_most_twice_then_takes_the_old_route(
    site: str, pages: list[PageSummary], tmp_path: Path
) -> None:
    plan = [step("give_up", reason="no form", reason_kind="no_data", quote=MESSAGE)]  # always
    titles = [(f"Luồng {n}", "/empty_state.html") for n in ("một", "hai", "ba")]
    job, proposal, discovery, seen, agent = route(tmp_path, site, plan, titles)
    result = run_core_flow(job, proposal, proposal.caller, profile([]), pages, agent_caller=agent)
    assert result is None and (job.job_dir / FALLBACK_FILE).is_file()
    saved = json.loads((job.job_dir / INFEASIBLE_FILE).read_text("utf-8"))
    assert len(saved) == 3 and any("Không có luồng nào khả thi" in w for w in proposal.warnings)


def test_a_flow_that_gave_up_for_another_reason_still_shows_its_storyboard(
    site: str, pages: list[PageSummary], tmp_path: Path
) -> None:
    plan = [step("give_up", reason="không hiểu trang", reason_kind="stuck"), *FILL[:2]]
    job, proposal, discovery, seen, agent = route(
        tmp_path, site, plan, [("Luồng một", "/flow_apply.html")]
    )
    run_core_flow(job, proposal, proposal.caller, profile([]), pages, agent_caller=agent)
    assert not (job.job_dir / INFEASIBLE_FILE).exists()
    assert [r.kind for r in seen].count("select_flow") == 1
