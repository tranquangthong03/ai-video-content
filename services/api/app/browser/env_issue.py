"""Is the page empty because the request guard refused what it needed? (flow agent, recorder)"""

from typing import Any

from playwright.sync_api import Page

from app.browser.guard import RequestGuard
from app.browser.page_utils import page_is_blank
from app.core.env_issue import KIND_GUARD

SINCE_PAD_S = 3.0  # requests refused up to this long before the action count as its cause


def check_env_issue(
    page: Page, guard: RequestGuard, since: float, blank: bool | None = None
) -> dict[str, Any] | None:
    """`guard_broke_page` when the page is blank and the guard refused requests since `since`
    (guard.clock() before the action) minus a few seconds; the event goes to the guard's sink."""
    blocked = [u for t, u in guard.blocked_log if t >= since - SINCE_PAD_S]
    if not blocked or not (page_is_blank(page) if blank is None else blank):
        return None
    urls = list(dict.fromkeys(u.split("?")[0] for u in blocked))
    issue = {"kind": KIND_GUARD, "blocked_urls": urls[:10], "page_url": page.url.split("?")[0]}
    guard.env_issues.append(issue)
    if guard.sink is not None:
        guard.sink({"event": "env_issue", **issue})
    return issue
