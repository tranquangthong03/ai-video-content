from pathlib import Path
from typing import Any

from app.browser.session import BrowserSession
from app.flows.agent import FlowAgent
from app.flows.storyboard import build_request, first_unsafe_index, keep_prefix
from app.pipeline.frontend import ScriptedFrontend
from app.pipeline.proposal_run import ProposalRunner
from app.schemas.generated.flow_run import FlowRun
from tests.conftest import FakeLLM
from tests.test_explorer import profile
from tests.test_flow_agent import FILL, flow_for, make_caller, step
from tests.test_select_flow import flow_dict

from app.llm.json_call import JsonCaller  # isort: skip

CHAPTERS = [
    {"id": "c1", "title": "Mở form", "step_ids": [1, 2]},
    {"id": "c2", "title": "Điền thông tin", "step_ids": [3, 4, 5, 6]},
]


def make_run(status: str = "stopped_before_submit", tail: bool = True, **kw: Any) -> FlowRun:
    """goto, click Leave, select Leave Type=Personal, pick_date From, type Comment (+ hover, highlight)."""
    spec = {"role": "button", "name": "x", "css": "button"}
    rows = [
        ("goto", None, None),
        ("navigate", "Leave", None),
        ("select", "Leave Type", "Personal"),
        ("pick_date", "From Date", "2027-03-05"),
        ("type", "Comment", "Family event"),
    ]
    if tail:
        rows += [("hover", "Apply", None), ("highlight", "Apply", None)]
    steps = [
        {
            "i": i,
            "action": {"do": do, "text": value} if value else {"do": do},
            "locator": spec if do != "goto" else None,
            "target_text": name,
            "value": value,
            "note": f"Bước {i}",
            "chapter_id": "c1" if i <= 2 else "c2",
        }
        for i, (do, name, value) in enumerate(rows, start=1)
    ]
    return FlowRun.model_validate(
        {
            "flow_id": "leave", "status": status, "steps": steps, "chapters": CHAPTERS,
            "sample_data": {"loai": "Personal"}, **kw,
        }
    )  # fmt: skip


# --- what to keep ------------------------------------------------------------------------------


def test_a_step_number_keeps_the_steps_before_it() -> None:
    run = make_run()
    assert keep_prefix(run, "bỏ bước 4") == 3
    assert keep_prefix(run, "Sửa Bước 3 và 5") == 2
    assert keep_prefix(run, "bỏ bước 1") == 1  # never less than the opening page
    assert keep_prefix(run, "bỏ bước 99") == 5  # the closing hover/highlight is never repeated


def test_a_named_value_restarts_at_the_first_step_that_has_it() -> None:
    run = make_run()
    assert keep_prefix(run, "chọn loại nghỉ Annual thay vì Personal") == 2  # step 3 has Personal
    assert keep_prefix(run, "đổi nội dung Comment") == 4  # step 5 is the comment
    assert keep_prefix(run, "làm lại hết đi") == 1  # nothing named: start over


def test_adding_a_step_keeps_everything_that_can_be_repeated() -> None:
    run = make_run()
    assert keep_prefix(run, "thêm bước xem My Leave") == 5
    assert keep_prefix(run, "thay Annual bằng Sick và thêm ghi chú") == 1  # "thay": not an append


def test_a_submit_click_and_the_pointing_tail_are_never_repeated() -> None:
    run = make_run(tail=False)
    run.steps[3].action.do = "click"
    run.steps[3].target_text = "Apply"
    assert first_unsafe_index(run) == 3
    assert keep_prefix(run, "thêm bước xem My Leave") == 3
    assert first_unsafe_index(make_run()) == 5


# --- the card and the review loop -----------------------------------------------------------


