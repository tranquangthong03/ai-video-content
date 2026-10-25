from datetime import date
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page
from pydantic import ValidationError

from app.browser.form_actions import ActionFailed, fold, format_date, parse_iso
from app.browser.locate import Unsafe
from app.browser.session import BrowserSession
from app.flows.actions import ActionRunner, FlowAction, is_submit_target
from app.flows.page_state import PageElement, capture_state
from tests.test_recorder import goto, loc, rec


@pytest.fixture
def env(browser_session: BrowserSession, site: str) -> Any:
    context = browser_session.new_context()
    page = context.new_page()
    page.goto(site + "/flow_apply.html")
    yield page, site, browser_session
    context.close()


def act(page: Page, runner: ActionRunner, name: str, **kw: Any) -> Any:
    state = capture_state(page)
    ref = next(e.ref for e in state.elements if e.name == name)
    return runner.run(state, FlowAction(ref=ref, **kw))


def runner_for(env: Any, **kw: Any) -> ActionRunner:
    page, site, session = env
    return ActionRunner(page, site, guard=session.guard, **kw)


# --- pure parts -------------------------------------------------------------------------------


def test_the_date_is_written_like_the_hint() -> None:
    d = date(2026, 11, 2)
    assert format_date(d, "dd/mm/yyyy") == "02/11/2026"
    assert format_date(d, "yyyy-mm-dd") == "2026-11-02"
    assert format_date(d, "mm.dd.yy") == "11.02.26"
    assert format_date(d, "d MMM yyyy") == "2 Nov 2026"
    assert format_date(d, "Select date") is None and format_date(d, "") is None


def test_iso_dates_only_and_accent_blind_folding() -> None:
    assert parse_iso(" 2026-11-02 ") == date(2026, 11, 2)
    with pytest.raises(ActionFailed):
        parse_iso("02/11/2026")
    assert fold("  Nghỉ  Phép Đặc biệt ") == "nghi phep dac biet"


def test_an_action_needs_what_its_kind_needs() -> None:
    assert FlowAction(do="scroll").direction == "down"
    for bad in ({"do": "click"}, {"do": "type", "ref": "e1"}, {"do": "select", "value": "x"}):
        with pytest.raises(ValidationError):
            FlowAction(**bad)
    assert FlowAction(do="finish").ref is None


def el(name: str, **kw: Any) -> PageElement:
    return PageElement(
        ref="e1", role=kw.pop("role", "button"), tag=kw.pop("tag", "button"), name=name, **kw
    )


def test_submit_targets_are_form_buttons_never_menu_links() -> None:
    assert is_submit_target(el("Apply", in_form=True, button_type="submit"))
    assert is_submit_target(el("Lưu", in_form=True))
    assert is_submit_target(el("Whatever", input_type="submit", tag="input"))
    assert not is_submit_target(el("Apply", role="link", tag="a"))  # a menu entry called Apply
    assert not is_submit_target(el("Apply", in_form=False))  # a button outside a form
    assert not is_submit_target(el("Cancel", in_form=True))


# --- on the page ------------------------------------------------------------------------------


def test_select_in_a_native_dropdown_and_a_dropdown_the_page_draws(env: Any) -> None:
    page, _, _ = env
    runner = runner_for(env)
    act(page, runner, "Leave Type", do="select", value="Annual")
    assert page.eval_on_selector("#kind", "e => e.selectedOptions[0].text") == "Annual"
    act(page, runner, "Reason category", do="select", value="Medical")
    assert page.inner_text("#cat") == "Medical"
    assert not page.locator("#catmenu").is_visible()  # the list closed again


def test_select_with_a_missing_option_says_what_exists(env: Any) -> None:
    page, _, _ = env
    runner = runner_for(env)
    with pytest.raises(ActionFailed, match="Annual"):
        act(page, runner, "Leave Type", do="select", value="Sabbatical")
    with pytest.raises(ActionFailed, match="Sabbatical"):
        act(page, runner, "Reason category", do="select", value="Sabbatical")


def test_dates_are_typed_in_the_fields_format_else_picked_in_the_calendar(env: Any) -> None:
    page, _, _ = env
    runner = runner_for(env)
    act(page, runner, "From Date", do="pick_date", value="2027-03-05")
    assert page.input_value("#from") == "05/03/2027"  # typed, no calendar needed
    act(page, runner, "To Date", do="pick_date", value="2027-03-07")  # read-only: the calendar
    assert page.input_value("#to") == "07/03/2027"


def test_the_calendar_walks_back_and_forward_to_the_month(env: Any) -> None:
    page, _, _ = env
    runner = runner_for(env)
    act(page, runner, "To Date", do="pick_date", value="2025-12-20")  # in the past: Previous
    assert page.input_value("#to") == "20/12/2025"


def test_check_ticks_once_and_type_fills_a_field(env: Any) -> None:
    page, _, _ = env
    runner = runner_for(env)
    act(page, runner, "Half day", do="check")
    act(page, runner, "Half day", do="check")  # already ticked: unchanged
    assert page.is_checked("#half")
    act(page, runner, "Comment", do="type", value="Family event")
    assert page.input_value("#comment") == "Family event"


