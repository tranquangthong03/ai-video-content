"""Way A: a real browser window where the user signs in by themselves.

One thread owns Playwright (its sync API must not be shared between threads) and every window;
the API talks to it through a queue. A window is a persistent Chromium context (profile in the job
dir, 1280x800) opened at the login page. When the user says "done" its cookies are saved as
storage_state.json, the page it ended on is remembered (login_result.json), the window is closed.
A window left open for TIMEOUT_S is closed by itself. This only works when the API runs on the
same computer as the user (the local demo): the window opens on the machine that runs the API.
"""

import json
import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Page, sync_playwright

TIMEOUT_S = 600  # a window nobody confirms is closed after 10 minutes
VIEWPORT = {"width": 1280, "height": 800}
POLL_S = 0.2

STATUS_NONE = "none"
STATUS_OPEN = "browser_open"
STATUS_TIMEOUT = "timeout"
STATUS_CLOSED = "closed"


@dataclass
class _Window:
    context: BrowserContext
    page: Page
    opened: float = field(default_factory=time.monotonic)


class LoginWindows:
    def __init__(self, *, headless: bool = False, timeout_s: float = TIMEOUT_S) -> None:
        self.headless = headless
        self.timeout_s = timeout_s
        self._commands: queue.Queue[tuple[Callable[[], Any], Future[Any]] | None] = queue.Queue()
        self._windows: dict[str, _Window] = {}
        self._status: dict[str, str] = {}
        self._thread = threading.Thread(target=self._loop, name="login-windows", daemon=True)
        self._thread.start()

    # --- the thread that owns the browser ---------------------------------------------------------

    def _loop(self) -> None:
        with sync_playwright() as pw:
            while True:
                try:
                    item = self._commands.get(timeout=POLL_S)
                except queue.Empty:
                    self._expire()
                    continue
                if item is None:
                    break
                call, future = item
                try:
                    future.set_result(call(pw))  # type: ignore[call-arg]
                except Exception as e:  # report to the caller, never kill the thread
                    future.set_exception(e)
            for job_id in list(self._windows):
                self._close(job_id, STATUS_CLOSED)

    def _expire(self) -> None:
        for job_id, w in list(self._windows.items()):
            if time.monotonic() - w.opened >= self.timeout_s:
                self._close(job_id, STATUS_TIMEOUT)

    def _close(self, job_id: str, status: str) -> None:
        window = self._windows.pop(job_id, None)
        if window is not None:
            try:
                window.context.close()
            except Exception:
                pass
        self._status[job_id] = status

    def _submit(self, call: Callable[[Any], Any]) -> Any:
        future: Future[Any] = Future()
        self._commands.put((call, future))  # type: ignore[arg-type]
        return future.result(timeout=60)

    # --- what the API calls ------------------------------------------------------------------

    def status(self, job_id: str) -> str:
        return STATUS_OPEN if job_id in self._windows else self._status.get(job_id, STATUS_NONE)

    def open(self, job_id: str, url: str, profile_dir: Path) -> None:
        def call(pw: Any) -> None:
            self._close(job_id, STATUS_CLOSED)
            profile_dir.mkdir(parents=True, exist_ok=True)
            context = pw.chromium.launch_persistent_context(
                str(profile_dir), headless=self.headless, viewport=VIEWPORT
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            self._windows[job_id] = _Window(context, page)
            self._status[job_id] = STATUS_OPEN

        self._submit(call)

    def finish(self, job_id: str, job_dir: Path) -> str | None:
        """Save the window's session as job-dir/storage_state.json and close it.

        Returns the URL the user ended on (also written to login_result.json), or None when there
        is no window (it was never opened, timed out or was closed)."""

        def call(_pw: Any) -> str | None:
            window = self._windows.get(job_id)
            if window is None:
                return None
            final_url = window.page.url
            for page in reversed(window.context.pages):  # the tab the user used last
                if page.url and not page.url.startswith("about:"):
                    final_url = page.url
                    break
            window.context.storage_state(path=str(job_dir / "storage_state.json"))
            (job_dir / "login_result.json").write_text(
                json.dumps({"final_url": final_url}), encoding="utf-8"
            )
            self._close(job_id, STATUS_CLOSED)
            return final_url

        return self._submit(call)  # type: ignore[no-any-return]

    def close(self, job_id: str) -> None:
        self._submit(lambda _pw: self._close(job_id, STATUS_CLOSED))

    def run_in_window(self, job_id: str, fn: Callable[[Page], Any]) -> Any:
        """Run `fn(page)` on the window's thread (tests play the user with it)."""

        def call(_pw: Any) -> Any:
            return fn(self._windows[job_id].page)

        return self._submit(call)

    def shutdown(self) -> None:
        self._commands.put(None)
        self._thread.join(timeout=15)
