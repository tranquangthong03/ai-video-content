"""Click safety shared by every module that drives a browser (explorer, recorder).
See CLAUDE.md "An toàn". The blacklist applies to elements that are clicked or hovered,
never to text that is typed into a field.

Matching of the core terms is a case-insensitive substring test: it deliberately over-blocks
(fail closed). The account actions below (invite, upgrade, revoke...) match as whole words /
phrases and only on interactive elements: a call to action such as "Mời bạn dùng thử" or a
heading "Upgrade your workflow" is not an invitation of people or a change of plan.
"""

import re
import unicodedata
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

# Actions of a signed-in account that reach other people, hand out access or change its plan.
# Whole words / phrases, and only for elements the visitor can operate (see matched_term).
_PEOPLE = (
    r"(?:thêm\s+)?(?:thành\s+viên|người\s+dùng|đồng\s+nghiệp|nhân\s+viên|bạn\s+bè|người\s+khác"
    r"|cộng\s+sự|quản\s+trị\s+viên)"
)
ACCOUNT_ACTIONS: dict[str, re.Pattern[str]] = {
    # "Invite member", "Invite" - not "Invite you to try"
    "invite": re.compile(
        r"(?<!\w)invite(?!\w)(?!\s+(?:you\b|to\s+(?:try|test|join\s+us|see)))", re.I
    ),
    # "Mời thành viên", "Mời" alone - not "Mời bạn dùng thử"
    "mời": re.compile(rf"(?<!\w)mời(?!\w)(?:\s+{_PEOPLE}|\s*$)", re.I),
    "share access": re.compile(r"(?<!\w)share\s+access(?!\w)", re.I),
    "chia sẻ quyền": re.compile(r"(?<!\w)chia\s+sẻ\s+quyền(?!\w)", re.I),
    "generate key": re.compile(r"(?<!\w)generate\s+(?:an?\s+)?(?:api\s+)?key(?!\w)", re.I),
    "tạo khóa": re.compile(r"(?<!\w)tạo\s+khóa(?!\w)", re.I),
    "revoke": re.compile(r"(?<!\w)revoke(?!\w)", re.I),
    "thu hồi": re.compile(r"(?<!\w)thu\s+hồi(?!\w)", re.I),
    "upgrade": re.compile(r"(?<!\w)upgrade(?!\w)", re.I),
    "nâng cấp": re.compile(r"(?<!\w)nâng\s+cấp(?!\w)", re.I),
}

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
    r"/(logout|log-out|signout|sign-out|sign_out|log_out|đăng-xuất|dang-xuat|delete|remove"
    r"|checkout|payment|payments|billing|cart)(/|$|\?)",
    re.I,
)


def matched_term(
    texts: Iterable[str | None],
    extra: tuple[str, ...] = (),
    ignore: Iterable[str] = (),
    interactive: bool = True,
) -> str | None:
    """First blacklisted term found in any of the texts, else None.

    `ignore` holds texts the explorer typed itself (sample data such as "Mua sữa"): an element
    whose text is exactly one of them is data, not a control label, and is not matched.
    `interactive=False` (a heading, a list item, a text field): only the core terms apply.
    """
    skip = {s.strip().lower() for s in ignore}
    for text in texts:
        if not text:
            continue
        low = unicodedata.normalize("NFC", text.lower())
        if low.strip() in skip:
            continue
        for term in (*BLACKLIST, *extra):
            if term in low:
                return term
        if interactive:
            for term, pattern in ACCOUNT_ACTIONS.items():
                if pattern.search(low):
                    return term
    return None


def is_blocked(
    *texts: str | None,
    strict: bool = False,
    ignore: Iterable[str] = (),
    interactive: bool = True,
) -> bool:
    """True when the element must not be clicked. strict=True also covers submit/save intents;
    interactive=False leaves out the account actions (see ACCOUNT_ACTIONS)."""
    return matched_term(texts, SUBMIT_INTENTS if strict else (), ignore, interactive) is not None


def is_blocked_href(href: str | None) -> bool:
    return bool(href) and bool(BLOCKED_PATH.search(urlparse(href or "").path + "/"))
