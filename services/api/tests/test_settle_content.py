"""wait_for_settle waits for the content of a page that fills itself with JS; a page that never
gets content is blank (not a valid storyboard step)."""

import time

from app.browser.page_utils import page_is_blank, wait_for_settle
from app.browser.session import BrowserSession
from app.core.flow_steps import counts


def test_a_page_that_renders_after_1_5_s_is_not_blank_after_the_wait(
    browser_session: BrowserSession, site: str
) -> None:
    page = browser_session.new_context().new_page()
    page.goto(f"{site}/late_content.html")
    result = wait_for_settle(page)
    assert result["content"] is True
    assert not page_is_blank(page)
    assert "Products" in page.inner_text("body")
    page.context.close()


def test_a_page_without_content_is_blank_and_the_wait_is_bounded(
    browser_session: BrowserSession, site: str
) -> None:
    page = browser_session.new_context().new_page()
    page.goto(f"{site}/never_content.html")
    started = time.monotonic()
    result = wait_for_settle(page)
    assert time.monotonic() - started < 9
    assert result["content"] is False and page_is_blank(page)
    page.context.close()


def test_a_page_with_content_does_not_wait(browser_session: BrowserSession, site: str) -> None:
    page = browser_session.new_context().new_page()
    page.goto(f"{site}/index.html")
    started = time.monotonic()
    wait_for_settle(page)
    assert time.monotonic() - started < 3
    page.context.close()


def test_blank_and_no_effect_steps_do_not_count() -> None:
    class Step:
        def __init__(self, blank: bool = False, no_effect: bool = False) -> None:
            self.blank, self.no_effect = blank, no_effect

    assert counts(Step()) and not counts(Step(blank=True)) and not counts(Step(no_effect=True))


def test_an_app_shell_with_a_field_is_not_blank(browser_session: BrowserSession) -> None:
    page = browser_session.new_context().new_page()
    page.set_content("<body><section><input placeholder='What needs to be done?'></section></body>")
    assert not page_is_blank(page)
    page.set_content("<body><nav><a href='/'>Home</a></nav><div id=app></div></body>")
    assert page_is_blank(page)
    page.context.close()
