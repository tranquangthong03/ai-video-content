from pathlib import Path
from typing import Any

import pytest

from app.browser.session import BrowserSession
from app.flows.agent import FlowAgent
from app.llm.client import LLMSettings
from app.llm.router import get_client, role_config
from app.schemas.generated.flow_run import FlowRun
from tests.conftest import FakeLLM
from tests.test_flow_agent import FILL, flow_for, make_caller, step

pytestmark = pytest.mark.slow


def settings(vision: str | None = "deepseek-flash") -> LLMSettings:
    return LLMSettings(
        base_url="http://x", api_key="k", model="deepseek-chat", vision_model=vision,
        cache_enabled=False, cache_dir=Path("."),
    )  # fmt: skip


def test_the_flow_agent_starts_at_auto_and_other_roles_keep_their_images() -> None:
    assert role_config("flow_agent", settings(), {}).vision_mode == "auto"
    assert (
        role_config("flow_agent", settings(), {"LLM_FLOW_AGENT_VISION": "true"}).vision_mode == "on"
    )
    assert (
        role_config("flow_agent", settings(), {"LLM_FLOW_AGENT_VISION": "false"}).vision_mode
        == "off"
    )
    assert (
        role_config("flow_agent", settings(), {"LLM_FLOW_AGENT_VISION": "AUTO"}).vision_mode
        == "auto"
    )
    assert role_config("script", settings(), {}).vision_mode == "on"
    assert role_config("flow_agent", settings(vision=None), {}).vision_mode == "off"
    caller = get_client(
        "flow_agent",
        settings=settings(),
        env={},
        providers={"deepseek": lambda s: FakeLLM(lambda _p: {}, s.vision_model)},
    )
    assert caller.vision_mode == "auto" and caller.can_see_images


def run_auto(
    session: BrowserSession, site: str, tmp_path: Path, plan: list[dict[str, Any]],
    page: str = "/flow_apply.html", mode: str = "auto", vision: str | None = "v",
) -> tuple[FlowRun, FakeLLM]:  # fmt: skip
    caller, llm = make_caller(tmp_path, plan, vision)
    caller.vision_mode = mode
    flow = flow_for(site, start_url=site + page)
    return FlowAgent(session, caller, flow, tmp_path / "job").run(), llm


def test_an_easy_flow_is_done_without_a_single_screenshot(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    run, llm = run_auto(
        browser_session, site, tmp_path, [*FILL, step("stop_before_submit", "Apply")]
    )
    assert run.status == "stopped_before_submit" and not any(c["images"] for c in llm.calls)
    r = run.report
    assert r and (r.text_calls, r.vision_calls, r.escalated_because) == (6, 0, None)
    assert not r.used_images and r.model == "fake-text"


def test_a_repeat_warning_makes_the_next_questions_carry_the_screenshot(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    run, llm = run_auto(browser_session, site, tmp_path, [step("click", "Leave Type")])
    flags = [c["images"] for c in llm.calls]
    assert flags[:2] == [False, False] and flags[2] is True  # the 2nd repeat shows in the 3rd ask
    r = run.report
    assert r and r.escalated_because == "cảnh báo lặp" and r.vision_calls >= 1 and r.text_calls == 2
    assert r.model == "fake-text + v"  # a text model and a vision model were both used


def test_two_refused_actions_escalate(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    plan = [step("click", "!invented"), step("check", "!invented"), step("finish")]  # not a repeat
    run, llm = run_auto(browser_session, site, tmp_path, plan)
    assert [c["images"] for c in llm.calls] == [False, False, True]
    assert run.report and "2 hành động bị từ chối" in (run.report.escalated_because or "")


def test_a_big_canvas_means_screenshots_from_the_first_question(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    run, llm = run_auto(browser_session, site, tmp_path, [step("finish")], page="/canvas.html")
    assert llm.calls[0]["images"] is True
    assert run.report and run.report.escalated_because == "trang có canvas/svg lớn"


def test_a_drawn_dropdown_with_no_readable_option_escalates(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    plan = [step("select", "Quality", value="High"), step("finish")]
    run, llm = run_auto(browser_session, site, tmp_path, plan, page="/drawn_select.html")
    assert [c["images"] for c in llm.calls] == [False, True]
    assert run.report and run.report.escalated_because == "control tự vẽ không đọc được option"


def test_true_always_false_never_and_no_vision_model_means_none(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    _, on = run_auto(browser_session, site, tmp_path / "a", [step("finish")], mode="on")
    assert all(c["images"] for c in on.calls)
    _, off = run_auto(
        browser_session, site, tmp_path / "b", [step("finish")], page="/canvas.html", mode="off"
    )
    assert not any(c["images"] for c in off.calls)
    run, none = run_auto(
        browser_session, site, tmp_path / "c", [step("finish")], page="/canvas.html", vision=None
    )
    assert (
        not any(c["images"] for c in none.calls)
        and run.report
        and run.report.escalated_because is None
    )
