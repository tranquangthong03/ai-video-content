"""Still image of a page for scenes that show a photo instead of a recording."""

from pathlib import Path

from app.browser.page_utils import dismiss_cookie_banner, wait_for_settle
from app.browser.session import BrowserSession


def take_screenshot(session: BrowserSession, url: str, out_path: Path) -> Path:
    """1920x1080 PNG of `url` once it has settled and the cookie banner is gone."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    context = session.new_context()
    try:
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        wait_for_settle(page)
        if dismiss_cookie_banner(page):
            wait_for_settle(page, timeout=1500)
        page.screenshot(path=str(out_path))
    finally:
        context.close()
    return out_path
