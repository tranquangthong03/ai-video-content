"""app/browser: locate fallbacks, safety on the resolved element, Enter policy, URL helpers."""

import pytest
from playwright.sync_api import Page

from app.browser.enter_policy import enter_decision
from app.browser.guard import RequestGuard
from app.browser.locate import (
    ElementInfo,
    FormInfo,
    Unsafe,
    check_clickable,
    check_typeable,
    resolve,
)
from app.browser.session import BrowserSession
from app.browser.urls import anchor_of, in_scope, path_prefix
from app.schemas.generated.locator import Bbox, LocatorSpec

# --- urls ---------------------------------------------------------------------------------------


def test_path_prefix_and_scope() -> None:
    assert path_prefix("https://ex.com/examples/react/dist/") == "/examples/react/dist"
    assert path_prefix("https://ex.com/") is None
    assert path_prefix("https://ex.com") is None
    root = "https://ex.com/examples/react/dist"
    prefix = "/examples/react/dist"
    assert in_scope("https://ex.com/examples/react/dist", root, prefix)
    assert in_scope("https://ex.com/examples/react/dist/sub/page", root, prefix)
    assert not in_scope("https://ex.com/examples/react/distribution", root, prefix)
    assert not in_scope("https://ex.com/", root, prefix)
    assert not in_scope("https://other.com/examples/react/dist", root, prefix)
    assert in_scope("https://ex.com/anything", "https://ex.com", None)  # no prefix: whole domain
    assert in_scope("https://www.ex.com/x", "https://ex.com", None)  # www is the same site


def test_anchor_of_ignores_hash_routes() -> None:
    assert anchor_of("https://ex.com/#pricing") == "pricing"
    assert anchor_of("https://ex.com/#/active") is None
    assert anchor_of("https://ex.com/#!/x") is None
    assert anchor_of("https://ex.com/page") is None


# --- Enter policy -------------------------------------------------------------------------------


def info(
    *,
    in_form: bool = False,
    form: FormInfo | None = None,
    input_type: str = "text",
    texts: list[str] | None = None,
    is_text_input: bool = True,
) -> ElementInfo:
    return ElementInfo(
        tag="input", texts=texts or ["Add item"], href=None, input_type=input_type, button_type=None,
        in_form=in_form, form=form, is_text_input=is_text_input, text="",
    )  # fmt: skip


PAGE = "https://ex.com/notes"


def form(
    method: str = "get", action: str = PAGE, inputs: int = 1, sensitive: bool = False
) -> FormInfo:
    return FormInfo(method=method, action=action, text_inputs=inputs, sensitive=sensitive)


@pytest.mark.parametrize(
    ("element", "allowed", "reason"),
    [
        (info(), True, "ok"),  # a lone input outside any form
        (info(in_form=True, form=form("get", "https://ex.com/search")), True, "ok"),
        (info(in_form=True, form=form("post", PAGE)), True, "ok"),  # posts to its own page
        (
            info(in_form=True, form=form("post", "https://ex.com/submit")),
            False,
            "form_posts_to_other_path",
        ),
        (
            info(in_form=True, form=form("get", "https://evil.com/")),
            False,
            "form_action_other_site",
        ),
        (info(in_form=True, form=form(inputs=2)), False, "form_has_2_text_inputs"),
        (info(in_form=True, form=form(sensitive=True)), False, "form_has_sensitive_input"),
        (info(input_type="password"), False, "password_field"),
        (info(texts=["Send message"]), False, "blacklisted_field"),
        (info(is_text_input=False), False, "not_a_text_input"),
    ],
)
def test_strict_enter_policy(element: ElementInfo, allowed: bool, reason: str) -> None:
    assert enter_decision(element, PAGE, guard_on=True, policy="strict") == (allowed, reason)


def test_enter_needs_the_guard_in_every_policy() -> None:
    assert enter_decision(info(), PAGE, guard_on=False, policy="strict") == (False, "guard_off")
    assert enter_decision(info(), PAGE, guard_on=False, policy="relaxed") == (False, "guard_off")


def test_relaxed_policy_allows_forms_but_never_passwords_or_blacklisted_fields() -> None:
    risky = info(in_form=True, form=form("post", "https://ex.com/submit", inputs=3, sensitive=True))
    assert enter_decision(risky, PAGE, guard_on=True, policy="relaxed") == (True, "ok")
    assert (
        enter_decision(info(input_type="password"), PAGE, guard_on=True, policy="relaxed")[0]
        is False
    )
    assert enter_decision(info(texts=["Gửi"]), PAGE, guard_on=True, policy="relaxed")[0] is False


