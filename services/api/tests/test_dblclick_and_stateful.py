"""dblclick / right_click, and stateful discovery (features that only exist after data does)."""

import json
from pathlib import Path

from app.browser.session import BrowserSession
from app.explorer.analyze import format_elements
from app.explorer.models import PageData
from app.explorer.report import Deadline, Report
from app.explorer.stateful import (
    MAX_PAGES,
    delta_elements,
    interaction_setups,
    run_stateful,
)
from app.explorer.synthesize import sanitize_profile
from app.explorer.verify import Evidence, classify_demo, verify_features
from app.llm.json_call import JsonCaller
from app.schemas.generated.locator import LocatorSpec
from tests.conftest import FakeLLM, _section, scripted_handler
from tests.test_explorer import el, feature, page_of, profile, verify

# --- dblclick / right_click ---------------------------------------------------------------------


def test_page_text_about_double_click_marks_the_labels_that_react(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    data = page_of(browser_session, site, "/edit.html", tmp_path)
    assert data.signals["dblclick_hint"] is True
    items = {e.text: e for e in data.elements if "dblclick" in e.caps}
    assert set(items) == {"Tưới cây", "Delete me"}
    assert all(e.role == "generic" for e in items.values())  # plain text blocks, not buttons
    assert "dblclick" in format_elements(data)  # the analyzer sees the capability column


def test_format_elements_lists_every_capability() -> None:
    page = PageData(
        n=1, url="https://ex.com/",
        elements=[el("e1", "Open"), el("e2", "Drop", caps=["upload"]),
                  el("e3", "Item", caps=["upload", "dblclick"])],
    )  # fmt: skip
    lines = format_elements(page).splitlines()
    assert lines[0].endswith("| main") and lines[1].endswith("| upload")
    assert lines[2].endswith("| upload,dblclick")


def test_double_click_that_starts_editing_is_an_interaction(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    data = page_of(browser_session, site, "/edit.html", tmp_path)
    item = next(e for e in data.elements if e.text == "Tưới cây")
    step = {"do": "dblclick", "url": data.url, "ref": item.ref}
    prof = profile([feature("edit", None, [step], url=data.url)])
    report = verify(browser_session, prof, [data], site, tmp_path)
    f = prof.features[0]
    assert f.demo_kind == "interaction"
    assert "double-click" in (f.demo_evidence.notes if f.demo_evidence else "")
    assert any(c.get("kind") == "dblclick" for c in report.data["clicks"])


def test_editing_alone_is_enough_for_an_interaction_verdict() -> None:
    ev = Evidence(editing=True)
    kind, score = classify_demo(ev, reached=True, steps_done=1, steps_total=1)
    assert kind == "interaction" and score >= 0.6


def test_blacklist_applies_to_double_click_like_to_click(
    browser_session: BrowserSession, site: str, tmp_path: Path, hits: list[str]
) -> None:
    data = page_of(browser_session, site, "/edit.html", tmp_path)
    doomed = next(e for e in data.elements if e.text == "Delete me")
    step = {"do": "dblclick", "url": data.url, "ref": doomed.ref}
    prof = profile([feature("dbl-delete", None, [step], url=data.url)])
    report = verify(browser_session, prof, [data], site, tmp_path)
    assert [(b["name"], b["reason"]) for b in report.data["clicks_blocked"]] == [
        ("Delete me", "blacklist")
    ]
    assert "/hit/dbl-delete" not in hits
    assert prof.features[0].demo_kind == "failed"


def test_right_click_opens_a_context_menu(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    data = page_of(browser_session, site, "/edit.html", tmp_path)
    step = {"do": "right_click", "url": data.url, "locator": LocatorSpec(css="#rc").model_dump()}
    prof = profile([feature("ctx", None, [step], url=data.url)])
    report = verify(browser_session, prof, [data], site, tmp_path)
    assert prof.features[0].demo_kind == "interaction"  # three menu buttons appeared
    assert any(c.get("kind") == "right_click" for c in report.data["clicks"])


def test_sanitize_accepts_dblclick_steps_and_refuses_blacklisted_ones() -> None:
    page = PageData(
        n=1, url="https://ex.com/app",
        elements=[el("e1", "Todo item", role="generic", caps=["dblclick"]), el("e2", "Delete all")],
    )  # fmt: skip

    def step(do: str, ref: str) -> dict:  # type: ignore[type-arg]
        return {"do": do, "url": "https://ex.com/app", "ref": ref}

    prof = profile(
        [
            feature("ok", "e1", [step("dblclick", "e1"), step("right_click", "e1")]),
            feature("bad", "e2", [step("dblclick", "e2")]),
        ]
    )
    clean, _ = sanitize_profile(prof, [page], "https://ex.com")
    by_id = {f.id: f for f in clean.features}
    assert [s.do for s in by_id["ok"].demo_steps] == ["dblclick", "right_click"]
    assert by_id["ok"].demo_steps[0].locator is not None
    assert by_id["bad"].demo_steps == []


# --- stateful: pure parts -----------------------------------------------------------------------


def test_delta_elements_are_the_ones_the_old_state_did_not_have() -> None:
    old = PageData(
        n=1, url="https://ex.com/", elements=[el("e1", "New todo", tag="input", text="")]
    )
    new = PageData(
        n=1, url="https://ex.com/",
        elements=[
            el("e1", "New todo", tag="input", text=""),  # same as before: not new
            el("e2", "Mua sữa", tag="label", text="Mua sữa"),
            el("e3", "Active", tag="a", text="Active"),
            el("e4", "Active", tag="a", text="active"),  # same identity once normalised
        ],
    )  # fmt: skip
    fresh = delta_elements(old, new, "s1")
    assert [(e.ref, e.name) for e in fresh] == [("s1e1", "Mua sữa"), ("s1e2", "Active")]
    assert new.elements[1].ref == "e2"  # the input state is not mutated


def feature_with_evidence(fid: str, importance: float, url: str, **ev: object) -> object:
    f = profile([feature(fid, None, [{"do": "click", "url": url, "ref": "e1"}], url=url)]).features[
        0
    ]
    f.importance, f.demo_kind = importance, "interaction"
    from app.schemas.generated.product_profile import DemoEvidence

    f.demo_evidence = DemoEvidence(
        **{"url_changed": False, "dom_delta": 0, "new_dialog": False, "new_list_items": 0,
           "visual_diff": 0.0, **ev}  # type: ignore[arg-type]
    )  # fmt: skip
    return f


def test_setups_are_limited_to_three_pages_and_need_data_creating_interactions() -> None:
    urls = [f"https://ex.com/p{i}" for i in range(5)]
    pages = [PageData(n=i, url=u, elements=[el("e1", "x")]) for i, u in enumerate(urls, start=1)]
    feats = [
        feature_with_evidence("dialog-only", 0.99, urls[0], new_dialog=True),  # no data created
        feature_with_evidence("a", 0.9, urls[0], new_list_items=2),
        feature_with_evidence("a2", 0.85, urls[0], new_list_items=2),  # same page: not chosen
        feature_with_evidence("b", 0.8, urls[1], dom_delta=3),
        feature_with_evidence("c", 0.7, urls[2], visual_diff=0.2),
        feature_with_evidence("d", 0.6, urls[3], new_list_items=1),  # fourth page: over the limit
    ]
    prof = profile([])
    prof.features = feats  # type: ignore[assignment]
    chosen = interaction_setups(prof, pages)
    assert [f.id for _, f in chosen] == ["a", "b", "c"] and len(chosen) == MAX_PAGES
    already = feats[1]
    already.requires_setup = True
    assert "a" not in [f.id for _, f in interaction_setups(prof, pages)]  # no setup on a setup


# --- stateful: end to end on the todo fixture ---------------------------------------------------


def delta_handler(prompt: str):  # type: ignore[no-untyped-def]
    """The synthesizer stand-in: when it is given a state delta, it finds the filter links."""
    if "<state_delta>" not in prompt:
        return scripted_handler(prompt)
    insights = json.loads(_section(prompt, "pages"))
    actions = {a["name"]: a for i in insights for a in i["actions"]}
    url = insights[0]["url"]
    return {
        "site_type": "web_app", "product_name": "Todo", "one_liner": "o", "target_users": [],
        "features": [
            {"id": "filter-views", "name": "Lọc theo trạng thái", "description": "All/Active/Completed",
             "importance": 0.7,
             "evidence": [{"source": "app_action", "url": url, "ref": actions["Active"]["ref"]}],
             "demo_steps": [{"do": "click", "url": url, "ref": actions["Completed"]["ref"]}]},
            {"id": "again", "name": "Thêm việc", "description": "already known", "importance": 0.5,
             "evidence": [{"source": "app_action", "url": url, "ref": actions["All"]["ref"]}],
             "demo_steps": []},
        ],
        "open_questions": [],
    }  # fmt: skip


def test_filter_bar_is_found_only_after_a_todo_exists(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    page = page_of(browser_session, site, "/todo.html", tmp_path)
    assert {"All", "Active", "Completed"}.isdisjoint(
        e.name for e in page.elements
    )  # hidden at first
    ref = next(e.ref for e in page.elements if e.name == "New todo")
    add = [{"do": "type", "url": page.url, "ref": ref, "text": "Mua sữa"}]
    prof = profile([feature("add-todo", None, add, url=page.url) | {"name": "Thêm việc"}])
    report = Report(site)
    verify_features(browser_session, prof, [page], site, tmp_path, report, Deadline(120))
    assert prof.features[0].demo_kind == "interaction"  # Enter added the item

    llm = FakeLLM(delta_handler)
    caller = JsonCaller(llm, cache_dir=tmp_path / "cache")
    added = run_stateful(
        browser_session, prof, [page], [],
        root_url=site, site_type="web_app", caller=caller, out_dir=tmp_path, report=report,
        deadline=Deadline(180),
    )  # fmt: skip

    assert [f.id for f in added] == ["filter-views"]  # "Thêm việc" was already known: not repeated
    f = added[0]
    assert f.requires_setup is True
    assert [s.do for s in f.demo_steps] == ["type", "click"]  # setup steps first, then its own
    assert f.demo_steps[0].ref == ref and f.demo_steps[1].ref.startswith("s1e")  # type: ignore[union-attr]
    assert f.demo_kind == "interaction"
    assert "requires setup" in (f.demo_evidence.notes if f.demo_evidence else "")
    # the setup's own effects (a new list item) are replayed but not counted as the evidence
    assert f.demo_evidence is not None and f.demo_evidence.new_list_items == 0
    assert f.demo_evidence.dom_delta >= 2  # hiding the item removed its checkbox and button
    assert [x.id for x in prof.features] == ["add-todo", "filter-views"]
    # only the delta went to the analyzer, once, and the synthesizer got the setup steps
    delta_prompts = [
        c["prompt"]
        for c in llm.calls
        if "<state_delta>" in c["prompt"] or "sau khi đã thao tác" in c["prompt"]
    ]
    analyzer = next(p for p in delta_prompts if p.startswith("Bạn là chuyên gia"))
    assert "Completed" in analyzer and "New todo" not in analyzer  # new elements only
    synth = next(p for p in delta_prompts if "<state_delta>" in p)
    assert '"do": "type"' in synth and "Mua sữa" in synth and "Thêm việc" in synth
    assert caller.tracker.steps["delta"]["calls"] == 2
    entry = report.data["stateful"][0]
    assert entry["new_features"] == ["filter-views"] and entry["delta_elements"] >= 3
    assert page.setup_steps and any(e.ref.startswith("s1e") for e in page.elements)


def test_without_setup_counts_the_setup_effects_would_count_as_evidence(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    page = page_of(browser_session, site, "/todo.html", tmp_path)
    ref = next(e.ref for e in page.elements if e.name == "New todo")
    steps = [{"do": "type", "url": page.url, "ref": ref, "text": "Mua sữa"}]
    prof = profile([feature("x", None, steps, url=page.url)])
    verify(browser_session, prof, [page], site, tmp_path, setup_counts={"x": 1})
    assert prof.features[0].demo_evidence.new_list_items == 0  # type: ignore[union-attr]
    plain = profile([feature("x", None, steps, url=page.url)])
    verify(browser_session, plain, [page], site, tmp_path / "plain")
    assert plain.features[0].demo_evidence.new_list_items == 1  # type: ignore[union-attr]
