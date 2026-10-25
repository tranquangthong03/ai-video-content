from typing import Any

import pytest
from playwright.sync_api import Page

from app.browser.locate import resolve
from app.browser.session import BrowserSession
from app.flows.page_state import (
    MAX_ELEMENTS,
    PageElement,
    build_state,
    capture_state,
    format_elements,
    format_messages,
)


@pytest.fixture
def page(browser_session: BrowserSession, site: str) -> Any:
    context = browser_session.new_context()
    page = context.new_page()
    page.goto(site + "/flowform.html")
    yield page
    context.close()


def by_name(state: Any, name: str) -> PageElement:
    return next(e for e in state.elements if e.name == name)


def test_the_state_has_url_title_heading_and_what_the_page_says(page: Page) -> None:
    state = capture_state(page)
    assert state.url.endswith("/flowform.html") and state.title == "HR - Apply Leave"
    assert state.heading == "Apply Leave"
    assert "Leave type is required" in state.messages
    assert "Comment is too short" in state.messages  # the text of an aria-invalid field's message


def test_fields_carry_name_placeholder_value_options_and_flags(page: Page) -> None:
    page.fill("#from", "2026-11-02")
    state = capture_state(page)
    leave_type = by_name(state, "Leave type")
    assert leave_type.role == "combobox" and leave_type.value == "-- Select --"
    assert leave_type.options == ["-- Select --", "Annual", "Personal", "Sick"]
    from_date = by_name(state, "From date")
    assert from_date.placeholder == "yyyy-mm-dd" and from_date.value == "2026-11-02"
    assert by_name(state, "To date").input_type == "date"
    note = by_name(state, "Comment")
    assert note.invalid and note.role == "textbox"
    half = by_name(state, "Half day")
    assert half.role == "checkbox" and half.value == "unchecked"
    page.check("#half")
    assert by_name(capture_state(page), "Half day").value == "checked"
    assert by_name(state, "Cancel request").disabled
    apply = by_name(state, "Apply")
    assert apply.is_submit_like and not apply.disabled


def test_a_custom_dropdown_is_a_combobox_and_lists_its_options_only_when_open(page: Page) -> None:
    closed = capture_state(page)
    assert by_name(closed, "Reason category").role == "combobox"
    assert not any(e.name == "Medical" for e in closed.elements)
    page.click("#cat")
    opened = capture_state(page)
    options = [e for e in opened.elements if e.role == "option"]
    assert [e.name for e in options] == ["Family", "Medical", "Travel"]


def test_forbidden_things_are_not_offered(page: Page) -> None:
    names = {e.name for e in capture_state(page).elements}
    assert "Delete draft" not in names  # blacklisted control
    assert "Logout" not in names and "Settings" not in names  # side / sensitive links
    assert "Password" not in names  # never offered: the agent must not type into it
    assert {"Dashboard", "Leave", "Apply"} <= names


def test_elements_far_below_the_viewport_are_left_out_until_scrolled_to(page: Page) -> None:
    state = capture_state(page)
    assert "Way down" not in {e.name for e in state.elements}
    assert state.can_scroll_down
    page.mouse.wheel(0, 3000)
    page.wait_for_timeout(200)
    after = capture_state(page)
    far = by_name(after, "Way down")
    assert far.in_view and after.scroll_y > 2000


def test_every_listed_element_can_be_resolved_again_from_its_locator(page: Page) -> None:
    state = capture_state(page)
    for name in ("Leave type", "From date", "Comment", "Apply", "Leave"):
        found = resolve(page, by_name(state, name).locator)
        assert found.target is not None, (name, found.tried)


def test_refs_are_short_unique_and_follow_the_document_order(page: Page) -> None:
    refs = [e.ref for e in capture_state(page).elements]
    assert refs == [f"e{i}" for i in range(1, len(refs) + 1)]


def raw_element(i: int, **kw: Any) -> dict[str, Any]:
    base = {
        "index": i, "role": "button", "tag": "button", "name": f"B{i}", "text": f"B{i}", "value": "",
        "options": [f"o{k}" for k in range(15)], "region": "main", "placeholder": "",
        "input_type": None, "disabled": False, "required": False, "invalid": False, "href": None,
        "in_form": False, "button_type": None, "in_view": True, "selector": None, "query": "button",
        "nth": i, "fingerprint": f"button|b{i}|0.5,0.5", "bbox": [0, i, 10, 10],
    }  # fmt: skip
    return {**base, **kw}