# --- safety on the resolved element -------------------------------------------------------------


def element(**kw: object) -> ElementInfo:
    base: dict[str, object] = {
        "tag": "button", "texts": ["Open"], "href": None, "input_type": None, "button_type": None,
        "in_form": False, "form": None, "is_text_input": False, "text": "Open",
    }  # fmt: skip
    return ElementInfo(**{**base, **kw})  # type: ignore[arg-type]


def test_check_clickable_reasons() -> None:
    root = "https://ex.com"
    check_clickable(element(), root)  # fine
    for kw, reason in [
        ({"texts": ["Delete task"]}, "blacklist"),
        ({"texts": ["Save changes"]}, "blacklist"),  # submit intents too (strict)
        ({"tag": "a", "href": "https://ex.com/logout"}, "blacklist"),
        ({"in_form": True, "button_type": "submit"}, "blacklist"),
        ({"tag": "a", "href": "https://other.com/x"}, "leaves_site"),
    ]:
        with pytest.raises(Unsafe) as err:
            check_clickable(element(**kw), root)
        assert err.value.reason == reason, kw
    with pytest.raises(Unsafe) as err:
        check_clickable(element(tag="a", href="https://ex.com/"), root, scope_prefix="/app")
    assert err.value.reason == "out_of_scope"
    check_clickable(element(tag="a", href="https://ex.com/app/x"), root, scope_prefix="/app")


def test_typing_is_never_checked_but_fields_and_passwords_are() -> None:
    check_typeable(element(tag="input", texts=["Task title"], is_text_input=True))
    with pytest.raises(Unsafe):
        check_typeable(element(tag="input", texts=["Send message"]))
    with pytest.raises(Unsafe):
        check_typeable(element(tag="input", input_type="password", texts=["Secret"]))


# --- guard report -------------------------------------------------------------------------------


def test_guard_remembers_the_first_passed_urls_per_rule() -> None:
    guard = RequestGuard("https://ex.com")

    class Req:
        def __init__(self, method: str, url: str) -> None:
            self.method, self.url, self.resource_type, self.post_data = method, url, "fetch", None

    class Route:
        def __init__(self, request: Req) -> None:
            self.request = request

        def continue_(self) -> None: ...
        def abort(self, _: str) -> None: ...
        def fulfill(self, **_: object) -> None: ...

    for i in range(14):
        guard.handle(Route(Req("POST", f"https://ex.com/api/search/{i}")))
    guard.handle(Route(Req("POST", "https://www.google-analytics.com/collect")))
    passed = guard.report()["first_passed_urls"]
    assert len(passed["allowed:read_path"]) == 10
    assert passed["allowed:read_path"][0].startswith("POST https://ex.com/api/search/0")
    assert passed["faked_204:telemetry"] == ["POST https://www.google-analytics.com/collect"]


# --- locate (browser) ---------------------------------------------------------------------------


@pytest.fixture
def tool_page(browser_session: BrowserSession, site: str):  # type: ignore[no-untyped-def]
    ctx = browser_session.new_context()
    page = ctx.new_page()
    page.goto(f"{site}/tool.html")
    yield page
    ctx.close()


def strategy(page: Page, spec: LocatorSpec) -> str | None:
    return resolve(page, spec, retry=False).strategy


def test_every_locate_tier_works_on_its_own(tool_page: Page) -> None:
    page = tool_page
    # 1 stable selector
    assert strategy(page, LocatorSpec(css="#s1")) == "css"
    # 2 role + exact accessible name ("2.8MB" + generated " large photo")
    assert strategy(page, LocatorSpec(role="button", name="2.8MB large photo")) == "role_exact"
    # 3 role + partial name: the stored name is stale/shorter than what the browser computes
    assert strategy(page, LocatorSpec(role="button", name="2.8MB")) == "role_partial"
    # 4 visible text when role/name no longer match
    assert strategy(page, LocatorSpec(role="button", name="gone", text="2.8MB")) == "text"
    # 5 css query + nth, accepted because the fingerprint still matches
    spec = LocatorSpec(css=".sample", nth=1, tag="button", fingerprint="button|1.6mb|0.1,0.1")
    assert strategy(page, spec) == "css_nth"
    # 6 coordinates, only because the element at that point has the same fingerprint
    box = page.locator("#s2").bounding_box()
    assert box is not None
    spec = LocatorSpec(
        tag="button", fingerprint="button|1.6mb|0,0",
        bbox=Bbox(x=box["x"], y=box["y"], w=box["width"], h=box["height"]),
    )  # fmt: skip
    found = resolve(page, spec, retry=False)
    assert found.strategy == "bbox" and found.target is not None
    assert found.target.info().tag == "button"


