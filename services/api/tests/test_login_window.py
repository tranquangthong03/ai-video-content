import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Page

from app.api.main import create_app
from app.browser.auth_detect import LoginRequired
from app.pipeline.file_frontend import FileFrontend
from app.pipeline.runner import JobConfig, JobResult
from app.pipeline.state import update_state
from app.session.browser_login import LoginWindows
from app.session.gate import LoginGate
from tests.auth_site import EMAIL, PASSWORD, AuthSite, running_site

OUTCOME: dict[str, Any] = {}


def sign_in_pipeline(site: AuthSite) -> Callable[[JobConfig, FileFrontend], JobResult]:
    """A pipeline that only asks for the sign-in (the real gate), then records what it got."""

    def pipeline(cfg: JobConfig, frontend: FileFrontend) -> JobResult:
        gate = LoginGate(cfg.job_dir.name, cfg.job_dir, frontend)
        outcome = gate.ask(LoginRequired(site.base + "/login", "requested", target_url=site.base))
        OUTCOME[cfg.job_dir.name] = outcome
        OUTCOME[cfg.job_dir.name + ":saved"] = outcome.storage_state.is_file()
        update_state(cfg.job_dir, status="done", step="done", progress_pct=100)
        return JobResult(0, "done")

    return pipeline


@pytest.fixture
def site() -> Iterator[AuthSite]:
    with running_site() as s:
        yield s


def until(check: Callable[[], Any], seconds: float = 90) -> Any:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("condition not reached in time")


def client_for(tmp_path: Path, site: AuthSite, windows: LoginWindows) -> TestClient:
    app = create_app(tmp_path / "jobs", sign_in_pipeline(site), windows)
    c = TestClient(app)
    c.__enter__()
    c.app.state.runner.poll_s = 0.05  # type: ignore[attr-defined]
    return c


def current_card(c: TestClient, job_id: str) -> dict[str, Any] | None:
    d = c.get(f"/api/jobs/{job_id}").json()
    p = d["pending"]
    return p if d["state"]["status"] == "waiting" and p and p["kind"] == "login_required" else None


def waiting_card(c: TestClient, job_id: str) -> dict[str, Any]:
    return until(lambda: current_card(c, job_id))  # type: ignore[no-any-return]


def answer(c: TestClient, card: dict[str, Any], action: str = "login_done") -> Any:
    body = {"interaction_id": card["interaction_id"], "job_id": card["job_id"], "action": action}
    return c.post(f"/api/jobs/{card['job_id']}/respond", json=body)


def user_signs_in(page: Page, base: str) -> None:
    """What the person does in the window: e-mail, Next, password, Log in."""
    page.get_by_label("Email").fill(EMAIL)
    page.get_by_role("button", name="Next").click()
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Log in").click()
    page.wait_for_url(base + "/app")


def start(c: TestClient, site: AuthSite) -> str:
    r = c.post("/api/jobs", data={"url": site.base + "/"})
    assert r.status_code == 201
    return r.json()["state"]["job_id"]  # type: ignore[no-any-return]


def test_the_user_signs_in_in_a_window_and_the_job_goes_on(tmp_path: Path, site: AuthSite) -> None:
    windows = LoginWindows(headless=True)
    c = client_for(tmp_path, site, windows)
    try:
        job_id = start(c, site)
        card = waiting_card(c, job_id)
        assert card["login"]["login_url"] == site.base + "/login"

        opened = c.post(f"/api/jobs/{job_id}/login/browser")
        assert opened.status_code == 200 and opened.json()["status"] == "browser_open"
        assert c.get(f"/api/jobs/{job_id}/login/browser").json()["status"] == "browser_open"
        windows.run_in_window(job_id, lambda page: user_signs_in(page, site.base))

        assert answer(c, card).status_code == 200  # "Tôi đã đăng nhập xong"
        until(lambda: c.get(f"/api/jobs/{job_id}").json()["state"]["status"] == "done")
        directory = tmp_path / "jobs" / job_id
        assert OUTCOME[job_id + ":saved"]  # the session existed while the job ran ...
        assert not (directory / "storage_state.json").exists()  # ... and goes with the job
        assert OUTCOME[job_id].url == site.base + "/app"  # where the window ended
        assert windows.status(job_id) == "closed"  # the window was closed
        assert c.get(f"/api/jobs/{job_id}/files/storage_state.json").status_code == 404
    finally:
        c.__exit__(None, None, None)
        windows.shutdown()


def test_pressing_done_without_signing_in_keeps_the_card_with_a_reason(
    tmp_path: Path, site: AuthSite
) -> None:
    windows = LoginWindows(headless=True)
    c = client_for(tmp_path, site, windows)
    try:
        job_id = start(c, site)
        card = waiting_card(c, job_id)
        c.post(f"/api/jobs/{job_id}/login/browser")
        assert answer(c, card).status_code == 200  # nothing was typed in the window
        again = until(
            lambda: (
                (p := current_card(c, job_id))
                and p["interaction_id"] != card["interaction_id"]
                and p
            )
        )
        assert again["login"]["failure"] == "Chưa vào được trang bên trong, vui lòng thử lại."
        assert windows.status(job_id) == "closed"
        windows.shutdown()
        windows = LoginWindows(headless=True)  # a fresh window for the second try
        c.app.state.login_windows = windows  # type: ignore[attr-defined]
        c.post(f"/api/jobs/{job_id}/login/browser")
        windows.run_in_window(job_id, lambda page: user_signs_in(page, site.base))
        assert answer(c, again).status_code == 200
        until(lambda: c.get(f"/api/jobs/{job_id}").json()["state"]["status"] == "done")
    finally:
        c.__exit__(None, None, None)
        windows.shutdown()


def test_a_window_nobody_confirms_is_closed_and_the_user_is_told(
    tmp_path: Path, site: AuthSite
) -> None:
    windows = LoginWindows(headless=True, timeout_s=0.8)
    c = client_for(tmp_path, site, windows)
    try:
        job_id = start(c, site)
        card = waiting_card(c, job_id)
        c.post(f"/api/jobs/{job_id}/login/browser")
        until(lambda: windows.status(job_id) == "timeout")
        late = answer(c, card)
        assert late.status_code == 409 and "10 phút" in late.json()["detail"]
    finally:
        c.__exit__(None, None, None)
        windows.shutdown()


def test_cancelling_the_job_closes_the_window(tmp_path: Path, site: AuthSite) -> None:
    windows = LoginWindows(headless=True)
    c = client_for(tmp_path, site, windows)
    try:
        job_id = start(c, site)
        waiting_card(c, job_id)
        c.post(f"/api/jobs/{job_id}/login/browser")
        assert windows.status(job_id) == "browser_open"
        assert c.post(f"/api/jobs/{job_id}/cancel").status_code == 200
        assert windows.status(job_id) == "closed"
    finally:
        c.__exit__(None, None, None)
        windows.shutdown()


def test_opening_a_window_needs_a_job_that_waits_for_a_login(
    tmp_path: Path, site: AuthSite
) -> None:
    windows = LoginWindows(headless=True)
    c = client_for(tmp_path, site, windows)
    try:
        job_id = start(c, site)
        waiting_card(c, job_id)
        assert c.post("/api/jobs/jnope/login/browser").status_code == 404
        c.post(f"/api/jobs/{job_id}/cancel")
        until(lambda: c.get(f"/api/jobs/{job_id}").json()["state"]["status"] == "cancelled")
        assert c.post(f"/api/jobs/{job_id}/login/browser").status_code == 409
    finally:
        c.__exit__(None, None, None)
        windows.shutdown()
