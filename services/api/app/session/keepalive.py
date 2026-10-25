"""Keep a signed-in session alive while the user reads and thinks (a light, optional nicety).

Every few minutes, while a job waits for an answer, a headless browser opens the app's main page
with the saved session (a GET, nothing is clicked) and writes the cookies it ends with back into
storage_state.json: sites that slide the session lifetime on each visit then keep it going.
KEEPALIVE_SESSION=0 turns it off; KEEPALIVE_INTERVAL_S changes the 4 minutes.
"""

import os
from pathlib import Path

from app.browser.auth_detect import detect_login
from app.browser.page_utils import wait_for_settle
from app.browser.session import BrowserSession


def keepalive_enabled(env: dict[str, str] | None = None) -> bool:
    value = (env if env is not None else os.environ).get("KEEPALIVE_SESSION", "1").strip().lower()
    return value not in ("0", "false", "off", "no")


def keepalive_interval(env: dict[str, str] | None = None) -> float:
    raw = (env if env is not None else os.environ).get("KEEPALIVE_INTERVAL_S", "")
    try:
        return max(5.0, float(raw)) if raw else 240.0
    except ValueError:
        return 240.0


def refresh_session(storage_state: Path, url: str) -> bool:
    """GET `url` with the session; when still good, save the refreshed cookies. Never clicks."""
    try:
        with BrowserSession(url, storage_state=storage_state) as session:
            context = session.new_context()
            try:
                page = context.new_page()
                response = page.goto(url, wait_until="domcontentloaded")
                wait_for_settle(page, timeout=3000)
                if detect_login(page, url, response.status if response else None) is not None:
                    return False  # already gone: leave the file as it is
                tmp = storage_state.with_name(storage_state.name + ".tmp")
                context.storage_state(path=str(tmp))
                tmp.replace(storage_state)
                return True
            finally:
                context.close()
    except Exception:
        return False
