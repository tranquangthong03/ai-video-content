"""The sign-in loop (aisoeasy.co): a session that passes the check but is thrown back to /login.

Findings of the live job (docs/login-acceptance/aisoeasy-loop.md): the check passed every time, the
app's start page was taken from the sign-in window (still showing /login), and the explorer treated
a link to /login as "session expired". Fast tests use a fake probe; the browser ones a local site.
"""

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from app.browser.auth_detect import LoginRequired
from app.browser.session import BrowserSession
from app.core.interaction import make_response
from app.explorer.mapper import Candidate, visit
from app.explorer.report import Report
from app.pipeline.frontend import ScriptedFrontend
from app.schemas.generated.interaction import InteractionRequest
from app.schemas.generated.user_response import UserResponse
from app.session.gate import RESULT_FILE, LoginGate, SessionCheck, verify_session
from tests.auth_site import AuthSite, running_site

HOME = "https://app.example.com/home"
LOGIN = "https://example.com/login"


class User(ScriptedFrontend):
    def __init__(self, replies: list[Callable[[InteractionRequest], UserResponse]]) -> None:
        super().__init__({}, Console(quiet=True))
        self.replies = list(replies)
        self.asked: list[InteractionRequest] = []

    def ask(self, request: InteractionRequest) -> UserResponse:
        self.asked.append(request)
        return self.replies.pop(0)(request)

    def reasons(self) -> list[str]:
        return [r.login.reason for r in self.asked if r.login]


def done(job: Path, window_url: str | None = None) -> Callable[..., UserResponse]:
    def reply(request: InteractionRequest) -> UserResponse:
        (job / "storage_state.json").write_text('{"cookies": [], "origins": []}', encoding="utf-8")
        if window_url:
            (job / RESULT_FILE).write_text(json.dumps({"final_url": window_url}), encoding="utf-8")
        return make_response(request, "login_done")

    return reply


def public(request: InteractionRequest) -> UserResponse:
    return make_response(request, "answer", answers={"login_method": "public"})


def landing_ok(_state: Path, _url: str) -> SessionCheck:
    return SessionCheck(True, HOME)  # the landing sends a signed-in visitor into the app


def refused(_state: Path, _url: str) -> SessionCheck:
    return SessionCheck(False, LOGIN)


def need(reason: str = "requested", target: str = "https://example.com/") -> LoginRequired:
    return LoginRequired(LOGIN, reason, target_url=target)


def make_gate(job: Path, user: User, probe: Callable[[Path, str], SessionCheck]) -> LoginGate:
    return LoginGate("j", job, user, probe=probe)


def test_the_start_page_is_where_the_check_ended_not_the_login_page_the_window_showed(
    tmp_path: Path,
) -> None:
    user = User([done(tmp_path, window_url=LOGIN)])
    got = make_gate(tmp_path, user, landing_ok).ask(need())
    assert got.url == HOME and not got.public


def test_the_check_opens_the_page_we_wanted_not_the_window_page(tmp_path: Path) -> None:
    opened: list[str] = []

    def probe(_s: Path, url: str) -> SessionCheck:
        opened.append(url)
        return SessionCheck(True, url)

    user = User([done(tmp_path, window_url="https://example.com/privacy")])
    got = make_gate(tmp_path, user, probe).ask(need("session_expired", "https://example.com/app"))
    assert opened == ["https://example.com/app"] and got.url == "https://example.com/app"


def test_a_verified_session_thrown_back_twice_is_explained_and_the_loop_ends(
    tmp_path: Path,
) -> None:
    user = User([done(tmp_path), done(tmp_path), public])
    g = make_gate(tmp_path, user, landing_ok)
    g.ask(need())  # first sign-in, verified
    g.ask(need("session_expired", LOGIN))  # bounced once: ask as usual
    got = g.ask(need("session_expired", LOGIN))  # bounced twice
    card = user.asked[-1].login
    assert card is not None and card.reason == "login_loop"
    assert "public" in card.methods and card.failure and LOGIN in card.failure
    assert card.hint and "tài khoản demo" in card.hint
    assert got.public and len(user.asked) == 3
    assert g.ask(need("session_expired")).public and len(user.asked) == 3  # never asked again


