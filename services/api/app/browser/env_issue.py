"""Is the page empty because the request guard refused what it needed? (flow agent, recorder)"""

from typing import Any

from playwright.sync_api import Page

from app.browser.guard import RequestGuard
from app.core.env_issue import KIND_GUARD

BLANK_JS = """
() => {
  const root = document.body ? document.body.cloneNode(true) : null;
  if (!root) return true;
  root.querySelectorAll('script,style,noscript,nav,header,footer,aside,[role=navigation]')
    .forEach((n) => n.remove());
  const text = (root.innerText || root.textContent || '').replace(/\s+/g, ' ').trim();
  if (text.length >= 40) return false;
  const big = (el) => {
    const r = el.getBoundingClientRect();
    return r.width >= 80 && r.height >= 80;
  };
  const media = [...document.querySelectorAll('canvas,video,svg,iframe')].some(big);
  const images = [...document.querySelectorAll('img')].some(
    (i) => i.complete && i.naturalWidth > 50 && big(i));
  return !(media || images);
}
"""

SINCE_PAD_S = 3.0  # requests refused up to this long before the action count as its cause


def page_is_blank(page: Page) -> bool:
    """The main area has (almost) no text and no loaded picture, canvas or video."""
    try:
        return bool(page.evaluate(BLANK_JS))
    except Exception:  # navigation destroyed the context: not judged
        return False


def check_env_issue(page: Page, guard: RequestGuard, since: float) -> dict[str, Any] | None:
    """`guard_broke_page` when the page is blank and the guard refused requests since `since`
    (guard.clock() before the action) minus a few seconds; the event goes to the guard's sink."""
    blocked = [u for t, u in guard.blocked_log if t >= since - SINCE_PAD_S]
    if not blocked or not page_is_blank(page):
        return None
    urls = list(dict.fromkeys(u.split("?")[0] for u in blocked))
    issue = {"kind": KIND_GUARD, "blocked_urls": urls[:10], "page_url": page.url.split("?")[0]}
    guard.env_issues.append(issue)
    if guard.sink is not None:
        guard.sink({"event": "env_issue", **issue})
    return issue
