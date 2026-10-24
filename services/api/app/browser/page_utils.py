"""Page-level helpers shared by every browser-driving module."""

import re
from typing import Any

from playwright.sync_api import Page

from app.browser.blacklist import is_blocked

ACCEPT_BUTTON = re.compile(
    r"^\s*(accept( all)?( cookies)?|agree|i agree|allow all|got it|đồng ý|chấp nhận( tất cả)?)\s*$",
    re.I,
)
HIDE_COOKIE_CSS = (
    '[id*="cookie" i], [class*="cookie" i], [class*="consent" i] { display: none !important; }'
)
CAPTCHA_FRAMES = ("recaptcha", "hcaptcha", "challenges.cloudflare.com", "turnstile")
CHALLENGE_TITLES = ("just a moment", "attention required", "verify you are human", "captcha")


def dismiss_cookie_banner(page: Page) -> bool:
    """Click an accept button if there is one; otherwise hide cookie/consent overlays with CSS."""
    try:
        for role in ("button", "link"):
            button = page.get_by_role(role, name=ACCEPT_BUTTON).first  # type: ignore[arg-type]
            if (
                button.count()
                and button.is_visible()
                and not is_blocked(button.inner_text(timeout=500))
            ):
                button.click(timeout=1500)
                page.wait_for_timeout(300)
                return True
    except Exception:  # banner handling must never break the crawl
        pass
    try:
        page.add_style_tag(content=HIDE_COOKIE_CSS)
    except Exception:
        pass
    return False


def detect_blockers(page: Page, status: int | None) -> dict[str, Any]:
    """{needs_login, captcha, http_error}: reasons the current page may not be explorable."""
    try:
        needs_login = page.locator("input[type=password]:visible").count() > 0
    except Exception:
        needs_login = False
    title = ""
    try:
        title = page.title().lower()
    except Exception:
        pass
    frames = any(any(k in (f.url or "") for k in CAPTCHA_FRAMES) for f in page.frames)
    captcha = frames or any(t in title for t in CHALLENGE_TITLES)
    return {
        "needs_login": needs_login,
        "captcha": captcha,
        "http_error": status if status is not None and status >= 400 else None,
    }
