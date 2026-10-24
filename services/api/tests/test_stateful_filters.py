"""Stateful discovery: filters need data that makes the result differ; failed features can be replaced."""

import json
from pathlib import Path
from typing import Any

from app.browser.session import BrowserSession
from app.explorer.models import PageData
from app.explorer.report import Deadline, Report
from app.explorer.stateful import is_replaceable, prep_len, run_stateful
from app.explorer.verify import verify_features
from app.llm.json_call import JsonCaller
from app.schemas.generated.product_profile import DemoStep
from tests.conftest import FakeLLM, _section, scripted_handler
from tests.test_explorer import el, feature, page_of, profile, verify
from tests.test_explorer_fixes import css


def todo_page(session: BrowserSession, site: str, tmp_path: Path) -> tuple[PageData, str]:
    page = page_of(session, site, "/todo.html", tmp_path)
    ref = next(e.ref for e in page.elements if e.name == "New todo")
    return page, ref


def add_feature(page: PageData, ref: str) -> dict:  # type: ignore[type-arg]
    step = {"do": "type", "url": page.url, "ref": ref, "text": "Viết báo cáo"}
    return feature("add-todo", None, [step], url=page.url) | {"name": "Thêm việc"}


def named(page: PageData, name: str) -> Any:
    return next(e for e in page.elements if e.name == name)


# --- a filter that shows the same list is not a demo -------------------------------------------------