def test_two_failed_checks_in_a_row_end_in_the_explaining_card_not_a_third_question(
    tmp_path: Path,
) -> None:
    user = User([done(tmp_path), done(tmp_path), public])
    got = make_gate(tmp_path, user, refused).ask(need())
    assert user.reasons() == ["requested", "requested", "login_loop"] and got.public


def test_a_late_expiry_is_not_taken_for_a_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.session.gate as module

    user = User([done(tmp_path), done(tmp_path)])
    g = make_gate(tmp_path, user, landing_ok)
    g.ask(need())
    monkeypatch.setattr(module, "BOUNCE_WINDOW_S", -1)  # the check was long ago
    g.ask(need("session_expired"))
    assert user.reasons() == ["requested", "session_expired"]


# --- with a browser --------------------------------------------------------------------------


@pytest.fixture
def site() -> Iterator[AuthSite]:
    with running_site() as s:
        yield s


def stale_state(site: AuthSite, path: Path) -> Path:
    cookie = {"name": "sid", "value": "gone", "domain": "127.0.0.1", "path": "/", "expires": -1}
    path.write_text(json.dumps({"cookies": [cookie], "origins": []}), encoding="utf-8")
    return path


def test_a_link_to_the_login_page_is_skipped_not_taken_for_an_expired_session(
    site: AuthSite, tmp_path: Path
) -> None:
    site.mode = "one_step"  # the form shows its password field right away
    with BrowserSession(site.base, storage_state=stale_state(site, tmp_path / "s.json")) as s:
        context = s.new_context()
        page = context.new_page()
        report = Report(site.base)
        link = Candidate(site.base + "/login", "Log in", "nav", 1, 1.0)
        assert visit(page, link, 1, tmp_path, report, site.base, authenticated=True) is None
        start = Candidate(site.base + "/app", "app", "nav", 0, 1.0, origin="root")
        with pytest.raises(LoginRequired):  # the start page bouncing IS an expired session
            visit(page, start, 2, tmp_path, report, site.base, authenticated=True)
        context.close()


def test_a_sign_in_form_nobody_can_see_does_not_mean_signed_out(
    site: AuthSite, tmp_path: Path
) -> None:
    state = tmp_path / "s.json"
    state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    assert verify_session(state, site.base + "/hidden-form").ok


PUT_TOKEN = """() => new Promise((ok) => { const r = indexedDB.open('auth', 1);
  r.onupgradeneeded = () => r.result.createObjectStore('kv');
  r.onsuccess = () => { const tx = r.result.transaction('kv', 'readwrite');
    tx.objectStore('kv').put('tok-1', 'token'); tx.oncomplete = () => ok(true); }; })"""
GET_TOKEN = """() => new Promise((ok) => { const r = indexedDB.open('auth', 1);
  r.onsuccess = () => { const q = r.result.transaction('kv').objectStore('kv').get('token');
    q.onsuccess = () => ok(q.result); }; r.onerror = () => ok(null); })"""


def test_a_session_kept_in_indexeddb_survives_the_saved_state(
    site: AuthSite, tmp_path: Path
) -> None:
    """Supabase/Firebase keep tokens in IndexedDB: storage_state needs indexed_db=True for them."""
    from playwright.sync_api import sync_playwright

    state = tmp_path / "state.json"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        first = browser.new_context()
        page = first.new_page()
        page.goto(site.base + "/")
        page.evaluate(PUT_TOKEN)
        first.storage_state(path=str(state), indexed_db=True)
        first.close()
        second: Any = browser.new_context(storage_state=state)
        page = second.new_page()
        page.goto(site.base + "/")
        assert page.evaluate(GET_TOKEN) == "tok-1"
        browser.close()
