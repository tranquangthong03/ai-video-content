import json
from pathlib import Path
from typing import Any

from app.core.flow_choice import (
    SUBMIT_NEEDS_CONFIRMATION,
    FlowAnswer,
    build_request,
    check_flow_answer,
    read_answer,
    resolve_submit_policy,
)
from app.core.interaction import check_response, make_response
from app.core.shared_demo import SHARED_DEMO_REASON
from app.flows.discovery import PageSummary
from app.llm.json_call import JsonCaller
from app.pipeline.frontend import ScriptedFrontend
from app.pipeline.proposal_run import ProposalRunner
from app.schemas.generated.core_flow import CoreFlow
from tests.conftest import FakeLLM
from tests.test_explorer import profile

ROOT = "https://hr.example.com/dashboard"
OWN_ROOT = "https://todo.example.com/"
PAGES = [
    PageSummary(url=ROOT, title="Dashboard", purpose="Tổng quan"),
    PageSummary(url="https://hr.example.com/leave", title="Leave", purpose="Nghỉ phép"),
]


def flow_dict(fid: str, **kw: Any) -> dict[str, Any]:
    base = {
        "id": fid, "title": f"Luồng {fid}", "persona": "Nhân viên", "goal": "g", "start_url": ROOT,
        "expected_steps": ["a", "b", "c"], "success_signal": "s", "needs_submit": True,
        "value": "v", "confidence": 0.8,
    }  # fmt: skip
    return {**base, **kw}


def flows(*ids: str) -> list[CoreFlow]:
    return [CoreFlow.model_validate(flow_dict(i)) for i in ids]


def runner(
    tmp_path: Path, answers: dict[str, list[dict[str, Any]]], handler: Any = None
) -> ProposalRunner:
    llm = FakeLLM(handler or (lambda _p: {"flows": [flow_dict("a"), flow_dict("b")]}))
    return ProposalRunner(
        "j", tmp_path, JsonCaller(llm, cache_dir=tmp_path / "c"), ScriptedFrontend(answers),
        explore_more=lambda _u, _d: profile([]),
    )  # fmt: skip


def answer(**answers: Any) -> dict[str, Any]:
    return {"action": "answer", "answers": answers}


def test_the_request_lists_the_flows_and_preselects_the_first() -> None:
    req = build_request("j", flows("a", "b"), OWN_ROOT)
    assert req.kind == "select_flow" and [f.id for f in req.flows or []] == ["a", "b"]
    assert req.flow_select and req.flow_select.default == ["a"] and req.flow_select.max == 2
    assert req.flow_select.submit_blocked_reason is None
    assert set(req.allowed_actions) == {"answer", "cancel"}


def test_a_shared_demo_site_carries_the_reason_in_the_request() -> None:
    req = build_request("j", flows("a"), "https://opensource-demo.orangehrmlive.com/web/index.php")
    assert req.flow_select and req.flow_select.submit_blocked_reason == SHARED_DEMO_REASON


def test_answers_are_checked_against_the_request() -> None:
    req = build_request("j", flows("a", "b", "c"), OWN_ROOT)

    def errors(**a: Any) -> list[str]:
        return check_response(req, make_response(req, "answer", answers=a))

    assert errors(selected_flows=["a"]) == []
    assert errors(selected_flows=["a", "b"]) == []
    assert errors(flow_description="xin nghỉ") == []  # a description alone is fine
    assert any("at least" in e for e in errors(selected_flows=[]))
    assert any("does not exist" in e for e in errors(selected_flows=["zzz"]))
    assert any("at most" in e for e in errors(selected_flows=["a", "b", "c"]))
    assert any("twice" in e for e in errors(selected_flows=["a", "a"]))
    assert (
        check_flow_answer(req, make_response(req, "answer", answers={"selected_flows": "a"})) == []
    )


def test_submit_is_off_unless_asked_confirmed_needed_and_the_site_is_not_shared() -> None:
    fs = flows("a")
    want = FlowAnswer(["a"], "", wants_submit=True, confirmed=True)
    assert resolve_submit_policy(OWN_ROOT, fs, want) == ("allow", None)
    assert resolve_submit_policy(OWN_ROOT, fs, FlowAnswer(["a"], "", False, False)) == (
        "stop",
        None,
    )
    assert resolve_submit_policy(OWN_ROOT, fs, FlowAnswer(["a"], "", True, False)) == (
        "stop", SUBMIT_NEEDS_CONFIRMATION,
    )  # fmt: skip
    shared = "https://opensource-demo.orangehrmlive.com/"
    assert resolve_submit_policy(shared, fs, want) == ("stop", SHARED_DEMO_REASON)
    no_submit = [CoreFlow.model_validate(flow_dict("a", needs_submit=False))]
    assert resolve_submit_policy(OWN_ROOT, no_submit, want) == ("stop", None)


def test_read_answer_accepts_a_single_string_and_ignores_other_values() -> None:
    r = make_response(
        build_request("j", flows("a"), OWN_ROOT), "answer",
        answers={"selected_flows": "a", "allow_submit": "yes", "flow_description": "  hi "},
    )  # fmt: skip
    a = read_answer(r)
    assert a.selected == ["a"] and a.description == "hi" and not a.wants_submit


def test_the_selection_keeps_the_users_order_and_is_saved_for_resume(tmp_path: Path) -> None:
    r = runner(tmp_path, {"select_flow": [answer(selected_flows=["b", "a"])]})
    sel = r.select_flow(profile([]), PAGES, OWN_ROOT)
    assert sel and [f.id for f in sel.flows] == ["b", "a"] and sel.submit_policy == "stop"
    assert json.loads((tmp_path / "selected_flow.json").read_text("utf-8"))["flows"][0]["id"] == "b"
    again = runner(tmp_path, {"select_flow": [{"action": "cancel"}]})
    resumed = again.select_flow(profile([]), PAGES, OWN_ROOT)
    assert resumed and [f.id for f in resumed.flows] == ["b", "a"]  # no question asked


