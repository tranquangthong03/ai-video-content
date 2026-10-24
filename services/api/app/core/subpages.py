"""Side pages a product video must not travel to: sign in, sign up, checkout, billing...

A viewer sees "Create account" for three seconds and learns nothing about the product; and these
pages are the same for every site, so they make different videos look alike. They are recognised by
the path of the URL or by the page title; features about them are dropped by the explorer, and
demo steps that lead into them are turned into a pointing scene on the page before.
"""

import re
from urllib.parse import urlparse

_WORDS = r"(login|signin|sign-in|register|signup|sign-up|auth|checkout|cart|billing|payment)"
_PATH = re.compile(rf"(^|/|[-_.]){_WORDS}($|/|[-_.])", re.IGNORECASE)
_ACCOUNT_CREATE = re.compile(r"account/(create|new)", re.IGNORECASE)
_TEXT = re.compile(
    r"\b(log\s?in|sign\s?in|sign\s?up|register|create (an )?account|checkout|billing"
    r"|payment|cart)\b"
    r"|đăng nhập|đăng ký|tạo tài khoản|thanh toán|giỏ hàng",
    re.IGNORECASE,
)


def is_subpage(url: str | None = None, title: str | None = None) -> bool:
    """True when the URL path or the page title names one of the side pages."""
    if url:
        path = urlparse(url).path or "/"
        if _PATH.search(path) or _ACCOUNT_CREATE.search(path):
            return True
    return bool(title and _TEXT.search(title))


def is_subpage_text(text: str | None) -> bool:
    """True when a feature name / description is about signing in, registering or paying."""
    return bool(text and _TEXT.search(text))
