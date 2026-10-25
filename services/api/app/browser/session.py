"""Playwright session (Chromium 1920x1080) with the request guard installed on every context."""

from pathlib import Path
from types import TracebackType

from playwright.sync_api import Browser, BrowserContext, Playwright, sync_playwright

from app.browser.guard import RequestGuard
from app.browser.privacy import BLUR_JS, blur_enabled

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
        blur_personal: bool | None = None,
        expect_session: bool = False,
    ) -> None:
        self.storage_state = storage_state
        # the job is a signed-in one: a login page is then a failure, even when the file is gone
        self.expect_session = expect_session
        self.blur_personal = blur_personal  # None: blur when a session is held (BLUR_PERSONAL_DATA)
        self.headless = headless
        self.guard = RequestGuard(root_url, allow_mutations=allow_mutations)
        self._pw: Playwright | None = None
        self.browser: Browser | None = None

    @property
    def signed_in_job(self) -> bool:
        return self.storage_state is not None or self.expect_session

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

    def new_context(
        self, record_video_dir: Path | None = None, viewport: dict[str, int] | None = None
    ) -> BrowserContext:
        """Fresh context (clean storage apart from --storage-state) with the guard installed.

        viewport: the explorer's 1920x1080 by default; the recorder passes the capture size.
        record_video_dir: record every page as a webm of that size into the directory.
        """
        assert self.browser is not None, "use BrowserSession as a context manager"
        size = viewport or VIEWPORT
        context = self.browser.new_context(
            viewport=size,
            storage_state=str(self.storage_state) if self.storage_state else None,
            record_video_dir=str(record_video_dir) if record_video_dir else None,
            record_video_size=size if record_video_dir else None,
        )
        context.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        context.set_default_timeout(8_000)
        context.route("**/*", self.guard.handle)
        blur = self.blur_personal
        if blur is None:
            blur = blur_enabled(self.storage_state is not None)
        if blur:  # personal data of a signed-in account must not reach screenshots or video
            context.add_init_script(BLUR_JS)
        return context