def raw_state(elements: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "url": "https://x.test/", "title": "t", "heading": "h", "messages": ["m"] * 9,
        "elements": elements, "scroll_y": 0, "max_scroll": 0,
    }  # fmt: skip


def test_at_most_sixty_elements_on_screen_and_dialogs_come_first() -> None:
    elements = [raw_element(i, in_view=i < 40) for i in range(100)]
    elements.append(raw_element(100, region="dialog", in_view=False, name="Confirm"))
    state = build_state(raw_state(elements))
    assert len(state.elements) == MAX_ELEMENTS
    names = [e.name for e in state.elements]
    assert "Confirm" in names  # the dialog outranks everything
    assert all(f"B{i}" in names for i in range(39))  # the visible ones are kept
    assert len(state.messages) == 5 and all(len(e.options) <= 10 for e in state.elements)


def test_build_state_drops_blocked_and_sensitive_entries() -> None:
    raw = [
        raw_element(1, name="Delete account"), raw_element(2, name="Save", role="button"),
        raw_element(3, name="Profile settings", role="link", href="https://x.test/a"),
        raw_element(4, name="Home", role="link", href="https://x.test/"),
        raw_element(5, name="Home", role="link", href="https://x.test/logout"),
    ]  # fmt: skip
    state = build_state(raw_state(raw))
    assert [e.name for e in state.elements] == ["Save", "Home"]  # save is the agent's to see


def test_the_prompt_lines_and_messages_format() -> None:
    state = build_state(
        raw_state([raw_element(1, name="Type", role="combobox", options=["A", "B"], disabled=True,
                               value="A", placeholder="pick", in_view=False)])
    )  # fmt: skip
    assert (
        format_elements(state.elements)
        == "e1 | combobox | Type | pick | A | A/B | disabled,offscreen | main"
    )
    assert format_messages([]) == "không có" and format_messages(["a", "b"]) == "a; b"


def test_a_transparent_tick_box_drawn_by_its_label_is_listed_and_named_by_its_row(
    browser_session: BrowserSession, site: str
) -> None:
    from app.flows.actions import ActionRunner, FlowAction

    context = browser_session.new_context()
    page = context.new_page()
    page.goto(site + "/todo_styled.html")
    state = capture_state(page)
    boxes = [e for e in state.elements if e.role == "checkbox"]
    assert [e.name for e in boxes] == ["Mua sữa", "Gọi cho mẹ"]
    runner = ActionRunner(page, site, guard=browser_session.guard)
    runner.run(state, FlowAction(do="check", ref=boxes[1].ref))
    assert page.locator("input.toggle").nth(1).is_checked()
    assert not page.locator("input.toggle").nth(0).is_checked()
    context.close()


def test_a_field_whose_label_is_only_next_to_it_still_gets_the_label_as_its_name(
    browser_session: BrowserSession, site: str
) -> None:
    context = browser_session.new_context()
    page = context.new_page()
    page.goto(site + "/labels_apart.html")
    state = capture_state(page)
    fields = [e for e in state.elements if e.role == "textbox"]
    assert [e.name for e in fields] == ["From Date", "To Date"]  # not both "yyyy-dd-mm"
    assert [e.placeholder for e in fields] == ["yyyy-dd-mm", "yyyy-dd-mm"]
    assert state.heading == "Apply Leave"  # an h6 title counts
    context.close()


def test_a_page_with_nothing_to_operate_says_what_it_shows(
    browser_session: BrowserSession, site: str
) -> None:
    context = browser_session.new_context()
    page = context.new_page()
    page.goto(site + "/empty_state.html")
    state = capture_state(page)
    assert state.heading == "Apply Leave"
    assert "Nội dung trang: No Leave Types with Leave Balance" in state.messages
    assert not any("Sidebar" in m or "©" in m for m in state.messages)
    page.goto(site + "/flowform.html")  # a page with a form does not add its text as messages
    assert not any(m.startswith("Nội dung trang") for m in capture_state(page).messages)
    context.close()
