"""The gate's way B: sign in with the job's demo account in a headless browser, keep the session."""

import json
from pathlib import Path

from app.browser.login import perform_login
from app.browser.session import BrowserSession
from app.core.credentials import CredentialStore
from app.session.gate import RESULT_FILE, STORAGE_FILE, CredentialLogin

REPORT_FILE = "login_report.json"  # which hosts the sign-in posted to; never any body


def make_credential_login(job_dir: Path, root_url: str) -> CredentialLogin:
    """(login_url, target_url) -> None when signed in (session saved), else why not (Vietnamese)."""

    def login(login_url: str, target_url: str) -> str | None:
        credentials = CredentialStore(job_dir).load()
        if credentials is None:
            return "Chưa có tài khoản demo (hoặc đã bị xóa). Hãy nhập lại."
        username, password = credentials
        where = login_url or target_url
        if not where:
            return "Chưa biết trang đăng nhập ở đâu. Hãy nhập địa chỉ trang đăng nhập."
        with BrowserSession(root_url or where) as session:
            context = session.new_context()
            try:
                page = context.new_page()
                page.goto(where, wait_until="domcontentloaded")
                attempt = perform_login(page, username, password, guard=session.guard)
                login_phase = session.guard.report()["login_phase"]
                (job_dir / REPORT_FILE).write_text(json.dumps(login_phase), encoding="utf-8")
                if not attempt.ok:
                    return attempt.message
                context.storage_state(path=str(job_dir / STORAGE_FILE))
                (job_dir / RESULT_FILE).write_text(
                    json.dumps({"final_url": attempt.final_url}), encoding="utf-8"
                )
                return None
            except Exception:
                return "Không mở được trang đăng nhập. Kiểm tra địa chỉ hoặc dùng cửa sổ đăng nhập."
            finally:
                context.close()

    return login
