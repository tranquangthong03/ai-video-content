import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page

from app.browser.auth_detect import (
    LoginRequired,
    detect_login,
    is_login_path,
    is_logout_url,
)
from app.browser.session import BrowserSession
from app.explorer.mapper import crawl
from app.explorer.report import Deadline, Report
from tests.auth_site import AuthSite, running_site
from tests.test_recorder import goto, loc, rec


@pytest.fixture(scope="module")
def site() -> Iterator[AuthSite]:  # shadows the static site: this module uses the sign-in one
    with running_site() as s:
        yield s


def state_file(tmp_path: Path, site: AuthSite, sid: str) -> Path:
    path = tmp_path / "storage_state.json"
    cookie = {"name": "sid", "value": sid, "domain": "127.0.0.1", "path": "/", "expires": -1}
    path.write_text(json.dumps({"cookies": [cookie], "origins": []}), encoding="utf-8")
    return path


def signal_for(session: BrowserSession, url: str):  # type: ignore[no-untyped-def]
    ctx = session.new_context()
    page: Page = ctx.new_page()
    response = page.goto(url)
    found = detect_login(page, url, response.status if response else None)
    ctx.close()
    return found


@pytest.fixture  # one Playwright at a time: no module-scoped browser next to the tests' own sessions
def anon(site: AuthSite) -> Iterator[BrowserSession]:
    with BrowserSession(site.base) as s:
        yield s


def test_paths_that_look_like_a_login_or_a_logout() -> None:
    for url in ("https://x.com/login", "https://x.com/sign-in/", "https://x.com/account/login",
                "https://x.com/auth", "https://x.com/dang-nhap", "https://x.com/đăng-nhập"):  # fmt: skip
        assert is_login_path(url), url
    assert not is_login_path("https://x.com/blog/login-tips-for-teams-5")
    for url in ("https://x.com/logout", "https://x.com/sign-out", "https://x.com/user/signout",
                "https://x.com/đăng-xuất"):  # fmt: skip
        assert is_logout_url(url), url
    assert not is_logout_url("https://x.com/app/blogout-party")


def test_a_redirect_to_the_login_page_is_detected(anon: BrowserSession, site: AuthSite) -> None:
    found = signal_for(anon, site.base + "/app")
    assert found is not None and found.reason == "redirect"
    assert found.login_url == site.base + "/login"


def test_a_visible_password_field_is_detected_wherever_it_is(
    anon: BrowserSession, site: AuthSite
) -> None:
    site.mode = "one_step"
    found = signal_for(anon, site.base + "/login")
    site.mode = "two_step"
    assert found is not None and found.reason == "password_field"


def test_a_401_on_the_document_is_detected(anon: BrowserSession, site: AuthSite) -> None:
    found = signal_for(anon, site.base + "/api/me")
    assert found is not None and found.reason == "http_status"


def test_a_public_landing_and_a_hidden_password_field_are_not_a_login(
    anon: BrowserSession, site: AuthSite
) -> None:
    assert signal_for(anon, site.base + "/") is None  # has <input type=password hidden>
    assert signal_for(anon, site.base + "/login?step=1") is None  # email step only


def test_a_signed_in_visitor_sees_no_signal(tmp_path: Path, site: AuthSite) -> None:
    sid = site.new_session()
    with BrowserSession(site.base, storage_state=state_file(tmp_path, site, sid)) as s:
        assert signal_for(s, site.base + "/app") is None


def crawl_from(session: BrowserSession, url: str, tmp_path: Path, authenticated: bool = False):  # type: ignore[no-untyped-def]
    ctx = session.new_context()
    try:
        return crawl(
            ctx.new_page(), ctx, url, tmp_path, Report(url), Deadline(60), max_pages=3,
            authenticated=authenticated,
        )  # fmt: skip
    finally:
        ctx.close()


def test_the_explorer_stops_when_the_start_page_needs_a_login(
    anon: BrowserSession, site: AuthSite, tmp_path: Path
) -> None:
    with pytest.raises(LoginRequired) as e:
        crawl_from(anon, site.base + "/app", tmp_path)
    assert e.value.login_url == site.base + "/login" and e.value.reason == "redirect"


def test_a_public_landing_is_explored_even_though_it_links_to_a_login(
    anon: BrowserSession, site: AuthSite, tmp_path: Path
) -> None:
    pages, _ = crawl_from(anon, site.base + "/", tmp_path)
    assert pages and pages[0].url.rstrip("/") == site.base


def test_an_expired_session_stops_the_explorer_with_session_expired(
    tmp_path: Path, site: AuthSite
) -> None:
    with BrowserSession(site.base, storage_state=state_file(tmp_path, site, "stale")) as s:
        with pytest.raises(LoginRequired) as e:
            crawl_from(s, site.base + "/app", tmp_path, authenticated=True)
    assert e.value.reason == "session_expired"


def test_a_valid_session_explores_the_app(tmp_path: Path, site: AuthSite) -> None:
    sid = site.new_session()
    with BrowserSession(site.base, storage_state=state_file(tmp_path, site, sid)) as s:
        pages, _ = crawl_from(s, site.base + "/app", tmp_path, authenticated=True)
    assert pages and pages[0].url.endswith("/app")


def test_the_recorder_stops_a_scene_when_the_session_has_expired(
    tmp_path: Path, site: AuthSite
) -> None:
    visual = {"mode": "recording", "actions": [goto(site.base, "/app")]}
    with BrowserSession(site.base, storage_state=state_file(tmp_path, site, "stale")) as s:
        with pytest.raises(LoginRequired) as e:
            rec(s, site.base, tmp_path / "out", visual)
    assert e.value.reason == "session_expired" and e.value.login_url.endswith("/login")


def test_the_recorder_records_a_signed_in_scene_normally(tmp_path: Path, site: AuthSite) -> None:
    sid = site.new_session()
    visual = {
        "mode": "recording",
        "actions": [goto(site.base, "/app"), {"do": "hover", "locator": loc("#create")}],
    }
    with BrowserSession(site.base, storage_state=state_file(tmp_path, site, sid)) as s:
        r = rec(s, site.base, tmp_path / "out", visual)
    assert r.kind == "recording" and r.warnings == []