def test_the_card_shows_status_run_and_version() -> None:
    from app.schemas.generated.core_flow import CoreFlow

    req = build_request("j", CoreFlow.model_validate(flow_dict("leave")), make_run(), version=2)
    assert req.kind == "flow_storyboard_review" and req.script_version == 2
    assert req.flow_review and len(req.flow_review.steps) == 7
    assert "Dừng trước khi gửi" in req.message and set(req.allowed_actions) == {
        "approve", "edit", "regenerate", "cancel",
    }  # fmt: skip
    failed = build_request("j", CoreFlow.model_validate(flow_dict("leave")), make_run("partial"))
    assert "chưa trọn" in failed.message


def reviewer(tmp_path: Path, answers: list[dict[str, Any]]) -> tuple[ProposalRunner, list[tuple]]:
    calls: list[tuple] = []
    runs = iter([make_run("partial", tail=False)] + [make_run()] * 10)

    def run_flow(notes: str, previous: FlowRun | None, keep: int) -> FlowRun:
        calls.append((notes, previous is not None, keep))
        return next(runs)

    r = ProposalRunner(
        "j", tmp_path, JsonCaller(FakeLLM(lambda _p: {}), cache_dir=tmp_path / "c"),
        ScriptedFrontend({"flow_storyboard_review": answers}),
        explore_more=lambda _u, _d: profile([]),
    )  # fmt: skip
    r.run_flow = run_flow  # type: ignore[attr-defined]
    return r, calls


def review(r: ProposalRunner) -> FlowRun:
    from app.schemas.generated.core_flow import CoreFlow

    return r.review_storyboard(CoreFlow.model_validate(flow_dict("leave")), r.run_flow)  # type: ignore[attr-defined]


def test_edit_reruns_with_the_notes_and_the_kept_prefix_then_approve(tmp_path: Path) -> None:
    r, calls = reviewer(
        tmp_path,
        [
            {"action": "edit", "edit": {"instruction": "bỏ bước 4"}},
            {"action": "edit", "edit": {"instruction": "chọn Sick thay vì Personal"}},
            {"action": "approve"},
        ],
    )
    run = review(r)
    assert run.status == "stopped_before_submit"
    assert calls[0] == ("", False, 0)  # the first run
    assert calls[1] == ("bỏ bước 4", True, 3)  # first run was tail-less partial: steps 1-3 kept
    assert calls[2][0] == "bỏ bước 4\nchọn Sick thay vì Personal" and calls[2][1]
    assert (tmp_path / "flow" / "flow_approved.json").is_file()
    assert sorted(p.name for p in (tmp_path / "flow" / "versions").iterdir()) == [
        "v1.json",
        "v2.json",
        "v3.json",
    ]


def test_regenerate_starts_over_and_forgets_the_notes(tmp_path: Path) -> None:
    r, calls = reviewer(
        tmp_path,
        [
            {"action": "edit", "edit": {"instruction": "bỏ bước 3"}},
            {"action": "regenerate"},
            {"action": "edit", "edit": {"instruction": "bỏ bước 5"}},
            {"action": "approve"},
        ],
    )
    review(r)
    assert calls[2] == ("", False, 0)
    assert calls[3][0] == "bỏ bước 5"  # the note before the restart is gone


def test_a_run_with_nothing_in_it_cannot_be_approved_and_an_empty_edit_is_asked_again(
    tmp_path: Path,
) -> None:
    answers = [
        {"action": "approve"},
        {"action": "edit"},
        {"action": "regenerate"},
        {"action": "approve"},
    ]
    r, _ = reviewer(tmp_path, answers)
    calls: list[tuple] = []
    runs = iter([make_run("failed", tail=False), make_run()])

    def run_flow(notes: str, previous: FlowRun | None, keep: int) -> FlowRun:
        calls.append((notes, previous is not None, keep))
        return next(runs)

    r.run_flow = run_flow  # type: ignore[attr-defined]
    run = review(r)
    assert run.status == "stopped_before_submit" and len(calls) == 2  # the failed run + regenerate


