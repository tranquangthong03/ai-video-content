"""Explorer fixes: dblclick must hit editable items, setup evidence is kept apart, no reload after setup."""

from pathlib import Path

from app.browser.session import BrowserSession
from app.explorer.models import PageData
from app.explorer.synthesize import drop_redundant_goto, is_dblclick_target, sanitize_profile
from app.explorer.verify import same_document, same_url
from app.schemas.generated.locator import LocatorSpec
from app.schemas.generated.product_profile import DemoStep
from tests.test_explorer import el, feature, page_of, profile, verify

# --- (a) which elements a double-click may target ------------------------------------------------


def test_dblclick_targets_are_items_never_controls() -> None:
    ok = [
        el("e1", "Item", tag="label", role="generic", caps=["dblclick"]),
        el("e2", "Row", tag="tr", role="row"),
        el("e3", "Cell", tag="td", role="cell"),
        el("e4", "Entry", tag="li", role="listitem"),
        el("e5", "Task", tag="span", role="generic", caps=["dblclick"]),
    ]
    never = [
        el("e6", "New todo", tag="input", role="textbox", caps=["dblclick"]),  # even when marked
        el("e7", "Notes", tag="textarea", role="textbox"),
        el("e8", "Add", tag="button", role="button", caps=["dblclick"]),
        el("e9", "Pick", tag="select", role="combobox"),
        el("e10", "Plain text", tag="div", role="generic"),  # nothing says it is an item
    ]
    assert all(is_dblclick_target(e) for e in ok)
    assert not any(is_dblclick_target(e) for e in never)


def test_sanitize_drops_a_dblclick_on_an_input_and_says_why() -> None:
    page = PageData(
        n=1,
        url="https://ex.com/app",
        elements=[
            el("e1", "New todo", tag="input", role="textbox"),
            el("e2", "Write report", tag="label", role="generic", caps=["dblclick"]),
        ],
    )

    def step(do: str, ref: str) -> dict:  # type: ignore[type-arg]
        return {"do": do, "url": "https://ex.com/app", "ref": ref}

    prof = profile(
        [
            feature("on-input", "e1", [step("click", "e1"), step("dblclick", "e1")]),
            feature("on-item", "e2", [step("dblclick", "e2")]),
        ]
    )
    clean, notes = sanitize_profile(prof, [page], "https://ex.com")
    by_id = {f.id: f for f in clean.features}
    # the steps before the invalid dblclick would show a different feature: nothing is kept
    assert by_id["on-input"].demo_steps == []
    assert [s.do for s in by_id["on-item"].demo_steps] == ["dblclick"]
    assert any("on-input" in n and "double-click" in n for n in notes)


# --- (a) verifying a dblclick -----------------------------------------------------------------


def css(do: str, url: str, selector: str, text: str | None = None) -> dict:  # type: ignore[type-arg]
    return {"do": do, "url": url, "text": text, "locator": LocatorSpec(css=selector).model_dump()}