def test_strategies_are_tried_in_order(tool_page: Page) -> None:
    spec = LocatorSpec(css="#s1", role="button", name="2.8MB large photo", text="2.8MB")
    assert strategy(tool_page, spec) == "css"  # the earliest working tier wins
    stale_css = LocatorSpec(css="#nope", role="button", name="2.8MB large photo")
    result = resolve(tool_page, stale_css, retry=False)
    assert result.strategy == "role_exact" and result.tried[0].startswith("css:")


def test_stale_nth_is_rejected_when_the_fingerprint_changed(tool_page: Page) -> None:
    spec = LocatorSpec(css=".sample", nth=1, tag="button", fingerprint="button|2.8mb|0.1,0.1")
    result = resolve(tool_page, spec, retry=False)
    assert result.target is None
    assert any("css_nth" in t and "changed" in t for t in result.tried)


def test_bbox_is_refused_when_something_else_sits_there(tool_page: Page) -> None:
    box = tool_page.locator("#s2").bounding_box()
    assert box is not None
    spec = LocatorSpec(
        tag="button", fingerprint="button|totally different|0,0",
        bbox=Bbox(x=box["x"], y=box["y"], w=box["width"], h=box["height"]),
    )  # fmt: skip
    result = resolve(tool_page, spec, retry=False)
    assert result.target is None and any("bbox" in t for t in result.tried)


def test_nothing_found_reports_every_strategy_tried(tool_page: Page) -> None:
    spec = LocatorSpec(css="#nope", role="button", name="Không tồn tại", text="Không tồn tại")
    result = resolve(tool_page, spec, retry=False)
    assert result.target is None and result.strategy is None
    tried = " ".join(result.tried)
    assert all(s in tried for s in ("css", "role_exact", "role_partial", "text"))


def test_several_matches_pick_the_one_nearest_to_the_stored_position(tool_page: Page) -> None:
    page = tool_page
    second = page.locator("#s2").bounding_box()
    assert second is not None
    near_second = LocatorSpec(
        role="button", name="large photo",  # matches both sample buttons
        bbox=Bbox(x=second["x"], y=second["y"], w=second["width"], h=second["height"]),
    )  # fmt: skip
    found = resolve(page, near_second, retry=False)
    assert found.strategy == "role_partial" and found.target is not None
    assert found.target.info().text == "1.6MB"
    no_hint = resolve(page, LocatorSpec(role="button", name="large photo"), retry=False)
    assert no_hint.target is None and "ambiguous" in " ".join(no_hint.tried)


def test_blacklist_is_checked_on_the_element_that_was_really_resolved(
    browser_session: BrowserSession, site: str
) -> None:
    ctx = browser_session.new_context()
    page = ctx.new_page()
    page.goto(f"{site}/app.html")
    # stored data claims a harmless name, but the selector really points at the Delete button
    spec = LocatorSpec(css=".del", role="button", name="Thông tin", text="Thông tin")
    found = resolve(page, spec)
    assert found.target is not None and found.strategy == "css"
    with pytest.raises(Unsafe) as err:
        check_clickable(found.target.info(), site)
    assert err.value.reason == "blacklist"
    ctx.close()


def test_links_that_leave_the_site_or_scope_are_refused(
    tool_page: Page, browser_session: BrowserSession, site: str
) -> None:
    docs = resolve(tool_page, LocatorSpec(role="link", name="Tài liệu"), retry=False)
    assert docs.target is not None
    with pytest.raises(Unsafe) as err:
        check_clickable(docs.target.info(), site)
    assert err.value.reason == "leaves_site"
    ctx = browser_session.new_context()
    page = ctx.new_page()
    page.goto(f"{site}/app/")
    home = resolve(page, LocatorSpec(role="link", name="Trang chủ TaskFlow"), retry=False)
    assert home.target is not None
    with pytest.raises(Unsafe) as err2:
        check_clickable(home.target.info(), site, scope_prefix="/app")
    assert err2.value.reason == "out_of_scope"
    ctx.close()
