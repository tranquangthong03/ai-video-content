"""Native dialogs (alert / confirm / prompt): never left open, always reported to the agent.

alert and beforeunload are accepted; confirm and prompt are dismissed (answering "no" is the
safe answer), unless a write window is open (the flow is allowed to submit): then a confirm is
accepted. Every dialog becomes a `dialog {type, message}` event and is kept for the agent's next
observation.
"""

from typing import Any

from playwright.sync_api import Dialog, Page

from app.browser.guard import RequestGuard

MAX_MESSAGE = 200


def handle_dialog(dialog: Dialog, guard: RequestGuard) -> None:
    kind, message = dialog.type, (dialog.message or "")[:MAX_MESSAGE]
    guard.note_dialog(kind, message)
    try:
        if kind in ("alert", "beforeunload") or (kind == "confirm" and guard.write_phase):
            dialog.accept()
        else:
            dialog.dismiss()
    except Exception:  # the page went away under the dialog: nothing left to answer
        pass


def install_dialog_handler(page: Page, guard: RequestGuard) -> None:
    page.on("dialog", lambda dialog: handle_dialog(dialog, guard))


def dialog_line(event: dict[str, Any]) -> str:
    return f"Hộp thoại {event['type']} vừa hiện: «{event['message']}»"
