import pytest

from app.browser.blacklist import is_blocked, is_blocked_href, matched_term
from app.browser.guard import RequestGuard

GUARD = RequestGuard("https://app.example.com")


@pytest.mark.parametrize(
    "text",
    ["Delete task", "Xóa", "Remove item", "Thanh toán ngay", "Pay now", "Checkout", "Mua ngay",
     "Buy plan", "Gửi", "Send message", "Đăng xuất", "Logout", "Hủy tài khoản", "DELETE"],
)  # fmt: skip
def test_blacklist_terms_block(text: str) -> None:
    assert is_blocked(text)


def test_benign_text_is_not_blocked_but_submit_intents_are_strict_only() -> None:
    assert not is_blocked("New task", "Tìm công việc")
    assert not is_blocked("Save")  # not in the CLAUDE.md blacklist...
    assert is_blocked("Save", strict=True)  # ...but the verifier refuses it
    assert is_blocked("Lưu thay đổi", strict=True)
    assert matched_term([None, "", "Place order"], ("place order",)) == "place order"


def test_blocked_href() -> None:
    assert is_blocked_href("https://x.com/logout")
    assert is_blocked_href("/account/delete?x=1")
    assert is_blocked_href("/checkout/")
    assert not is_blocked_href("/features")
    assert not is_blocked_href(None)


def decide(method: str, url: str, rtype: str = "fetch", body: str | None = None) -> tuple[str, str]:
    return GUARD.decide(method, url, rtype, body)


def test_guard_get_and_always_blocked_methods() -> None:
    assert decide("GET", "https://app.example.com/x") == ("continue", "read")
    for method in ("PUT", "PATCH", "DELETE"):
        assert decide(method, "https://app.example.com/api/search")[0] == "abort"


def test_guard_document_post_is_always_blocked() -> None:
    assert decide("POST", "https://app.example.com/search", "document") == (
        "abort",
        "document_post",
    )


def test_guard_graphql_query_allowed_mutation_blocked() -> None:
    url = "https://app.example.com/api"
    query = '{"query": "query Tasks { tasks { id } }"}'
    mutation = '{"query": "mutation Add { addTask { id } }"}'
    assert decide("POST", url, body=query) == ("continue", "graphql_query")
    assert decide("POST", url, body='{"query": "{ tasks { id } }"}')[0] == "continue"
    assert decide("POST", url, body=mutation)[0] == "abort"
    # operationName does not rescue a body that contains a mutation
    both = '{"operationName": "Add", "query": "query Q { a } mutation Add { b }"}'
    assert decide("POST", url, body=both)[0] == "abort"
    assert (
        decide("POST", url, body='[{"query": "query A { a }"}, {"query": "mutation B { b }"}]')[0]
        == "abort"
    )


def test_guard_telemetry_is_faked_not_sent() -> None:
    assert decide("POST", "https://www.google-analytics.com/collect") == ("fake_204", "telemetry")
    assert decide("POST", "https://o123.ingest.sentry.io/api/1/envelope/") == (
        "fake_204",
        "telemetry",
    )
    # a telemetry-looking host that is the site's own domain is not exempt
    own = RequestGuard("https://sentry.io")
    assert own.decide("POST", "https://sentry.io/api/create", "fetch", None)[0] == "abort"


def test_guard_read_like_paths() -> None:
    assert decide("POST", "https://app.example.com/api/search")[0] == "continue"
    assert decide("POST", "https://app.example.com/api/tasks/list")[0] == "continue"
    assert decide("POST", "https://app.example.com/api/search/create")[0] == "abort"
    assert decide("POST", "https://app.example.com/api/tasks")[0] == "abort"


def test_guard_report_counts_and_first_blocked_urls() -> None:
    guard = RequestGuard("https://app.example.com")

    class Req:
        def __init__(self, method: str, url: str) -> None:
            self.method, self.url, self.resource_type, self.post_data = method, url, "fetch", None

    class Route:
        def __init__(self, request: Req) -> None:
            self.request = request

        def continue_(self) -> None: ...
        def abort(self, _: str) -> None: ...
        def fulfill(self, **_: object) -> None: ...

    for i in range(12):
        guard.handle(Route(Req("DELETE", f"https://app.example.com/api/{i}")))
    guard.handle(Route(Req("POST", "https://app.example.com/api/search")))
    guard.handle(Route(Req("POST", "https://www.google-analytics.com/collect")))
    guard.handle(Route(Req("GET", "https://app.example.com/")))  # not counted
    report = guard.report()
    assert report["blocked"] == {"method_delete": 12}
    assert report["allowed"] == {"read_path": 1}
    assert report["faked_204"] == {"telemetry": 1}
    assert len(report["first_blocked_urls"]) == 10
