"""Way B: sign in with a demo account, like a person would.

Finds the identity field, the password field and the submit button of a login form (one step:
both on the page; two steps: identity, Next, then password), types, submits, and says what came
of it. A failure is classified so the user gets a useful hint: wrong credentials, a captcha, a
second factor, a "sign in with Google" only page, or no form at all.

The sign-in's own POSTs are let through by the request guard for the duration (allow_login_posts).
Credentials are only ever passed in as arguments: nothing here logs or stores them.
"""

import random
import re
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Literal

from playwright.sync_api import Locator, Page

from app.browser.auth_detect import is_login_path
from app.browser.blacklist import is_blocked
from app.browser.guard import RequestGuard
from app.browser.page_utils import CAPTCHA_FRAMES, dismiss_cookie_banner, wait_for_settle

Failure = Literal["wrong_credentials", "captcha", "two_factor", "no_form", "third_party"]

IDENTITY_WORDS = re.compile(
    r"e-?mail|user|login|username|account|identifier|tài khoản|tên đăng", re.I
)
OTP_WORDS = re.compile(
    r"one-time-code|otp|verification|verify|2fa|authenticator|passcode|mã xác|security code", re.I
)
SUBMIT_TEXT = re.compile(
    r"^\s*(log\s?in|sign\s?in|login|signin|continue|next|submit|đăng nhập|tiếp tục|tiếp theo)\s*$",
    re.I,
)
SOCIAL_TEXT = re.compile(
    r"(sign\s?in|log\s?in|continue|đăng nhập|tiếp tục)\s*(with|via|bằng|qua)\s*"
    r"(google|microsoft|github|apple|facebook|linkedin|sso)",
    re.I,
)
ERROR_SELECTOR = (
    "[role=alert], [aria-live=assertive], .error, .alert, [class*=error i], [class*=invalid i]"
)

MESSAGES: dict[str, str] = {
    "wrong_credentials": "Sai thông tin đăng nhập (trang báo lỗi). Kiểm tra lại tài khoản demo, "
    "hoặc dùng «Mở cửa sổ đăng nhập».",
    "captcha": "Trang yêu cầu xác minh captcha nên không đăng nhập tự động được. "
    "Hãy dùng «Mở cửa sổ đăng nhập».",
    "two_factor": "Trang yêu cầu mã xác thực (2FA/OTP) nên không đăng nhập tự động được. "
    "Hãy dùng «Mở cửa sổ đăng nhập».",
    "no_form": "Không tìm thấy form đăng nhập trên trang này. Hãy kiểm tra địa chỉ trang đăng nhập "
    "hoặc dùng «Mở cửa sổ đăng nhập».",
    "third_party": "Đăng nhập qua tài khoản bên thứ ba — vui lòng dùng cửa sổ đăng nhập.",
}


@dataclass
class LoginAttempt:
    ok: bool
    final_url: str
    failure: Failure | None = None

    @property
    def message(self) -> str:
        return MESSAGES[self.failure] if self.failure else ""


# --- finding things ---------------------------------------------------------------------------


def first_visible(page: Page, selector: str) -> Locator | None:
    loc = page.locator(selector)
    try:
        for i in range(min(loc.count(), 8)):
            item = loc.nth(i)
            if item.is_visible():
                return item
    except Exception:
        return None
    return None


def hints_of(page: Page, field: Locator) -> str:
    """name, id, autocomplete, placeholder, aria-label and the label text of a field, joined."""
    try:
        return str(
            field.evaluate(
                """(el) => {
                  const label = el.labels && el.labels[0] ? el.labels[0].innerText : '';
                  return [el.name, el.id, el.autocomplete, el.placeholder,
                          el.getAttribute('aria-label'), label].join(' ');
                }"""
            )
        )
    except Exception:
        return ""


def find_identity(page: Page) -> Locator | None:
    """The e-mail / username field: type=email, a telling name/id/label, else the first text one."""
    email = first_visible(page, "input[type=email]")
    if email is not None:
        return email
    loc = page.locator("input:not([type=password]):not([type=hidden]):not([type=checkbox])")
    candidates: list[Locator] = []
    try:
        for i in range(min(loc.count(), 10)):
            item = loc.nth(i)
            kind = (item.get_attribute("type") or "text").lower()
            if item.is_visible() and kind in ("text", "tel", "email", ""):
                candidates.append(item)
    except Exception:
        return None
    for item in candidates:
        hints = hints_of(page, item)
        if IDENTITY_WORDS.search(hints) and not OTP_WORDS.search(hints):
            return item
    return next((c for c in candidates if not OTP_WORDS.search(hints_of(page, c))), None)


def find_otp(page: Page) -> bool:
    loc = page.locator("input:not([type=password]):not([type=hidden])")
    try:
        for i in range(min(loc.count(), 10)):
            item = loc.nth(i)
            if item.is_visible() and OTP_WORDS.search(hints_of(page, item)):
                return True
    except Exception:
        return False
    return False


