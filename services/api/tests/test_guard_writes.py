import pytest

from app.browser.guard import MAX_WRITE_WINDOWS, RequestGuard, WritesNotAllowed
from app.core.shared_demo import is_shared_demo, shared_demo_sites

ROOT = "https://app.example.com/"


class Route:
    def __init__(self, method: str, url: str, rtype: str = "fetch") -> None:
        self.request = type("R", (), {"method": method, "url": url, "resource_type": rtype,
                                      "post_data": None})()  # fmt: skip
        self.result = ""

    def continue_(self) -> None:
        self.result = "continue"

    def fulfill(self, **_: object) -> None:
        self.result = "fake"

    def abort(self, _reason: str) -> None:
        self.result = "abort"


def send(guard: RequestGuard, method: str, url: str, rtype: str = "fetch") -> str:
    route = Route(method, url, rtype)
    guard.handle(route)
    return route.result


def test_writes_are_blocked_outside_the_window() -> None:
    guard = RequestGuard(ROOT)
    assert send(guard, "POST", ROOT + "api/todos") == "abort"
    assert send(guard, "PUT", ROOT + "api/todos/1") == "abort"
    with guard.allow_writes():
        pass
    assert send(guard, "POST", ROOT + "api/todos") == "abort"  # the window is closed again


def test_inside_the_window_own_domain_writes_pass_and_are_logged() -> None:
    guard = RequestGuard(ROOT)
    with guard.allow_writes():
        assert send(guard, "POST", ROOT + "api/leave") == "continue"
        assert send(guard, "PATCH", ROOT + "api/leave/3") == "continue"
        assert send(guard, "POST", ROOT + "leave/apply", "document") == "continue"  # a form submit
        assert send(guard, "POST", "https://other.example.org/api/x") == "abort"
        assert send(guard, "DELETE", ROOT + "api/leave/3") == "abort"
    report = guard.report()["writes"]
    assert report["windows"] == 1 and len(report["requests"]) == 3


@pytest.mark.parametrize(
    "path",
    ["api/users/1/delete", "api/checkout", "api/payment/charge", "api/invite", "api/messages/send",
     "api/mail", "api/billing", "logout"],
)  # fmt: skip
def test_destructive_payment_invite_and_send_paths_never_pass(path: str) -> None:
    guard = RequestGuard(ROOT)
    with guard.allow_writes():
        assert send(guard, "POST", ROOT + path) == "abort"
    assert guard.write_log == []


def test_at_most_two_windows_per_guard() -> None:
    guard = RequestGuard(ROOT)
    for _ in range(MAX_WRITE_WINDOWS):
        with guard.allow_writes():
            pass
    with pytest.raises(WritesNotAllowed), guard.allow_writes():
        pass


def test_a_shared_demo_site_never_opens_a_window() -> None:
    guard = RequestGuard("https://opensource-demo.orangehrmlive.com/web/index.php/dashboard")
    with pytest.raises(WritesNotAllowed, match="shared demo"), guard.allow_writes():
        pass
    assert send(guard, "POST", "https://opensource-demo.orangehrmlive.com/api/v2/leave") == "abort"


def test_the_shared_demo_list_is_configurable() -> None:
    env = {"SHARED_DEMO_SITES": "demo.shop.test, WWW.other.demo"}
    assert "demo.shop.test" in shared_demo_sites(env) and "other.demo" in shared_demo_sites(env)
    assert is_shared_demo("https://sub.demo.shop.test/x", env)
    assert is_shared_demo("https://opensource-demo.orangehrmlive.com/", {})
    assert not is_shared_demo("https://todomvc.com/", env)
    assert not is_shared_demo("https://notdemo.shop.test/", env)