def test_filtering_by_active_when_everything_is_active_changes_nothing_so_it_is_not_demonstrable(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    page, _ = todo_page(browser_session, site, tmp_path)
    setup = [{"do": "goto", "url": page.url}, css("type", page.url, "#new", "Một việc")]
    own = [css("click", page.url, "a[href='#/active']")]
    f = {**feature("filter", None, [*setup, *own], url=page.url), "requires_setup": True}
    prof = profile([f])
    verify(browser_session, prof, [page], site, tmp_path, setup_counts={"filter": 2})
    assert prof.features[0].demo_kind != "interaction"  # the hash changed, the list did not


def test_the_same_filter_after_preparing_a_checked_item_does_change_the_list(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    page, _ = todo_page(browser_session, site, tmp_path)
    steps = [
        {"do": "goto", "url": page.url},
        css("type", page.url, "#new", "Việc một"),  # setup
        css("type", page.url, "#new", "Việc hai"),  # preparation
        css(
            "click", page.url, "li:first-child input[type=checkbox]"
        ),  # preparation: tick the first item
        css("click", page.url, "a[href='#/active']"),  # the real trigger: hides the ticked one
    ]
    f = {**feature("filter", None, steps, url=page.url), "requires_setup": True}
    prof = profile([f])
    verify(browser_session, prof, [page], site, tmp_path, setup_counts={"filter": 4})
    got = prof.features[0]
    assert got.demo_kind == "interaction", (got.demo_note, got.demo_evidence)
    ev = got.demo_evidence
    assert (
        ev is not None and ev.new_list_items == 0 and ev.dom_delta >= 2
    )  # only the filter counted


def test_prep_len_counts_typing_and_ticking_but_stops_at_the_trigger() -> None:
    page = PageData(
        n=1,
        url="https://ex.com/",
        elements=[
            el("e1", "New todo", role="textbox", tag="input"),
            el("e2", "Done", role="checkbox", tag="input"),
            el("e3", "Active", role="link", tag="a"),
            el("e4", "Completed", role="link", tag="a"),
        ],
    )

    def step(do: str, ref: str | None = None) -> DemoStep:
        return DemoStep(do=do, url="https://ex.com/", ref=ref, text="x" if do == "type" else None)

    assert (
        prep_len(
            [step("type", "e1"), step("click", "e2"), step("click", "e3"), step("click", "e4")],
            page,
        )
        == 2
    )
    assert prep_len([step("click", "e3"), step("type", "e1")], page) == 0  # the trigger comes first
    assert prep_len([step("click", "e1"), step("type", "e1"), step("click", "e3")], page) == 2
    assert prep_len([], page) == 0


# --- end to end: the delta step proposes a filter with its own data preparation -------------------------


def filter_handler(page: PageData, ref: str):  # type: ignore[no-untyped-def]
    def handler(prompt: str) -> dict[str, Any]:
        if "<state_delta>" not in prompt:
            return scripted_handler(prompt)
        url = page.url
        done = named(page, "Done").ref  # delta elements are already on the page when this runs
        active = named(page, "Active").ref
        return {
            "site_type": "web_app", "product_name": "Todo", "one_liner": "o", "target_users": [],
            "features": [{
                "id": "filter-views", "name": "Lọc theo trạng thái", "description": "Active",
                "importance": 0.7,
                "evidence": [{"source": "app_action", "url": url, "ref": active}],
                "demo_steps": [
                    {"do": "type", "url": url, "ref": ref, "text": "Việc hai"},
                    {"do": "click", "url": url, "ref": done},
                    {"do": "click", "url": url, "ref": active},
                ],
            }],
            "open_questions": [],
        }  # fmt: skip

    return handler


def test_a_filter_with_its_own_preparation_is_judged_by_the_filter_click_alone(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    page, ref = todo_page(browser_session, site, tmp_path)
    prof = profile([add_feature(page, ref)])
    report = Report(site)
    verify_features(browser_session, prof, [page], site, tmp_path, report, Deadline(120))
    llm = FakeLLM(filter_handler(page, ref))
    added = run_stateful(
        browser_session, prof, [page], [], root_url=site, site_type="web_app",
        caller=JsonCaller(llm, cache_dir=tmp_path / "c"), out_dir=tmp_path, report=report,
        deadline=Deadline(180),
    )  # fmt: skip
    assert [f.id for f in added] == ["filter-views"]
    f = added[0]
    assert [s.do for s in f.demo_steps] == [
        "type",
        "type",
        "click",
        "click",
    ]  # setup + preparation + trigger
    assert f.demo_kind == "interaction"
    assert (
        f.demo_evidence is not None and f.demo_evidence.new_list_items == 0
    )  # neither add counted


# --- failed features can be replaced by the delta step ---------------------------------------------------


def test_a_failed_feature_is_not_known_and_is_replaced_by_the_new_one_with_working_steps(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    page, ref = todo_page(browser_session, site, tmp_path)
    failed = {**feature("edit-todo", None, [], url=page.url), "name": "Sửa việc tại chỗ"}
    prof = profile([add_feature(page, ref), failed])
    report = Report(site)
    verify_features(browser_session, prof, [page], site, tmp_path, report, Deadline(120))
    old = next(f for f in prof.features if f.id == "edit-todo")
    assert old.demo_kind in (None, "failed") and is_replaceable(old)
    assert not is_replaceable(next(f for f in prof.features if f.id == "add-todo"))

    prompts: list[str] = []

    def handler(prompt: str) -> dict[str, Any]:
        if "<state_delta>" not in prompt:
            return scripted_handler(prompt)
        prompts.append(prompt)
        label = next(e for e in page.elements if e.ref.startswith("s") and e.tag == "label")
        return {
            "site_type": "web_app", "product_name": "Todo", "one_liner": "o", "target_users": [],
            "features": [{
                "id": "edit-todo-new", "name": "Sửa việc tại chỗ", "description": "nhấp đúp",
                "importance": 0.6,
                "evidence": [{"source": "app_action", "url": page.url, "ref": label.ref}],
                "demo_steps": [{"do": "dblclick", "url": page.url, "ref": label.ref}],
            }],
            "open_questions": [],
        }  # fmt: skip

    llm = FakeLLM(handler)
    added = run_stateful(
        browser_session, prof, [page], [], root_url=site, site_type="web_app",
        caller=JsonCaller(llm, cache_dir=tmp_path / "c"), out_dir=tmp_path, report=report,
        deadline=Deadline(180),
    )  # fmt: skip
    known_line = json.dumps(_section(prompts[0], "pages"), ensure_ascii=False)
    assert (
        "Sửa việc tại chỗ"
        not in prompts[0].split("không lặp lại các tính năng đã có:")[1].split(".")[0]
    )
    assert known_line  # the prompt was built
    assert [f.id for f in added] == ["edit-todo-new"] and added[0].demo_kind == "interaction"
    assert [f.id for f in prof.features] == ["add-todo", "edit-todo-new"]  # the failed one is gone
