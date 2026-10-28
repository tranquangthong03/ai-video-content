"""Does a POST read or write? (request guard, rules shared by every site)

Order of the decision (classify_write_intent):
  a. the browser action that caused the request commits data (its control's text is a commit
     verb) -> write, whatever the path is called
  b. the action only loads / navigates / filters / searches / opens a detail, the body shows no
     write intent and the path has no write verb -> read (paths with unguessable names pass here)
  c. no known action: the path's words and the body decide; write verbs beat read verbs; what is
     left is unknown (blocked like a write)
A body with write intent (GraphQL mutation, a write verb as operation/method/action, personal or
transaction fields, a form with an e-mail) is a write in every case.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import parse_qsl, urlparse

Verdict = Literal["read", "write", "unknown"]
Trigger = Literal[
    "page_load", "navigate", "filter", "search", "open_detail", "type", "click", "commit", "none"
]
READ_TRIGGERS = ("page_load", "navigate", "filter", "search", "open_detail")
MAX_BODY_CHARS = 256_000

# verbs that change data: matched as a word, a prefix of a joined word (addtocart) or, from four
# letters, inside one (savedraft)
WRITE_VERBS = (
    "create", "insert", "update", "edit", "delete", "remove", "destroy", "save", "submit",
    "upload", "invite", "subscribe", "register", "signup", "login", "logout", "signin", "checkout",
    "purchase", "add", "pay", "send", "like", "vote", "mutation", "mutate", "publish", "book",
)  # fmt: skip
# nouns that mean a write only when no read verb goes with them ("viewcart" reads, "cart" writes)
WRITE_NOUNS = ("cart", "order", "payment", "comment", "basket", "booking")
READ_VERBS = (
    "view", "get", "list", "search", "query", "queries", "find", "fetch", "load", "lookup",
    "read", "show", "browse", "suggest", "autocomplete", "filter", "graphql",
)  # fmt: skip
READ_WORDS = ("detail", "details", "page", "feed", "pages", "items", "results")  # whole words only

OP_KEYS = {"operationname", "method", "action", "op", "type", "cmd", "command", "mutation"}
PERSONAL_WORDS = {
    "password", "passwd", "pwd", "email", "phone", "mobile", "address", "card", "cardnumber",
    "cvv", "cvc", "iban", "qty", "quantity", "amount", "price", "total",
}  # fmt: skip
RANGE_WORDS = {"min", "max", "from", "to", "lt", "gt", "lte", "gte"}  # price range filters


@dataclass(frozen=True)
class Intent:
    verdict: Verdict
    reason: str


def words(text: str) -> list[str]:
    """Lower-case words of a path / key / value; camelCase and separators split."""
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    return [w for w in re.split(r"[^A-Za-z0-9]+", text.lower()) if w]


def _has(token: str, verbs: tuple[str, ...]) -> bool:
    return any(token == v or token.startswith(v) or (len(v) >= 4 and v in token) for v in verbs)


def path_class(path: str) -> Literal["write", "read", "neutral"]:
    tokens = words(path)
    if any(_has(t, WRITE_VERBS) for t in tokens):
        return "write"
    read = any(_has_prefix(t, READ_VERBS) or t in READ_WORDS for t in tokens)
    if any(_has(t, WRITE_NOUNS) for t in tokens) and not read:
        return "write"
    return "read" if read else "neutral"


def _has_prefix(token: str, verbs: tuple[str, ...]) -> bool:
    return any(token == v or token.startswith(v) for v in verbs)


def _key_is_personal(key: str) -> bool:
    toks = words(key)
    return any(t in PERSONAL_WORDS for t in toks) and not any(t in RANGE_WORDS for t in toks)


def _value_is_write(value: Any) -> bool:
    return isinstance(value, str) and len(value) < 80 and any(
        _has(t, WRITE_VERBS) for t in words(value)
    )  # fmt: skip


def _scan(node: Any, depth: int = 0) -> bool:
    """True when the JSON shows write intent."""
    if depth > 4:
        return False
    if isinstance(node, dict):
        for key, value in node.items():
            k = str(key)
            if _key_is_personal(k):
                return True
            if k.lower() in OP_KEYS and _value_is_write(value):
                return True
            if _scan(value, depth + 1):
                return True
    elif isinstance(node, list):
        return any(_scan(v, depth + 1) for v in node[:50])
    return False


def graphql_kind(node: Any) -> Literal["query", "mutation", "none"]:
    items = node if isinstance(node, list) else [node]
    if not items:
        return "none"
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("query"), str):
            return "none"
        text = item["query"].lstrip()
        if text.startswith(("mutation", "subscription")) or re.search(r"\bmutation\b", text):
            return "mutation"
    return "query"


def body_intent(
    post_data: str | None, content_type: str = ""
) -> tuple[Literal["write", "clean", "unclear"], Any]:
    """('write' | 'clean' | 'unclear', parsed JSON or None). An empty body is clean."""
    if not post_data:
        return "clean", None
    if len(post_data) > MAX_BODY_CHARS:
        return "unclear", None
    ctype = content_type.lower()
    if "multipart" in ctype:
        return "unclear", None
    stripped = post_data.lstrip()
    if "json" in ctype or stripped[:1] in "{[":
        try:
            body = json.loads(post_data)
        except ValueError:
            return "unclear", None
        return ("write" if _scan(body) else "clean"), body
    if "x-www-form-urlencoded" in ctype or "=" in post_data:
        pairs = parse_qsl(post_data, keep_blank_values=True)
        data = {k: v for k, v in pairs}
        return ("write" if _scan(data) else "clean"), None
    return "unclear", None


def classify_write_intent(
    url: str,
    post_data: str | None = None,
    *,
    content_type: str = "",
    trigger: Trigger = "none",
) -> Intent:
    """Intent of one POST (see the module docstring for the order of the rules)."""
    body, parsed = body_intent(post_data, content_type)
    gql = graphql_kind(parsed) if parsed is not None else "none"
    if gql == "mutation":
        return Intent("write", "graphql_mutation")
    if gql == "query" and trigger != "commit":
        return Intent("read", "graphql_query")
    if trigger == "commit":
        return Intent("write", "commit_action")
    if body == "write":
        return Intent("write", "body_write_intent")
    path = urlparse(url).path
    klass = path_class(path)
    if klass == "write":
        return Intent("write", "path_write_word")
    if trigger in READ_TRIGGERS and body == "clean":
        return Intent("read", f"{trigger}_action")
    if klass == "read" and body == "clean":
        return Intent("read", "path_read_word")
    return Intent("unknown", "no_evidence")


NAV_ROLES = {"link", "tab", "menuitem", "menuitemradio", "treeitem"}


def action_trigger(
    do: str, role: str = "", name: str = "", *, submit_like: bool = False
) -> Trigger:
    """The trigger kind of one browser action (what the guard is told before it runs).

    Only controls that move to other content count as reads (links, tabs, menu entries) and a
    search box being typed in; everything else is judged by the request itself (rule c).
    """
    from app.core.commit_verbs import is_commit_text

    if do == "scroll":
        return "page_load"  # lazy loading
    if do in ("goto", "navigate") and not name:
        return "navigate"
    if do in ("click", "navigate", "stop_before_submit"):
        if submit_like or is_commit_text(name):
            return "commit"
        return "navigate" if role in NAV_ROLES else "click"
    if do == "type":
        is_search = role == "searchbox" or re.search(r"search|tìm|tim kiem", name, re.I)
        return "search" if is_search else "type"
    return "click" if do in ("select", "check", "pick_date", "upload") else "none"
