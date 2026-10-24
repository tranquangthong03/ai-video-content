"""Playwright session (Chromium 1920x1080) with the request guard installed on every context."""

from pathlib import Path
from types import TracebackType

from playwright.sync_api import Browser, BrowserContext, Playwright, sync_playwright

from app.browser.guard import RequestGuard

VIEWPORT = {"width": 1920, "height": 1080}
NAV_TIMEOUT_MS = 20_000


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

    def new_context(self, record_video_dir: Path | None = None) -> BrowserContext:
        """Fresh context (clean storage apart from --storage-state) with the guard installed.

        record_video_dir: record every page of the context as 1920x1080 webm into that directory.
        """
        assert self.browser is not None, "use BrowserSession as a context manager"
        context = self.browser.new_context(
            viewport=VIEWPORT,
            storage_state=str(self.storage_state) if self.storage_state else None,
            record_video_dir=str(record_video_dir) if record_video_dir else None,
            record_video_size=VIEWPORT if record_video_dir else None,
        )
        context.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        context.set_default_timeout(8_000)
        context.route("**/*", self.guard.handle)
        return context
