"""What the Flow Agent needs from a film running while it works (the recorder implements it).

The agent only knows this interface; the recorder domain provides LiveFilm (app/recorder/live.py)
and the pipeline hands it in, so flows never import recorder."""

from pathlib import Path
from typing import Any, Protocol

from playwright.sync_api import BrowserContext, Page

from app.browser.form_actions import Ops


class Film(Protocol):
    raw_dir: Path  # where the browser context records its video
    ops: Ops  # the visible mouse and keyboard the actions use (valid after start())

    def prepare(self, context: BrowserContext) -> None: ...

    def start(self, page: Page, *, allow_submit: bool) -> None:
        """The page exists and is still blank: show the sync pulse."""

    def opened(self) -> None:
        """The first page is loaded: what follows is shown."""

    def begin_wait(self) -> None:
        """The agent starts asking the model (nothing may move until end_wait)."""

    def end_wait(self) -> None: ...

    def on_target(self, do: str, element: Any, state: Any, target: Any) -> None:
        """An action found its element (called by ActionRunner)."""

    def attempt_start(self) -> None: ...

    def attempt_end(self, ok: bool, step: int | None, do: str) -> None:
        """The action ended; when ok, `step` is its number in the run and the result is held."""

    def point_at(self, spec: dict[str, Any], name: str, first_step: int) -> bool:
        """Hover and outline the final button (two steps: first_step and first_step + 1)."""

    def stop(self) -> None:
        """No more actions: stop filming (before the context is closed)."""

    def finish(self) -> dict[str, Any] | None:
        """After the context is closed: the clip and logs; the dict is FlowRun.live (or None)."""