def test_auto_mode_takes_the_first_flow(tmp_path: Path) -> None:
    sel = runner(tmp_path, {}).select_flow(profile([]), PAGES, OWN_ROOT)
    assert sel and [f.id for f in sel.flows] == ["a"]


def test_a_described_flow_is_added_preselected_then_the_card_is_asked_again(tmp_path: Path) -> None:
    def handler(prompt: str) -> dict[str, Any]:
        if "<mode>normalize</mode>" in prompt:
            return {"flows": [flow_dict("x", title="Xin nghỉ phép 2 ngày")]}
        return {"flows": [flow_dict("a"), flow_dict("b")]}

    answers = {
        "select_flow": [
            answer(selected_flows=["b"], flow_description="Nhân viên xin nghỉ phép 2 ngày"),
            answer(selected_flows=["user_xin_ngh_ph_p_2_ng_y", "b"]),
        ]
    }
    r = runner(tmp_path, answers, handler)
    asked: list[Any] = []
    real_ask = r.frontend.ask
    r.frontend.ask = lambda req: (asked.append(req), real_ask(req))[1]  # type: ignore[method-assign]
    sel = r.select_flow(profile([]), PAGES, OWN_ROOT)
    assert sel and [f.source for f in sel.flows] == ["user", "proposed"]
    assert len(asked) == 2 and asked[1].flow_select.default[0].startswith("user_")
    assert asked[1].flows[-1].source == "user" and "Đã thêm luồng" in asked[1].message


def test_submit_policy_is_refused_for_a_shared_demo_even_when_ticked(tmp_path: Path) -> None:
    root = "https://opensource-demo.orangehrmlive.com/web/index.php/dashboard"
    handler = lambda _p: {"flows": [flow_dict("a", start_url=root)]}  # noqa: E731
    pages = [PageSummary(url=root, title="Dashboard", purpose="p")]
    answers = {
        "select_flow": [answer(selected_flows=["a"], allow_submit="true", submit_confirmed="true")]
    }
    sel = runner(tmp_path, answers, handler).select_flow(profile([]), pages, root)
    assert sel and sel.submit_policy == "stop" and sel.warnings == [SHARED_DEMO_REASON]


def test_ticking_without_the_confirmation_keeps_submit_off(tmp_path: Path) -> None:
    answers = {"select_flow": [answer(selected_flows=["a"], allow_submit="true")]}
    sel = runner(tmp_path, answers).select_flow(profile([]), PAGES, OWN_ROOT)
    assert sel and sel.submit_policy == "stop" and sel.warnings == [SUBMIT_NEEDS_CONFIRMATION]


def test_a_confirmed_submit_on_an_own_site_is_allowed(tmp_path: Path) -> None:
    answers = {
        "select_flow": [answer(selected_flows=["a"], allow_submit="true", submit_confirmed="true")]
    }
    sel = runner(tmp_path, answers).select_flow(profile([]), PAGES, OWN_ROOT)
    assert sel and sel.submit_policy == "allow"


def test_when_discovery_fails_the_caller_falls_back(tmp_path: Path) -> None:
    r = runner(tmp_path, {}, lambda _p: {"flows": "not a list"})
    assert r.select_flow(profile([]), PAGES, OWN_ROOT) is None
    assert any("chuyển sang chọn tính năng" in w for w in r.warnings)
    assert not (tmp_path / "selected_flow.json").exists()


class _Ask:
    def __init__(self, value: object) -> None:
        self.value = value

    def ask(self) -> object:
        return self.value


class FakeQ:
    """questionary stand-in: checkbox picks, a description, then the two submit confirmations."""

    class Choice:
        def __init__(self, title: str, value: str, checked: bool = False) -> None:
            self.title, self.value, self.checked = title, value, checked

    def __init__(self, picks: list[str], description: str, confirms: list[bool]) -> None:
        self.picks, self.description, self.confirms = picks, description, confirms
        self.defaults: list[str] = []

    def checkbox(self, _m: str, choices: list[Any]) -> _Ask:
        self.defaults = [c.value for c in choices if c.checked]
        return _Ask(self.picks)

    def text(self, _m: str) -> _Ask:
        return _Ask(self.description)

    def confirm(self, _m: str, default: bool = False) -> _Ask:
        return _Ask(self.confirms.pop(0))


def test_terminal_card_preselects_asks_description_and_two_confirmations() -> None:
    from app.pipeline.frontend import TerminalFrontend

    req = build_request("j", flows("a", "b"), OWN_ROOT)
    fake = FakeQ(["b"], "xin nghỉ", [True, True])
    resp = TerminalFrontend()._ask_flow(req, fake)
    assert fake.defaults == ["a"]
    assert resp.answers == {
        "selected_flows": ["b"], "flow_description": "xin nghỉ",
        "allow_submit": "true", "submit_confirmed": "true",
    }  # fmt: skip
    declined = TerminalFrontend()._ask_flow(req, FakeQ(["a"], "", [False]))
    assert declined.answers == {"selected_flows": ["a"]}  # submit stays off by default
    shared = build_request("j", flows("a"), "https://opensource-demo.orangehrmlive.com/")
    blocked = TerminalFrontend()._ask_flow(shared, FakeQ(["a"], "", []))  # never asked to confirm
    assert blocked.answers == {"selected_flows": ["a"]}
