"""Verbs that commit data (the one list shared by the request guard, the goal check and hints).

Pure functions, vi + en, accent-insensitive. A "commit" control is a button or link whose text says
it stores, sends, orders or pays: the flow must stop before it unless the submit policy allows it.
"""

import re
import unicodedata

# whole words / phrases (matched after folding accents, lower case)
COMMIT_PHRASES = (
    "add to cart", "add to basket", "add to bag", "place order", "buy now", "pay now",
    "check out", "checkout", "purchase", "order now", "submit", "save", "apply", "confirm",
    "create", "send", "post", "publish", "register", "sign up", "subscribe", "book now",
    "upload", "invite", "delete", "remove",
    "them vao gio", "dat hang", "mua ngay", "thanh toan", "luu", "gui", "tao", "xac nhan",
    "dang ky", "dang bai", "dang tai", "dat cho", "dat lich", "xoa",
)  # fmt: skip


def fold(text: str) -> str:
    """Lower case without accents (đ -> d), spaces collapsed."""
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


COMMIT_RE = re.compile(r"\b(" + "|".join(re.escape(p) for p in COMMIT_PHRASES) + r")\b")


def commit_verb(text: str) -> str | None:
    """The commit verb/phrase a control's text contains, or None."""
    m = COMMIT_RE.search(fold(text))
    return m.group(1) if m else None


def is_commit_text(text: str) -> bool:
    return commit_verb(text) is not None
