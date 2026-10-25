"""Still image of a page for scenes that show a photo instead of a recording."""

from pathlib import Path

from app.browser.auth_detect import LoginRequired, detect_login
from app.browser.page_utils import dismiss_cookie_banner, wait_for_settle
from app.browser.session import BrowserSession


def take_screenshot(
    session: BrowserSession, url: str, out_path: Path, viewport: dict[str, int] | None = None
) -> Path:
    """Viewport-sized PNG (default 1920x1080) of `url` once settled, cookie banner gone.

    Raises LoginRequired when a signed-in job lands on a sign-in page (never photograph that)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    context = session.new_context(viewport=viewport)
    try:
        page = context.new_page()
        response = page.goto(url, wait_until="domcontentloaded")
        wait_for_settle(page)
        if session.signed_in_job:
            signal = detect_login(page, url, response.status if response else None)
            if signal is not None:
                raise LoginRequired(signal.login_url, "session_expired", target_url=url)
        if dismiss_cookie_banner(page):
            wait_for_settle(page, timeout=1500)
        page.screenshot(path=str(out_path))
    finally:
        context.close()
    return out_path