def test_an_approved_storyboard_is_reused_on_resume(tmp_path: Path) -> None:
    r, _ = reviewer(tmp_path, [{"action": "approve"}])
    review(r)
    again, calls = reviewer(tmp_path, [{"action": "cancel"}])
    assert review(again).flow_id == "leave" and not calls


def test_terminal_storyboard_offers_the_four_choices() -> None:
    from app.pipeline.frontend import TerminalFrontend
    from app.schemas.generated.core_flow import CoreFlow

    class Ask:
        def __init__(self, v: object) -> None:
            self.v = v

        def ask(self) -> object:
            return self.v

    class Q:
        class Choice:
            def __init__(self, title: str, value: str) -> None:
                self.title, self.value = title, value

        def __init__(self, action: str, text: str = "") -> None:
            self.action, self.typed = action, text
            self.offered: list[str] = []

        def select(self, _m: str, choices: list[Any]) -> Ask:
            self.offered = [c.value for c in choices]
            return Ask(self.action)

        def text(self, _m: str) -> Ask:
            return Ask(self.typed)

    req = build_request("j", CoreFlow.model_validate(flow_dict("leave")), make_run())
    q = Q("edit", "bỏ bước 3")
    resp = TerminalFrontend()._ask_storyboard(req, q)
    assert q.offered == ["approve", "edit", "regenerate", "cancel"]
    assert resp.action == "edit" and resp.edit and resp.edit.instruction == "bỏ bước 3"
    assert TerminalFrontend()._ask_storyboard(req, Q("approve")).action == "approve"


# --- the agent repeats the kept steps without asking the model ------------------------------


def test_kept_steps_are_replayed_and_the_agent_continues_from_there(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    browser_session.guard.write_log.clear()
    first_caller, _ = make_caller(tmp_path, [*FILL, step("stop_before_submit", "Apply")])
    first = FlowAgent(browser_session, first_caller, flow_for(site), tmp_path / "job").run()
    assert first.status == "stopped_before_submit"
    keep = keep_prefix(first, "đổi nội dung Comment")  # the comment step
    assert keep == len(first.steps) - 3  # goto + 4 fills kept; comment, hover, highlight redone
    plan = [step("type", "Comment", value="Doctor visit"), step("stop_before_submit", "Apply")]
    caller, llm = make_caller(tmp_path / "b", plan)
    run = FlowAgent(
        browser_session, caller, flow_for(site), tmp_path / "job2", previous=first, keep=keep,
        user_notes="đổi nội dung Comment",
    ).run()  # fmt: skip
    assert run.status == "stopped_before_submit" and not run.warnings
    assert len(llm.calls) == 2  # only the redone part was asked
    assert [s.action.do for s in run.steps[:5]] == [
        "goto",
        "select",
        "select",
        "pick_date",
        "pick_date",
    ]
    assert run.steps[5].value == "Doctor visit"
    assert run.sample_data == first.sample_data  # what was decided before is remembered
    assert "đổi nội dung Comment" in llm.calls[0]["prompt"]
    assert "select «Leave Type»" in llm.calls[0]["prompt"]  # the replayed steps are in the history


def test_a_kept_step_that_no_longer_works_ends_the_replay_with_a_warning(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    caller, _ = make_caller(tmp_path, [*FILL, step("stop_before_submit", "Apply")])
    first = FlowAgent(browser_session, caller, flow_for(site), tmp_path / "job").run()
    first.steps[2].action.text = "Sabbatical"  # that option does not exist (any more)
    caller2, llm2 = make_caller(tmp_path / "b", [step("finish")])
    run = FlowAgent(
        browser_session, caller2, flow_for(site), tmp_path / "job2", previous=first, keep=5
    ).run()
    assert any("Không lặp lại được bước 3" in w for w in run.warnings)
    assert [s.action.do for s in run.steps] == ["goto", "select"]  # stopped after the good step
    assert llm2.calls and run.status == "reached_goal"