def test_a_ref_that_is_not_listed_is_refused(env: Any) -> None:
    page, _, _ = env
    with pytest.raises(ActionFailed, match="không có trong danh sách"):
        runner_for(env).run(capture_state(page), FlowAction(do="click", ref="e999"))


def test_typing_into_a_button_or_choosing_in_a_text_box_fails_cleanly(env: Any) -> None:
    page, _, _ = env
    runner = runner_for(env)
    with pytest.raises(ActionFailed):
        act(page, runner, "Apply", do="type", value="x")


def test_the_submit_button_is_refused_while_the_policy_is_stop(env: Any) -> None:
    page, _, _ = env
    runner = runner_for(env)  # allow_submit=False
    with pytest.raises(Unsafe, match="không được phép gửi"):
        act(page, runner, "Apply", do="click")
    assert page.inner_text("#result") == ""  # nothing happened


def test_with_allow_the_submit_is_clicked_inside_a_write_window_and_counted(env: Any) -> None:
    page, _, session = env
    runner = runner_for(env, allow_submit=True)
    result = act(page, runner, "Apply", do="click")
    assert result.submitted and runner.submits == 1
    assert "Required" in page.inner_text("#result")  # the page validated: nothing was filled in
    assert session.guard.write_windows == 1
    act(page, runner, "Apply", do="click")
    with pytest.raises(Unsafe, match="2 lần"):
        act(page, runner, "Apply", do="click")


def test_on_a_shared_demo_site_the_submit_is_refused_even_with_allow(
    browser_session: BrowserSession, site: str
) -> None:
    context = browser_session.new_context()
    page = context.new_page()
    page.goto(site + "/flow_apply.html")
    from app.browser.guard import RequestGuard

    shared = RequestGuard("https://opensource-demo.orangehrmlive.com/")
    runner = ActionRunner(page, site, allow_submit=True, guard=shared)
    with pytest.raises(Unsafe, match="ghi dữ liệu"):
        act(page, runner, "Apply", do="click")
    context.close()


def test_scroll_moves_the_page(env: Any) -> None:
    page, _, _ = env
    page.set_viewport_size({"width": 800, "height": 300})
    runner = runner_for(env)
    runner.run(capture_state(page), FlowAction(do="scroll", direction="down"))
    assert page.evaluate("window.scrollY") > 50


def test_navigation_through_a_menu_link_changes_the_url_and_is_reported(env: Any) -> None:
    page, site, _ = env
    runner = runner_for(env)
    result = act(page, runner, "My Leave", do="navigate")
    assert result.url_before.endswith("/flow_apply.html") and result.url_after.endswith(
        "/flow_myleave.html"
    )
    assert result.locator is not None and result.target_text == "My Leave"


def test_a_navigation_to_another_site_is_refused(env: Any) -> None:
    page, _, _ = env
    page.evaluate("document.querySelector('nav a').href = 'https://other.example.org/'")
    runner = runner_for(env)
    with pytest.raises(Unsafe):
        act(page, runner, "Dashboard", do="navigate")


# --- replay in the recorder -------------------------------------------------------------------


def test_the_recorder_replays_the_form_actions_from_their_locators(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    page_ = site + "/flow_apply.html"
    visual = {
        "mode": "recording",
        "actions": [
            goto(site, "/flow_apply.html"),
            {"do": "select", "locator": loc("#kind"), "text": "Sick"},
            {"do": "select", "locator": loc("#cat"), "text": "Travel"},
            {"do": "pick_date", "locator": loc("#from"), "text": "2027-03-05"},
            {"do": "pick_date", "locator": loc("#to"), "text": "2027-03-06"},
            {"do": "check", "locator": loc("#half")},
            {"do": "type", "locator": loc("#comment"), "text": "Family trip"},
        ],
    }
    r = rec(browser_session, site, tmp_path, visual, speech_ms=1500)
    assert r.warnings == [] and r.steps_ok == 6 and r.kind == "recording", (page_, r.warnings)
    done = [a["do"] for a in r.action_log]
    assert done.count("select") == 2 and "pick_date" in done and "check" in done
    assert any(f["kind"] == "click" for f in r.focus_log)  # the camera has something to follow


def test_the_recorder_replays_navigate_across_pages(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    visual = {
        "mode": "recording",
        "actions": [
            goto(site, "/flow_home.html"),
            {"do": "navigate", "locator": loc(None, role="link", name="Leave")},
            {"do": "navigate", "locator": loc(None, role="link", name="My Leave")},
        ],
    }
    r = rec(browser_session, site, tmp_path, visual, speech_ms=1500)
    assert r.warnings == [] and r.steps_ok == 2  # the goto is not counted
    texts = [(i["kind"], i["text"]) for s in r.inventory for i in s["items"]]
    assert ("heading", "My Leave") in texts, texts[-12:]
