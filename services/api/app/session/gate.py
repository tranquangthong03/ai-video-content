"""Login gate: ask the user to sign in, check that it worked, hand back a usable session.

Used wherever a LoginRequired comes up (start of a job, in the middle of exploring or recording).
The answers: "login_done" (a session file is in job-dir/storage_state.json: the browser window, an
uploaded auth.json), "answer" with a login_url (where to sign in) or with login_method="credentials"
(a demo account, handled by the credential_login hook). Every session is checked in a fresh
headless browser before it is accepted; a failed check keeps the card open with the reason.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.browser.auth_detect import LoginRequired, detect_login, is_login_path
from app.browser.page_utils import wait_for_settle
from app.browser.session import BrowserSession
from app.core.interaction import make_request
from app.pipeline.asker import ask as ask_user
from app.pipeline.frontend import Frontend

STORAGE_FILE = "storage_state.json"
LOG_FILE = "login_log.json"
RESULT_FILE = "login_result.json"  # {"final_url": ...} written by the browser-window login
MAX_ROUNDS = 6
METHODS = ["browser_window", "credentials", "upload_state"]
REASONS = {
    "redirect": "Trang này yêu cầu đăng nhập.",
    "password_field": "Trang này yêu cầu đăng nhập.",
    "http_status": "Trang này trả về lỗi 401/403 (cần đăng nhập).",
    "session_expired": "Phiên đăng nhập đã hết hạn.",
    "requested": "Bạn đã báo tính năng chính nằm sau đăng nhập.",
    "login_page": "Các cảnh quay ra trang đăng nhập: phiên đăng nhập không còn hiệu lực. "
    "Vui lòng đăng nhập lại.",
    "session_expired_review": "Phiên đăng nhập đã hết hạn trong lúc bạn duyệt kịch bản, "
    "vui lòng đăng nhập lại để quay video.",
}
EXPIRED = ("session_expired", "session_expired_review", "login_page")
NOT_INSIDE = "Chưa vào được trang bên trong, vui lòng thử lại."
HINT = "Chỉ dùng tài khoản demo, không dùng tài khoản thật có dữ liệu quan trọng."


@dataclass
class SessionCheck:
    ok: bool
    url: str  # where the session ended up


@dataclass
class LoginOutcome:
    storage_state: Path
    url: str  # the page the signed-in visitor lands on (the app's main page)
    login_url: str | None = None  # where the sign-in page is (asked again if the session expires)


Probe = Callable[[Path, str], SessionCheck]
CredentialLogin = Callable[[str, str], str | None]  # (login_url, target_url) -> failure or None


def verify_session(storage_state: Path, url: str) -> SessionCheck:
    """Open `url` with the session in a new headless browser: signed in when no sign-in signal."""
    with BrowserSession(url, storage_state=storage_state) as session:
        context = session.new_context()
        try:
            page = context.new_page()
            response = page.goto(url, wait_until="domcontentloaded")
            wait_for_settle(page)
            signal = detect_login(page, url, response.status if response else None)
            # still on a login page (e.g. the e-mail step, which has no password field yet): no
            stayed = is_login_path(url) and is_login_path(page.url)
            return SessionCheck(signal is None and not stayed, page.url)
        except Exception:
            return SessionCheck(False, url)
        finally:
            context.close()


def valid_http_url(text: str) -> str | None:
    text = text.strip()
    if text and "://" not in text:
        text = "https://" + text
    return text if text.startswith(("http://", "https://")) and " " not in text else None


class LoginGate:
    def __init__(
        self,
        job_id: str,
        job_dir: Path,
        frontend: Frontend,
        *,
        probe: Probe = verify_session,
        credential_login: CredentialLogin | None = None,
        has_credentials: Callable[[], bool] = lambda: False,
    ) -> None:
        self.job_id, self.dir, self.frontend = job_id, job_dir, frontend
        self.has_credentials = has_credentials
        self.events: list[dict[str, object]] = []  # what happened, without any secret
        self.probe = probe
        self.credential_login = credential_login

    def record(self, event: str, **fields: object) -> None:
        """Append to job-dir/login_log.json (events and outcomes only: never a credential)."""
        self.events.append({"at": time.strftime("%H:%M:%S"), "event": event, **fields})
        (self.dir / LOG_FILE).write_text(
            json.dumps(self.events, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @property
    def storage_state(self) -> Path:
        return self.dir / STORAGE_FILE

    def ask(self, need: LoginRequired) -> LoginOutcome:
        """Block until the user has signed in (checked) or cancelled (raises Cancelled)."""
        login_url = need.login_url or None
        target = need.target_url or login_url or ""
        failure: str | None = None
        self.record("login_required", reason=need.reason, login_url=login_url)
        if need.reason in EXPIRED and self.credential_login and self.has_credentials():
            # the job has a demo account: sign in again by itself before bothering the user
            failed = self.credential_login(login_url or target, target)
            self.record("auto_relogin", ok=failed is None, failure=failed)
            if failed is None:
                renewed = self.finish(login_url, target, need)
                if renewed is not None:
                    return renewed
        for _ in range(MAX_ROUNDS):
            request = make_request(
                self.job_id,
                "login_required",
                REASONS.get(need.reason, "Cần đăng nhập để xem trang này."),
                login={
                    "login_url": login_url,
                    "target_url": target or None,
                    "reason": need.reason,
                    "methods": METHODS,
                    "can_enter_url": login_url is None,
                    "failure": failure,
                    "hint": HINT,
                },
            )
            response = ask_user(self.frontend, self.dir, request)
            answers = response.answers or {}
            typed = valid_http_url(str(answers.get("login_url", "")))
            if typed:
                login_url, failure = typed, None
            if response.action == "answer":
                if answers.get("login_method") == "credentials":
                    if self.credential_login is None:
                        failure = "Đăng nhập bằng tài khoản demo chưa được hỗ trợ ở chế độ này."
                        continue
                    failure = self.credential_login(login_url or target, target)
                    if failure is not None:
                        continue
                elif typed:
                    continue  # only the URL was given: ask again with it filled in
                else:
                    failure = "Chưa nhận được thông tin đăng nhập."
                    continue
            elif not self.storage_state.is_file():  # login_done without a session file
                failure = NOT_INSIDE
                continue
            result = self.finish(login_url, target, need)
            if result is not None:
                return result
            failure = NOT_INSIDE
        raise RuntimeError("đăng nhập không thành công sau nhiều lần thử")

    def finish(
        self, login_url: str | None, target: str, need: LoginRequired
    ) -> LoginOutcome | None:
        """Check the saved session; the page to open is the one we wanted (or the login page)."""
        open_url = target if need.reason in EXPIRED else (login_url or target)
        if not open_url:
            return None
        check = self.probe(self.storage_state, open_url)
        self.record("verify_session", ok=check.ok, opened=open_url, ended_at=check.url)
        if not check.ok:
            return None
        final = check.url
        result_file = self.dir / RESULT_FILE
        if result_file.is_file():
            final = json.loads(result_file.read_text(encoding="utf-8")).get("final_url") or final
            result_file.unlink()
        return LoginOutcome(self.storage_state, final, login_url)
