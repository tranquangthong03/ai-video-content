"""classify_write_intent: does a POST read or write, by the action that caused it, its path, its body."""

import json

import pytest

from app.browser.write_intent import action_trigger, body_intent, classify_write_intent, path_class
from app.core.commit_verbs import commit_verb, is_commit_text

API = "https://shop.example.com"
JSON = "application/json"
FORM = "application/x-www-form-urlencoded"


def verdict(url: str, body: object = None, *, trigger: str = "none", ctype: str = JSON) -> str:
    data = body if isinstance(body, str) or body is None else json.dumps(body)
    return classify_write_intent(url, data, content_type=ctype, trigger=trigger).verdict  # type: ignore[arg-type]


# (url, body, trigger, expected) - no site names: the kinds of API sites really use
CASES = [
    # --- the page loads / navigates: a post with an unguessable name is a read
    (f"{API}/api/x", {"id": "7"}, "page_load", "read"),
    (f"{API}/api/x", {"cat": "phone"}, "filter", "read"),
    (f"{API}/api/x", {"id": "7"}, "open_detail", "read"),
    (f"{API}/api/viewbasket", {"token": "abc"}, "navigate", "read"),
    # --- the same endpoint after pressing a commit button is a write
    (f"{API}/api/x", {"id": "7"}, "commit", "write"),
    (f"{API}/api/viewbasket", {"token": "abc"}, "commit", "write"),
    # --- no known action: words of the path decide, write verbs win
    (f"{API}/api/search", {"q": "lamp"}, "none", "read"),
    (f"{API}/api/tasks/list", {}, "none", "read"),
    (f"{API}/api/getItems", {"page": 2}, "none", "read"),
    (f"{API}/api/items/fetch", None, "none", "read"),
    (f"{API}/api/search/create", {"q": "lamp"}, "none", "write"),
    (f"{API}/api/addtocart", {"id": "7"}, "none", "write"),
    (f"{API}/api/deleteItem", {"id": "7"}, "none", "write"),
    (f"{API}/api/tasks", {"title": "x"}, "none", "unknown"),
    (f"{API}/api/x", {"id": "7"}, "none", "unknown"),
    (f"{API}/api/bycat", {"cat": "phone"}, "none", "unknown"),  # no word of the path says "read"
    (f"{API}/api/cart", {"id": "7"}, "none", "write"),  # a noun on its own is a write
    # --- a write verb in the path beats the action
    (f"{API}/api/addtocart", {"id": "7"}, "page_load", "write"),
    (f"{API}/api/order/create", {}, "navigate", "write"),
    (f"{API}/api/login", {"user": "a"}, "navigate", "write"),
    # --- body intent
    (f"{API}/api/search", {"q": "a", "email": "me@x.io"}, "none", "write"),
    (f"{API}/api/x", {"password": "p"}, "page_load", "write"),
    (f"{API}/api/x", {"qty": 3, "id": "7"}, "filter", "write"),
    (f"{API}/api/x", {"maxPrice": 30, "q": "a"}, "search", "read"),  # a range filter, not a price
    (f"{API}/api/x", {"amount": 30}, "filter", "write"),
    (f"{API}/api/x", {"action": "deleteUser"}, "navigate", "write"),
    (f"{API}/api/x", {"type": "query", "q": "a"}, "search", "read"),
    # --- GraphQL: query yes (unless a commit caused it), mutation no
    (f"{API}/graphql", {"query": "query Tasks { tasks { id } }"}, "none", "read"),
    (f"{API}/graphql", {"query": "{ tasks { id } }", "operationName": "Tasks"}, "none", "read"),
    (f"{API}/graphql", {"query": "mutation Add { addTask { id } }"}, "page_load", "write"),
    (f"{API}/graphql", {"query": "mutation Add { b }", "operationName": "Q"}, "none", "write"),
    (f"{API}/graphql", {"query": "query Tasks { tasks { id } }"}, "commit", "write"),
    (f"{API}/graphql", [{"query": "query A { a }"}, {"query": "mutation B { b }"}], "none", "write"),
    # --- JSON-RPC
    (f"{API}/rpc", {"jsonrpc": "2.0", "method": "getItems", "params": {}}, "none", "unknown"),
    (f"{API}/rpc", {"jsonrpc": "2.0", "method": "getItems", "params": {}}, "page_load", "read"),
    (f"{API}/rpc", {"jsonrpc": "2.0", "method": "deleteItem", "params": {"id": 1}}, "page_load", "write"),
    (f"{API}/rpc", {"jsonrpc": "2.0", "method": "item.update"}, "none", "write"),
    # --- search services
    (f"{API}/indexes/products/queries", {"requests": [{"indexName": "p", "params": "query=lamp"}]}, "none", "read"),
    (f"{API}/products/_search", {"query": {"match": {"title": "lamp"}}}, "none", "read"),
    (f"{API}/indexes/*/queries", {"requests": [{"params": "query=a"}]}, "search", "read"),
]  # fmt: skip