def find_submit(page: Page, near: Locator) -> Locator | None:
    """The submit button of the form the field is in (else any button that says log in / next)."""
    try:
        form = near.locator("xpath=ancestor::form[1]")
        scope = form if form.count() else page.locator("body")
    except Exception:
        scope = page.locator("body")
    explicit = scope.locator("button[type=submit], input[type=submit], button:not([type])")
    try:
        for i in range(min(explicit.count(), 6)):
            item = explicit.nth(i)
            if item.is_visible() and not is_blocked(item.inner_text(timeout=500)):
                return item
    except Exception:
        pass
    for role in ("button", "link"):
        try:
            item = scope.get_by_role(role, name=SUBMIT_TEXT).first  # type: ignore[arg-type]
            if item.count() and item.is_visible():
                return item
        except Exception:
            continue
    return None


def has_social_only(page: Page) -> bool:
    for role in ("button", "link"):
        try:
            if page.get_by_role(role, name=SOCIAL_TEXT).count() > 0:  # type: ignore[arg-type]
                return True
        except Exception:
            continue
    return False


def has_captcha(page: Page) -> bool:
    return any(any(k in (f.url or "") for k in CAPTCHA_FRAMES) for f in page.frames)


def form_error(page: Page) -> bool:
    try:
        loc = page.locator(ERROR_SELECTOR)
        for i in range(min(loc.count(), 6)):
            item = loc.nth(i)
            if item.is_visible() and item.inner_text(timeout=500).strip():
                return True
    except Exception:
        return False
    return False


# --- doing it ---------------------------------------------------------------------------------


def type_like_a_person(field: Locator, text: str, rng: random.Random) -> None:
    field.click()
    field.fill("")
    field.press_sequentially(text, delay=rng.randint(45, 90))


def submit(page: Page, field: Locator) -> None:
    button = find_submit(page, field)
    if button is not None:
        button.click(timeout=4000)
    else:
        field.press("Enter")
    wait_for_settle(page, timeout=5000)


def signed_in(page: Page) -> bool:
    try:
        password = page.locator("input[type=password]:visible").count() > 0
    except Exception:
        password = True
    return not password and not is_login_path(page.url) and not find_otp(page)


def wait_for_outcome(page: Page, timeout_ms: int = 10_000) -> None:
    """After submitting: single-page sites change the URL a little later, so wait until the page
    is signed in, shows an error, asks for a code or a captcha (or the time is up)."""
    waited = 0
    while waited < timeout_ms:
        if signed_in(page) or find_otp(page) or has_captcha(page) or form_error(page):
            return
        page.wait_for_timeout(300)
        waited += 300


def classify_failure(page: Page) -> Failure:
    if has_captcha(page):
        return "captcha"
    if find_otp(page):
        return "two_factor"
    return "wrong_credentials"


def perform_login(
    page: Page,
    username: str,
    password: str,
    *,
    guard: RequestGuard | None = None,
    rng: random.Random | None = None,
) -> LoginAttempt:
    """Sign in on the page that is open now (the login page). Never raises for a failed login."""
    rng = rng or random.Random()
    with guard.allow_login_posts() if guard is not None else nullcontext():
        try:
            return _login(page, username, password, rng)
        except Exception:
            return LoginAttempt(False, page.url, "no_form")


def _login(page: Page, username: str, password: str, rng: random.Random) -> LoginAttempt:
    dismiss_cookie_banner(page)
    wait_for_settle(page, timeout=3000)
    if has_captcha(page):
        return LoginAttempt(False, page.url, "captcha")
    identity = find_identity(page)
    pw = first_visible(page, "input[type=password]")
    if identity is None and pw is None:
        failure: Failure = "third_party" if has_social_only(page) else "no_form"
        return LoginAttempt(False, page.url, failure)

    if identity is not None:
        type_like_a_person(identity, username, rng)
    if pw is None:  # two steps: identity, Next, then the password
        submit(page, identity)  # type: ignore[arg-type]
        if form_error(page) and first_visible(page, "input[type=password]") is None:
            return LoginAttempt(False, page.url, "wrong_credentials")
        if has_captcha(page):
            return LoginAttempt(False, page.url, "captcha")
        for _ in range(10):  # the password field may appear after a short animation
            pw = first_visible(page, "input[type=password]")
            if pw is not None:
                break
            page.wait_for_timeout(300)
        if pw is None:
            return LoginAttempt(False, page.url, classify_failure(page))
    type_like_a_person(pw, password, rng)
    submit(page, pw)
    wait_for_outcome(page)
    if signed_in(page):
        return LoginAttempt(True, page.url)
    return LoginAttempt(False, page.url, classify_failure(page))