def test_a_double_click_that_opens_an_edit_field_in_the_item_is_an_interaction(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    data = page_of(browser_session, site, "/edit.html", tmp_path)
    prof = profile([feature("edit", None, [css("dblclick", data.url, "#item1")], url=data.url)])
    verify(browser_session, prof, [data], site, tmp_path)
    f = prof.features[0]
    assert f.demo_kind == "interaction"
    assert "turned the element into an input" in f.demo_evidence.notes  # type: ignore[union-attr]


def test_a_double_click_that_opens_nothing_is_not_an_interaction(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    data = page_of(browser_session, site, "/edit.html", tmp_path)
    prof = profile([feature("nothing", None, [css("dblclick", data.url, "#rc")], url=data.url)])
    verify(browser_session, prof, [data], site, tmp_path)
    f = prof.features[0]
    assert f.demo_kind != "interaction"
    assert "did not open an edit field" in (f.demo_note or "")


def test_double_clicking_an_input_is_not_an_edit_even_though_it_gets_focus(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    data = page_of(browser_session, site, "/todo.html", tmp_path)
    prof = profile([feature("on-input", None, [css("dblclick", data.url, "#new")], url=data.url)])
    verify(browser_session, prof, [data], site, tmp_path)
    assert prof.features[0].demo_kind != "interaction"


def test_other_steps_changing_the_page_do_not_rescue_a_failed_edit(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    """The todo is added (the list changes), but the double-click that follows edits nothing."""
    data = page_of(browser_session, site, "/todo.html", tmp_path)
    steps = [css("type", data.url, "#new", "Viết báo cáo"), css("dblclick", data.url, "h1")]
    prof = profile([feature("edit-bad", None, steps, url=data.url)])
    verify(browser_session, prof, [data], site, tmp_path)
    f = prof.features[0]
    assert f.demo_kind != "interaction"
    assert "never opened an edit field" in f.demo_evidence.notes or "did not open" in (
        f.demo_note or ""
    )  # type: ignore[union-attr]


# --- (b) evidence of a stateful feature comes only from its own steps ------------------------------


def stateful(data: PageData, own: list[dict]) -> dict:  # type: ignore[type-arg]
    setup = [
        {"do": "goto", "url": data.url},
        css("type", data.url, "#new", "Việc mẫu"),
    ]
    return {**feature("later", None, [*setup, *own], url=data.url), "requires_setup": True}


def test_a_setup_that_changes_the_page_does_not_make_a_feature_that_changes_nothing_an_interaction(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    data = page_of(browser_session, site, "/todo.html", tmp_path)
    prof = profile([stateful(data, [css("click", data.url, "h1")])])
    verify(browser_session, prof, [data], site, tmp_path, setup_counts={"later": 2})
    f = prof.features[0]
    assert f.demo_kind != "interaction"
    ev = f.demo_evidence
    assert (
        ev is not None and ev.new_list_items == 0 and ev.dom_delta == 0
    )  # the new todo is not counted


def test_without_the_setup_split_the_same_steps_would_look_like_an_interaction(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    data = page_of(browser_session, site, "/todo.html", tmp_path)
    prof = profile([stateful(data, [css("click", data.url, "h1")])])
    verify(browser_session, prof, [data], site, tmp_path)  # no setup_counts: all steps are evidence
    assert prof.features[0].demo_kind == "interaction"


# --- (c) no reload after the setup -----------------------------------------------------------------


def test_the_goto_that_follows_the_setup_is_dropped_but_a_hash_route_is_kept() -> None:
    url = "https://ex.com/app"

    def goto(u: str) -> DemoStep:
        return DemoStep(do="goto", url=u)

    click = DemoStep(do="click", url=url, ref="e1")
    assert drop_redundant_goto([goto(url), click], url) == [click]
    assert drop_redundant_goto([goto(url + "/"), click], url) == [
        click
    ]  # trailing slash is the same page
    assert drop_redundant_goto([goto(url + "#/active"), click], url) == [
        goto(url + "#/active"),
        click,
    ]
    assert drop_redundant_goto([goto(url + "#/active"), click], url + "#/active") == [click]
    assert drop_redundant_goto([click], url) == [click]
    assert drop_redundant_goto([goto("https://ex.com/other"), click], url)[0].do == "goto"
    assert same_url(url + "#/a", url + "#/a") and not same_url(url + "#/a", url + "#/b")


def test_a_hash_route_change_is_not_a_reason_to_reload_the_page(
    browser_session: BrowserSession, site: str, tmp_path: Path, hits: list[str]
) -> None:
    """Steps recorded on `/todo.html` run after a click moved the page to `/todo.html#/active`."""
    data = page_of(browser_session, site, "/todo.html", tmp_path)
    steps = [
        css("type", data.url, "#new", "Việc một"),
        css("click", data.url, "a[href='#/active']"),
        css("click", data.url, "a[href='#/completed']"),
    ]
    prof = profile([feature("routes", None, steps, url=data.url)])
    hits.clear()
    verify(browser_session, prof, [data], site, tmp_path)
    assert len([h for h in hits if h.startswith("/todo.html")]) == 1  # only the first load
    assert prof.features[0].demo_note is None  # no step failed
    assert not same_document("http://x/a#/one", "http://x/b#/one")
    assert same_document("http://x/a/#/one", "http://x/a#/two")


def test_verify_skips_the_reload_after_the_setup_and_keeps_a_hash_route(
    browser_session: BrowserSession, site: str, tmp_path: Path, hits: list[str]
) -> None:
    data = page_of(browser_session, site, "/todo.html", tmp_path)
    hits.clear()
    reload_ = stateful(data, [{"do": "goto", "url": data.url}, css("click", data.url, "h1")])
    prof = profile([reload_])
    verify(browser_session, prof, [data], site, tmp_path, setup_counts={"later": 2})
    with_reload = [h for h in hits if h.startswith("/todo.html")]
    notes = prof.features[0].demo_evidence.notes  # type: ignore[union-attr]
    assert "skipped a reload" in notes

    hits.clear()
    prof2 = profile([stateful(data, [css("click", data.url, "h1")])])
    verify(browser_session, prof2, [data], site, tmp_path / "b", setup_counts={"later": 2})
    assert with_reload == [
        h for h in hits if h.startswith("/todo.html")
    ]  # same requests: no extra reload

    routed = stateful(
        data, [{"do": "goto", "url": data.url + "#/active"}, css("click", data.url, "h1")]
    )
    prof3 = profile([routed])
    verify(browser_session, prof3, [data], site, tmp_path / "c", setup_counts={"later": 2})
    assert "skipped a reload" not in prof3.features[0].demo_evidence.notes  # type: ignore[union-attr]
    assert prof3.features[0].demo_note is None  # the hash route step ran without a failure
