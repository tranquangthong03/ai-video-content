"""Does this page ask the visitor to sign in?

Three signals: a password field that is visible, a redirect to a login-looking path, an HTTP 401/403
on the document. LoginRequired carries what the web card needs to ask the user: where the login
page is and why we think so.
"""

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from playwright.sync_api import Page

LOGIN_PATH = re.compile(
    r"(^|/)(log-?in|sign-?in|signin|auth|account/login|đăng-?nhập|dang-?nhap)(/|$|\.)",
    re.IGNORECASE,
)
# a path that must never be visited on purpose after signing in
LOGOUT_PATH = re.compile(
    r"(^|/|[-_.])(log-?out|sign-?out|signout|đăng-?xuất|dang-?xuat)($|/|[-_.])", re.IGNORECASE
)

Reason = Literal["password_field", "redirect", "http_status", "session_expired"]


@dataclass(frozen=True)
class LoginSignal:
    reason: Reason
    login_url: str  # where the login page is (the page we landed on)


class LoginRequired(RuntimeError):
    """The page needs a signed-in visitor. Raised by the explorer and the recorder."""

    def __init__(self, login_url: str, reason: str, *, target_url: str = "") -> None:
        super().__init__(f"login required ({reason}) at {login_url}")
        self.login_url = login_url
        self.reason = reason
        self.target_url = target_url or login_url


def is_login_path(url: str) -> bool:
    return bool(LOGIN_PATH.search(urlparse(url).path or "/"))


def is_logout_url(url: str) -> bool:
    return bool(LOGOUT_PATH.search(urlparse(url).path or "/"))


def detect_login(page: Page, requested_url: str, status: int | None) -> LoginSignal | None:
    """The sign-in signal of the page we are on now, or None.

    requested_url is what we navigated to: landing on a login-looking path that we did not ask
    for is a redirect; a visible password field or a 401/403 count wherever they are.
    """
    here = page.url
    if status in (401, 403):
        return LoginSignal("http_status", here)
    try:
        password = page.locator("input[type=password]:visible").count() > 0
    except Exception:
        password = False
    if password:
        return LoginSignal("password_field", here)
    if is_login_path(here) and not is_login_path(requested_url):
        return LoginSignal("redirect", here)
    return None
