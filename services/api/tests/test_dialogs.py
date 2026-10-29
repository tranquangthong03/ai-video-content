"""Native dialogs never hang a page: alert is accepted, confirm / prompt dismissed, all reported."""

from app.browser.dialogs import dialog_line
from app.browser.session import BrowserSession


def test_alert_confirm_and_prompt_do_not_stall_and_are_recorded(
    browser_session: BrowserSession, site: str
) -> None:
    guard = browser_session.guard
    guard.dialogs.clear()
    guard.unseen_dialogs.clear()
    page = browser_session.new_context().new_page()
    page.goto(f"{site}/dialogs.html")
    page.click("#a")
    assert page.inner_text("#out") == "alert done"
    page.click("#c")
    assert page.inner_text("#out") == "no"  # dismissed: the safe answer
    page.click("#p")
    assert page.inner_text("#out") == "null"
    assert [d["type"] for d in guard.dialogs] == ["alert", "confirm", "prompt"]
    assert guard.dialogs[0]["message"] == "Product added"
    told = guard.take_dialogs()
    assert len(told) == 3 and guard.take_dialogs() == []
    assert "Product added" in dialog_line(told[0])
    page.context.close()


def test_a_confirm_is_accepted_inside_a_write_window(
    browser_session: BrowserSession, site: str
) -> None:
    page = browser_session.new_context().new_page()
    page.goto(f"{site}/dialogs.html")
    guard = browser_session.guard
    guard.write_windows = 0
    with guard.allow_writes():
        page.click("#c")
    assert page.inner_text("#out") == "yes"
    page.context.close()
