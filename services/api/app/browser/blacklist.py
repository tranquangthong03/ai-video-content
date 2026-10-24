"""Click safety shared by every module that drives a browser (explorer, recorder).
See CLAUDE.md "An toàn". The blacklist applies to elements that are clicked or hovered,
never to text that is typed into a field.

Matching is a case-insensitive substring test: it deliberately over-blocks (fail closed).
"""

import re
from collections.abc import Iterable
from urllib.parse import urlparse

# From CLAUDE.md: elements whose text/aria matches any of these are never clicked
BLACKLIST: tuple[str, ...] = (
    "xóa",
    "delete",
    "remove",
    "thanh toán",
    "pay",
    "checkout",
    "mua",
    "buy",
    "gửi",
    "send",
    "đăng xuất",
    "logout",
    "hủy tài khoản",
)

# Extra intents the verifier must never trigger (they write data or leave the page)
SUBMIT_INTENTS: tuple[str, ...] = (
    "save",
    "lưu",
    "submit",
    "đặt hàng",
    "place order",
    "order now",
    "sign out",
    "log out",
)

# href path segments that mean "destructive/account/payment" even if the link text looks harmless
BLOCKED_PATH = re.compile(
    r"/(logout|log-out|signout|sign-out|delete|remove|checkout|payment|payments|billing|cart)(/|$|\?)",
    re.I,
)


def matched_term(
    texts: Iterable[str | None],
    extra: tuple[str, ...] = (),
    ignore: Iterable[str] = (),
) -> str | None:
    """First blacklisted term found in any of the texts, else None.

    `ignore` holds texts the explorer typed itself (sample data such as "Mua sữa"): an element
    whose text is exactly one of them is data, not a control label, and is not matched.
    """
    skip = {s.strip().lower() for s in ignore}
    for text in texts:
        if not text:
            continue
        low = text.lower()
        if low.strip() in skip:
            continue
        for term in (*BLACKLIST, *extra):
            if term in low:
                return term
    return None


def is_blocked(*texts: str | None, strict: bool = False, ignore: Iterable[str] = ()) -> bool:
    """True when the element must not be clicked. strict=True also covers submit/save intents."""
    return matched_term(texts, SUBMIT_INTENTS if strict else (), ignore) is not None


def is_blocked_href(href: str | None) -> bool:
    return bool(href) and bool(BLOCKED_PATH.search(urlparse(href or "").path + "/"))
