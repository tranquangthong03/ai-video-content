"""Playwright session (Chromium 1920x1080): request guard, cookie banners, blockers."""

import re
from pathlib import Path
from types import TracebackType
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from app.core.safety import is_blocked
from app.explorer.guard import RequestGuard

VIEWPORT = {"width": 1920, "height": 1080}
NAV_TIMEOUT_MS = 20_000

ACCEPT_BUTTON = re.compile(
    r"^\s*(accept( all)?( cookies)?|agree|i agree|allow all|got it|đồng ý|chấp nhận( tất cả)?)\s*$",
    re.I,
)
HIDE_COOKIE_CSS = (
    '[id*="cookie" i], [class*="cookie" i], [class*="consent" i] { display: none !important; }'
)
CAPTCHA_FRAMES = ("recaptcha", "hcaptcha", "challenges.cloudflare.com", "turnstile")
CHALLENGE_TITLES = ("just a moment", "attention required", "verify you are human", "captcha")


class BrowserSession:
    def __init__(
        self,
        root_url: str,
        *,
        storage_state: Path | None = None,
        headless: bool = True,
        allow_mutations: bool = False,
    ) -> None:
        self.storage_state = storage_state
        self.headless = headless
        self.guard = RequestGuard(root_url, allow_mutations=allow_mutations)
        self._pw: Playwright | None = None
        self.browser: Browser | None = None

    def __enter__(self) -> "BrowserSession":
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=self.headless)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self.browser:
            self.browser.close()
        if self._pw:
            self._pw.stop()

    def new_context(self) -> BrowserContext:
        """Fresh context (clean storage apart from --storage-state) with the guard installed."""
        assert self.browser is not None, "use BrowserSession as a context manager"
        context = self.browser.new_context(
            viewport=VIEWPORT,
            storage_state=str(self.storage_state) if self.storage_state else None,
        )
        context.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        context.set_default_timeout(8_000)
        context.route("**/*", self.guard.handle)
        return context


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
