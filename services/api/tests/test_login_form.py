import random
from collections.abc import Iterator

import pytest

from app.browser.guard import RequestGuard, registrable
from app.browser.login import MESSAGES, perform_login
from app.browser.session import BrowserSession
from tests.auth_site import EMAIL, OTP, PASSWORD, AuthSite, running_site


@pytest.fixture
def site() -> Iterator[AuthSite]:
    with running_site() as s:
        yield s


def attempt(site: AuthSite, mode: str, username: str = EMAIL, password: str = PASSWORD):  # type: ignore[no-untyped-def]
    site.mode = mode
    with BrowserSession(site.base) as session:
        ctx = session.new_context()
        page = ctx.new_page()
        page.goto(site.base + "/login")
        result = perform_login(page, username, password, guard=session.guard, rng=random.Random(1))
        cookies = [c["name"] for c in ctx.cookies()]
        report = session.guard.report()
        ctx.close()
    return result, cookies, report


def test_a_one_step_form_signs_in(site: AuthSite) -> None:
    result, cookies, report = attempt(site, "one_step")
    assert result.ok and result.final_url == site.base + "/app" and "sid" in cookies
    assert report["allowed"]["login_post"] >= 1  # the form post was let through, and counted


def test_a_two_step_form_signs_in(site: AuthSite) -> None:
    result, cookies, _ = attempt(site, "two_step")
    assert result.ok and result.final_url == site.base + "/app" and "sid" in cookies
    assert site.posts == ["POST /login/identify", "POST /login/password"]


def test_a_wrong_password_is_reported_with_the_page_s_error(site: AuthSite) -> None:
    result, cookies, _ = attempt(site, "two_step", password="nope")
    assert not result.ok and result.failure == "wrong_credentials" and "sid" not in cookies
    assert "Sai thông tin" in result.message and "cửa sổ đăng nhập" in result.message


def test_an_unknown_account_stops_at_the_first_step(site: AuthSite) -> None:
    result, _, _ = attempt(site, "two_step", username="nobody@example.com")
    assert result.failure == "wrong_credentials" and site.posts == ["POST /login/identify"]


def test_a_one_time_code_is_a_two_factor_failure(site: AuthSite) -> None:
    result, cookies, _ = attempt(site, "otp")
    assert not result.ok and result.failure == "two_factor" and "sid" not in cookies
    assert OTP not in result.message and "2FA" in result.message


def test_a_captcha_is_never_attempted(site: AuthSite) -> None:
    result, cookies, _ = attempt(site, "captcha")
    assert result.failure == "captcha" and "sid" not in cookies and site.posts == []


def test_a_page_with_only_social_buttons_is_not_automated(site: AuthSite) -> None:
    result, _, _ = attempt(site, "social")
    assert result.failure == "third_party" and "bên thứ ba" in result.message


def test_a_page_without_any_form_says_so(site: AuthSite) -> None:
    site.mode = "two_step"
    with BrowserSession(site.base) as session:
        ctx = session.new_context()
        page = ctx.new_page()
        page.goto(site.base + "/")
        result = perform_login(page, EMAIL, PASSWORD, guard=session.guard)
        ctx.close()
    assert result.failure == "no_form" and result.message == MESSAGES["no_form"]


def test_outside_a_sign_in_the_guard_still_blocks_posts(site: AuthSite) -> None:
    site.mode = "one_step"
    with BrowserSession(site.base) as session:
        ctx = session.new_context()
        page = ctx.new_page()
        page.goto(site.base + "/login")
        page.get_by_label("Email address").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_timeout(500)
        blocked = session.guard.report()["blocked"]
        ctx.close()
    assert blocked.get("document_post") == 1 and site.posts == []  # the old rule is untouched


# --- which POSTs the sign-in may make ------------------------------------------------------------


def test_the_sign_in_may_post_to_the_site_and_to_known_auth_providers_only() -> None:
    guard = RequestGuard("https://app.example.com/")
    allowed = [
        "https://app.example.com/session",
        "https://www.example.com/api/login",
        "https://example.com/login",
        "https://auth.example.com/oauth/token",
        "https://accounts.example.com/signin",
        "https://acme.auth0.com/oauth/token",
        "https://xyz.clerk.accounts.dev/v1/client/sign_ins",
        "https://eu-west.auth.eu-west-1.amazoncognito.com/oauth2/token",
        "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword",
        "https://acme.okta.com/api/v1/authn",
        "https://abc.supabase.co/auth/v1/token",
        "https://acme.firebaseapp.com/__/auth/handler",
    ]
    refused = [
        "https://evil.com/collect",
        "https://abc.supabase.co/rest/v1/items",  # supabase only under /auth/
        "https://cdn.example.org/login",
        "https://shop.example.com.attacker.io/post",
        "https://tracker.example.com/pixel",  # a sibling subdomain that is not auth-like
        "https://clerk.example.dev/v1/client/sign_ins",  # looks like clerk, is not
    ]
    with guard.allow_login_posts():
        verdict = {u: guard.login_post_allowed(u) for u in allowed + refused}
    assert all(verdict[u] for u in allowed)
    assert not any(verdict[u] for u in refused)


def test_registrable_domains() -> None:
    assert registrable("app.example.com") == "example.com"
    assert registrable("login.example.com.vn") == "example.com.vn"
    assert registrable("example.co.uk") == "example.co.uk"


def test_outside_the_phase_a_post_is_decided_by_the_old_rules() -> None:
    guard = RequestGuard("https://example.com/")
    assert guard.decide("POST", "https://example.com/login", "xhr", "{}") == (
        "abort",
        "post_default",
    )
    with guard.allow_login_posts():
        assert (
            guard.decide("POST", "https://example.com/login", "document", None)[1] == "login_post"
        )
        guard.decide("POST", "https://evil.com/x", "xhr", "{}")
    assert guard.report()["login_phase"] == {
        "posts_allowed": {"example.com": 1},
        "hosts_refused": {"evil.com": 1},
    }
    assert guard.decide("POST", "https://example.com/login", "xhr", "{}")[0] == "abort"
