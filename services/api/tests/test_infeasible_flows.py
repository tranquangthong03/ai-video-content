import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.browser.session import BrowserSession
from app.core.flow_choice import build_request, check_flow_answer
from app.core.interaction import make_response
from app.flows.actions import FlowAction
from app.flows.agent import FlowAgent, _Step, give_up_has_evidence, tried_to_reach
from app.flows.discovery import propose_flows, same_flow
from app.llm.json_call import JsonCaller
from app.pipeline.frontend import TerminalFrontend
from app.schemas.generated.core_flow import CoreFlow
from tests.conftest import FakeLLM
from tests.test_explorer import profile
from tests.test_flow_agent import flow_for, make_caller, step
from tests.test_flow_discovery import PAGES as DISCOVERY_PAGES
from tests.test_flow_discovery import flow as discovery_flow
from tests.test_select_flow import flow_dict

MESSAGE = "No Leave Types with Leave Balance"


# --- the action ---------------------------------------------------------------------------------


def test_give_up_says_why_and_defaults_to_stuck() -> None:
    assert FlowAction(do="give_up", reason="x").reason_kind == "stuck"
    a = FlowAction(do="give_up", reason="x", reason_kind="no_data", quote=MESSAGE)
    assert (a.reason_kind, a.quote) == ("no_data", MESSAGE)
    with pytest.raises(ValidationError):
        FlowAction(do="give_up", reason_kind="whatever")  # type: ignore[arg-type]


def agent_run(
    session: BrowserSession, site: str, tmp_path: Path, quote: str | None, times: int = 1
) -> Any:
    plan = [
        step("give_up", reason="trang không có form", reason_kind="no_data", quote=quote)
        for _ in range(times)
    ]
    caller, _ = make_caller(tmp_path, plan)
    flow = flow_for(site, start_url=site + "/empty_state.html")
    return FlowAgent(session, caller, flow, tmp_path / "job").run()


def test_the_site_message_is_kept_only_when_it_is_really_on_the_page(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    run = agent_run(browser_session, site, tmp_path / "a", MESSAGE)
    assert run.status == "partial" and run.give_up is not None
    assert (run.give_up.reason_kind, run.give_up.quote) == ("no_data", MESSAGE)
    made_up = agent_run(
        browser_session, site, tmp_path / "b", "Please contact your administrator", times=3
    )
    # no real message and no try through the menu: refused twice, then kept as plain "stuck"
    assert made_up.give_up is not None and made_up.give_up.quote is None
    assert made_up.give_up.reason_kind == "stuck"


# --- the card and discovery ---------------------------------------------------------------------


def flows(*ids: str) -> list[CoreFlow]:
    return [CoreFlow.model_validate(flow_dict(i, title=f"Luồng {i}")) for i in ids]


def test_a_flow_that_cannot_be_done_is_marked_never_preselected_never_accepted() -> None:
    req = build_request("j", flows("a", "b"), "https://x.test/", infeasible={"a": MESSAGE})
    assert req.flow_select and req.flow_select.default == ["b"]
    assert req.flow_select.infeasible == {"a": MESSAGE}
    bad = make_response(req, "answer", answers={"selected_flows": ["a"]})
    assert any(MESSAGE in e for e in check_flow_answer(req, bad))
    good = make_response(req, "answer", answers={"selected_flows": ["b"]})
    assert check_flow_answer(req, good) == []
    only = build_request("j", flows("a"), "https://x.test/", infeasible={"a": MESSAGE})
    assert only.flow_select and only.flow_select.default == []


def test_same_flow_ignores_accents_case_and_a_word_or_two() -> None:
    assert same_flow("Nhân viên xin nghỉ phép", "nhan vien xin nghi phep")
    assert same_flow("Xin nghỉ phép 2 ngày cho nhân viên", "Xin nghỉ phép 2 ngày cho nhân viên mới")
    assert not same_flow("Xin nghỉ phép", "Thêm nhân viên mới")


def test_discovery_asked_again_does_not_offer_the_flow_back(tmp_path: Path) -> None:
    again = discovery_flow(id="x", title="Nhân viên xin nghỉ phép")
    other = discovery_flow(id="y", title="Thêm nhân viên mới")
    llm = FakeLLM(lambda _p: {"flows": [again, other]})
    caller = JsonCaller(llm, cache_dir=tmp_path)
    avoid = [("nhan vien xin nghi phep", MESSAGE)]
    found = propose_flows(caller, profile([]), DISCOVERY_PAGES, avoid)
    assert [f.id for f in found] == ["y"]
    prompt = llm.calls[0]["prompt"]
    assert "<infeasible>" in prompt and MESSAGE in prompt and "KHÔNG đề xuất lại" in prompt
    assert "form tạo mới không cần dữ liệu có sẵn" in prompt


def test_the_terminal_card_disables_a_flow_that_cannot_be_done() -> None:
    class Ask:
        def __init__(self, v: object) -> None:
            self.v = v

        def ask(self) -> object:
            return self.v

    class Q:
        class Choice:
            def __init__(
                self, title: str, value: str, checked: bool = False, disabled: str | None = None
            ) -> None:
                self.value, self.disabled = value, disabled

        def checkbox(self, _m: str, choices: list[Any]) -> Ask:
            self.choices = choices
            return Ask(["b"])

        def text(self, _m: str) -> Ask:
            return Ask("")

        def confirm(self, _m: str, default: bool = False) -> Ask:
            return Ask(False)

    req = build_request("j", flows("a", "b"), "https://x.test/", infeasible={"a": MESSAGE})
    q = Q()
    TerminalFrontend()._ask_flow(req, q)
    assert [(c.value, bool(c.disabled)) for c in q.choices] == [("a", True), ("b", False)]


# --- P0-b: a flow is only "infeasible" with evidence (saved OrangeHRM data) -------------------------

SAVED = json.loads((Path(__file__).parent / "fixtures" / "orangehrm_flows.json").read_text("utf-8"))


def saved_step(do: str, text: str = "") -> _Step:
    return _Step({"do": do}, None, text, None, "", "", "", "")


def goto_step() -> _Step:
    return saved_step("goto")


def click_step(text: str) -> _Step:
    return saved_step("click", text)


def test_the_saved_user_flow_and_the_discovery_flow_start_from_the_same_page() -> None:
    user, found = (
        CoreFlow.model_validate(SAVED["user_leave"]),
        CoreFlow.model_validate(SAVED["discovery_leave"]),
    )
    assert user.start_url == found.start_url  # the start page was never the difference
    assert (
        user.expected_steps[0].split("chọn")[-1].strip() in found.expected_steps[0]
    )  # same entry point: Apply Leave


def test_giving_up_on_the_saved_leave_flow_needs_the_message_or_a_try_through_the_menu() -> None:
    user = CoreFlow.model_validate(SAVED["user_leave"])
    only_start = [goto_step()]  # what the agent had done when it declared the form missing
    assert not give_up_has_evidence("no_data", None, user, only_start)
    assert not give_up_has_evidence("feature_missing", None, user, only_start)
    assert give_up_has_evidence("no_data", MESSAGE, user, only_start)  # the site said so
    assert give_up_has_evidence(
        "no_permission", None, user, only_start
    )  # not an account-data claim
    assert give_up_has_evidence("stuck", None, user, only_start)
    tried = [goto_step(), click_step("Apply Leave")]
    assert tried_to_reach(user, tried) and give_up_has_evidence("no_data", None, user, tried)
    assert not tried_to_reach(user, [goto_step(), click_step("Logout")])