@pytest.mark.parametrize(("url", "body", "trigger", "expected"), CASES)
def test_classification(url: str, body: object, trigger: str, expected: str) -> None:
    assert verdict(url, body, trigger=trigger) == expected


def test_a_traditional_form_with_an_email_is_a_write() -> None:
    assert verdict(f"{API}/subscribe", "email=a%40b.io&name=x", ctype=FORM) == "write"
    assert verdict(f"{API}/x", "email=a%40b.io", trigger="navigate", ctype=FORM) == "write"
    assert verdict(f"{API}/api/x", "q=lamp&page=2", trigger="search", ctype=FORM) == "read"


def test_a_body_that_cannot_be_read_is_not_a_read() -> None:
    assert body_intent("\x00\x01binary", "application/octet-stream")[0] == "unclear"
    assert verdict(f"{API}/api/x", "\x00\x01binary", trigger="page_load", ctype="") == "unknown"
    assert verdict(f"{API}/api/search", "x" * 300_000, ctype="text/plain") == "unknown"
    assert body_intent("--b\r\ncontent", "multipart/form-data; boundary=b")[0] == "unclear"


def test_a_commit_stays_a_write_even_for_a_read_looking_path() -> None:
    assert verdict(f"{API}/api/search", {"q": "a"}, trigger="commit") == "write"


def test_path_words() -> None:
    assert path_class("/api/viewcart") == "read"
    assert path_class("/api/addtocart") == "write"
    assert path_class("/api/x") == "neutral"
    assert path_class("/api/getUserList") == "read"
    assert path_class("/api/saveDraft") == "write"
    assert path_class("/api/orders") == "write"
    assert path_class("/api/getOrders") == "read"


def test_what_a_browser_action_is() -> None:
    assert action_trigger("click", "button", "Add to cart") == "commit"
    assert action_trigger("click", "button", "Lưu") == "commit"
    assert action_trigger("click", "button", "Save", submit_like=True) == "commit"
    assert action_trigger("click", "link", "Laptops") == "navigate"
    assert action_trigger("navigate", "menuitem", "Reports") == "navigate"
    assert action_trigger("click", "button", "Filter") == "click"  # judged by the request itself
    assert action_trigger("type", "searchbox", "Q") == "search"
    assert action_trigger("type", "textbox", "Search products") == "search"
    assert action_trigger("type", "textbox", "First name") == "type"
    assert action_trigger("select", "combobox", "Country") == "click"
    assert action_trigger("scroll") == "page_load"


def test_commit_verbs_vi_and_en() -> None:
    for text in (
        "Add to cart",
        "THÊM VÀO GIỎ",
        "Đặt hàng",
        "Place order",
        "Lưu",
        "Gửi",
        "Save changes",
    ):
        assert is_commit_text(text), text
    for text in ("Laptops", "Xem chi tiết", "Home", "Product", "Giỏ hàng"):
        assert not is_commit_text(text), text
    assert commit_verb("Please Check out now") == "check out"
