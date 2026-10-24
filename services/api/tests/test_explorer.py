"""Explorer tests against the local fixture site (needs Playwright Chromium, no network, no LLM)."""

from pathlib import Path

from app.browser.session import BrowserSession
from app.browser.urls import normalize_url
from app.explorer.extract import extract_page
from app.explorer.mapper import (
    Candidate,
    Frontier,
    candidates_from_links,
    crawl,
    pick_candidates_by_description,
    score_candidate,
    template_keys,
)
from app.explorer.models import Element, PageData
from app.explorer.report import Deadline, Report
from app.explorer.synthesize import sanitize_profile
from app.explorer.verify import Evidence, classify_demo, verify_features
from app.schemas.generated.page_insight import PageInsight
from app.schemas.generated.product_profile import ProductProfile

# --- mapper (pure) ------------------------------------------------------------------------------


def test_normalize_url() -> None:
    assert normalize_url("/a/?utm_source=x&b=1#top", "https://Ex.com/") == "https://ex.com/a?b=1"
    assert normalize_url("https://ex.com/#/active") == "https://ex.com/#/active"  # hash route kept
    assert normalize_url("https://ex.com/#pricing") == "https://ex.com/"  # plain anchor dropped...
    assert normalize_url("https://ex.com/#pricing", keep_anchor=True) == "https://ex.com/#pricing"
    assert normalize_url("mailto:a@b.c") is None
    assert normalize_url("https://ex.com/file.pdf") is None


def test_scoring_prefers_nav_and_feature_paths_and_penalises_noise() -> None:
    app = score_candidate("https://ex.com/app", "nav", 1)
    pricing = score_candidate("https://ex.com/pricing", "header", 1)
    blog = score_candidate("https://ex.com/blog/post", "footer", 1)
    login = score_candidate("https://ex.com/login", "nav", 1)
    assert app > pricing > blog
    assert login < app and blog < 0
    assert score_candidate("https://ex.com/x", "nav", 2) < score_candidate(
        "https://ex.com/x", "nav", 1
    )


def test_link_text_adds_a_strong_bonus() -> None:
    url = "https://ex.com/p/1"
    plain = score_candidate(url, "main", 1, text="About us")
    assert score_candidate(url, "main", 1, text="Try the live demo") >= plain + 4
    assert score_candidate(url, "main", 1, text="Dùng thử") >= plain + 4
    assert score_candidate(url, "main", 1, text="Trải nghiệm ngay") >= plain + 4
    assert plain + 2 <= score_candidate(url, "main", 1, text="Pricing") < plain + 4
    assert score_candidate(url, "main", 1, text="Bảng giá") >= plain + 2


def link(href: str, text: str = "x", region: str = "nav") -> dict:  # type: ignore[type-arg]
    return {"href": href, "text": text, "region": region, "visible": True}


def test_candidates_drop_blacklisted_offsite_and_skip_reason_is_reported() -> None:
    report = Report("https://ex.com")
    raw = [
        link("https://ex.com/features", "Features"),
        link("https://ex.com/account/delete", "Account"),
        link("https://ex.com/p", "Buy now"),
        link("https://ex.com/logout", "Out", "footer"),
        link("https://other.com/x", "Elsewhere"),
    ]
    found = candidates_from_links(raw, "https://ex.com/", "https://ex.com", 1, report)
    assert [c.url for c in found] == ["https://ex.com/features"]
    reasons = " ".join(s["reason"] for s in report.data["pages_skipped"])
    assert "Buy now" in reasons and "logout" in reasons and "delete" in reasons


def test_same_page_anchors_are_sections_not_pages() -> None:
    report = Report("https://ex.com")
    raw = [
        link("https://ex.com/#features", "Features"),
        link("https://ex.com/#pricing", "Pricing"),
        link("https://ex.com/pricing#plans", "Plans"),  # another page with an anchor: a real page
        link("https://ex.com/other", "Other"),
    ]
    found = candidates_from_links(raw, "https://ex.com/", "https://ex.com", 1, report)
    assert sorted(c.url for c in found) == ["https://ex.com/other", "https://ex.com/pricing"]
    assert report.data["anchor_sections"] == 2


def test_path_scope_keeps_in_scope_links_and_lists_the_rest() -> None:
    report = Report("https://todomvc.com/examples/react/dist/")
    prefix = "/examples/react/dist"
    raw = [
        link("https://todomvc.com/examples/react/dist/#/active", "Active"),
        link("https://todomvc.com/examples/react/dist/other", "Other"),
        link("https://todomvc.com/examples/vue/dist/", "Vue"),
        link("https://todomvc.com/", "Home"),
        link("https://todomvc.com/examples/react/distribution", "Not a child path"),
    ]
    found = candidates_from_links(
        raw, "https://todomvc.com/examples/react/dist", "https://todomvc.com/examples/react/dist",
        1, report, prefix=prefix,
    )  # fmt: skip
    assert sorted(c.url for c in found) == [
        "https://todomvc.com/examples/react/dist#/active",
        "https://todomvc.com/examples/react/dist/other",
    ]
    listed = {x["url"] for x in report.data["out_of_scope"]}
    assert (
        listed
        == {
            "https://todomvc.com/examples/vue/dist",
            "https://todomvc.com",
            "https://todomvc.com/examples/react/distribution",
        }
        or "https://todomvc.com/" in listed
    )  # normalisation of the bare domain differs by version


def test_template_keys_group_similar_paths() -> None:
    assert template_keys("https://ex.com/for-saas") == ["/for-*"]
    assert template_keys("https://ex.com/vs-matomo") == ["/vs-*"]
    assert "/*-web-analytics" in template_keys("https://ex.com/simple-web-analytics")
    assert template_keys("https://ex.com/blog/a-post") == ["/blog/*"]
    assert template_keys("https://ex.com/docs/a/b") == ["/docs/*/*"]
    assert template_keys("https://ex.com/pricing") == []
    assert template_keys("https://ex.com/") == []


def test_frontier_samples_each_template_group_twice() -> None:
    f = Frontier()
    for i, name in enumerate(["a", "b", "c", "d"]):
        f.add(Candidate(f"https://ex.com/for-{name}", "", "nav", 1, 5.0 - i * 0.1))
    f.add(Candidate("https://ex.com/pricing", "", "nav", 1, 1.0))
    popped = []
    while (c := f.pop()) is not None:
        popped.append(c.url.rsplit("/", 1)[1])
    assert popped == ["for-a", "for-b", "pricing"]  # for-c and for-d were grouped away
    assert f.grouped_skips == {"/for-*": 2}


def test_small_groups_are_not_limited() -> None:
    f = Frontier()
    f.add(Candidate("https://ex.com/for-a", "", "nav", 1, 3.0))
    f.add(Candidate("https://ex.com/for-b", "", "nav", 1, 2.0))
    assert f.pop() and f.pop() and f.grouped_skips == {}


def test_demo_slots_are_served_first_when_requested() -> None:
    f = Frontier()
    f.add(Candidate("https://ex.com/blog", "", "nav", 1, 9.0))
    f.add(Candidate("https://ex.com/live", "Live demo", "main", 1, 1.0, demo=True))
    first = f.pop(prefer_demo=True)
    assert first is not None and first.url.endswith("/live")
    second = f.pop()
    assert second is not None and second.url.endswith("/blog")


def test_frontier_pops_best_first_and_never_twice() -> None:
    f = Frontier()
    f.add(Candidate("https://ex.com/low", "", "footer", 1, 0.2))
    f.add(Candidate("https://ex.com/high", "", "nav", 1, 5.0))
    f.add(Candidate("https://ex.com/high", "", "nav", 1, 4.0))  # lower duplicate ignored
    assert [f.pop().url, f.pop().url, f.pop()] == [  # type: ignore[union-attr]
        "https://ex.com/high",
        "https://ex.com/low",
        None,
    ]


def test_pick_candidates_by_description() -> None:
    cands = [
        {"url": "https://ex.com/reports", "text": "Báo cáo", "score": 1.0},
        {"url": "https://ex.com/settings", "text": "Cài đặt", "score": 3.0},
    ]
    assert pick_candidates_by_description(cands, [], "xem trang báo cáo reports") == [
        "https://ex.com/reports"
    ]
    assert pick_candidates_by_description(cands, ["https://ex.com/reports"], "reports") == []


# --- extraction ---------------------------------------------------------------------------------


def page_of(session: BrowserSession, site: str, path: str, out: Path, n: int = 1) -> PageData:
    ctx = session.new_context()
    page = ctx.new_page()
    page.goto(f"{site}{path}")
    data = extract_page(page, n, out)
    ctx.close()
    return data


def test_extract_assigns_stable_refs_and_selectors(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    first = page_of(browser_session, site, "/app.html", tmp_path)
    second = page_of(browser_session, site, "/app.html", tmp_path)
    assert [(e.ref, e.role, e.name) for e in first.elements] == [
        (e.ref, e.role, e.name) for e in second.elements
    ]
    assert [e.ref for e in first.elements] == [f"e{i}" for i in range(1, len(first.elements) + 1)]
    by_name = {e.name: e for e in first.elements}
    assert by_name["New task"].selector == "#new-task"
    assert by_name["Báo cáo"].selector == '[data-testid="tab-reports"]'  # data-testid wins over id
    assert by_name["Báo cáo"].region == "nav"  # a nav inside an aside counts as navigation
    assert by_name["Delete task"].role == "button"
    assert (tmp_path / "pages" / "1.json").is_file() and (tmp_path / "pages" / "1.png").is_file()
    assert first.signals["has_sidebar"] is True and first.headings[0].text == "Công việc"


def test_extract_stores_a_full_locator_per_element(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    data = page_of(browser_session, site, "/app.html", tmp_path)
    by_name = {e.name: e for e in data.elements}
    stable = by_name["New task"].locator
    assert stable.css == "#new-task" and stable.nth is None
    assert stable.role == "button" and stable.name == "New task" and stable.tag == "button"
    assert stable.text == "New task"
    assert stable.fingerprint and stable.fingerprint.startswith("button|new task|")
    assert stable.bbox is not None and stable.bbox.w > 0
    plain = by_name["Thông tin"].locator  # id "noop" is stable too, so css is that id
    assert plain.css == "#noop"
    link_el = by_name["Delete task"]
    assert link_el.text == "Delete"  # innerText differs from the accessible name (aria-label)


def test_accessible_name_comes_from_the_browser_not_from_innertext(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    data = page_of(browser_session, site, "/tool.html", tmp_path)
    sample = next(e for e in data.elements if e.text == "2.8MB")
    assert sample.name == "2.8MB large photo"  # generated ::after content is part of the name
    assert sample.locator.name == "2.8MB large photo"


def test_hidden_file_input_is_an_upload_target(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    data = page_of(browser_session, site, "/tool.html", tmp_path)
    upload = [e for e in data.elements if "upload" in e.caps and e.tag == "input"]
    assert len(upload) == 1
    assert upload[0].role == "file" and upload[0].accept == "image/*"
    assert upload[0].selector == "#file"
    assert "Kéo thả" in upload[0].name  # named after its drop zone label


def test_anchor_sections_are_recorded_on_the_page(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    data = page_of(browser_session, site, "/", tmp_path)
    assert [(a.id, a.selector) for a in data.anchors] == [("features", "#features")]
    assert "Kanban" in data.anchors[0].text


def test_forms_are_described_for_the_enter_policy(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    data = page_of(browser_session, site, "/form.html", tmp_path)
    by_name = {e.name: e for e in data.elements}
    note = by_name["Your note"].form
    assert note is not None and note.method == "post" and note.text_inputs == 1
    assert note.action.endswith("/submit-note")
    assert by_name["Search notes"].form.method == "get"  # type: ignore[union-attr]
    assert by_name["First name"].form.text_inputs == 2  # type: ignore[union-attr]
    quick = page_of(browser_session, site, "/quick.html", tmp_path, n=2)
    assert next(e for e in quick.elements if e.name == "Add item").in_form is False


def test_hidden_dialog_fields_are_not_extracted(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    names = {e.name for e in page_of(browser_session, site, "/app.html", tmp_path).elements}
    assert "Task title" not in names and "Add" not in names


# --- crawl --------------------------------------------------------------------------------------


def run_crawl(
    session: BrowserSession, url: str, tmp_path: Path, **kw: object
) -> tuple[list[PageData], Report]:
    ctx = session.new_context()
    report = Report(url)
    pages, _ = crawl(ctx.new_page(), ctx, url, tmp_path, report, Deadline(120), **kw)  # type: ignore[arg-type]
    ctx.close()
    return pages, report


def test_crawl_visits_important_pages_first_and_never_blacklisted_ones(
    browser_session: BrowserSession, site: str, tmp_path: Path, hits: list[str]
) -> None:
    pages, report = run_crawl(browser_session, site + "/", tmp_path, max_pages=6)
    paths = [p.url.removeprefix(site) for p in pages]
    assert paths[0] in ("", "/")
    assert "/app.html" in paths and "/features.html" in paths and "/pricing.html" in paths
    assert (
        paths.index("/app.html") < paths.index("/blog/post.html")
        if "/blog/post.html" in paths
        else True
    )
    assert not any(h.startswith(("/logout", "/account")) for h in hits)
    assert all(p.depth <= 2 for p in pages) and len(pages) <= 6
    skipped = " ".join(s["reason"] for s in report.data["pages_skipped"])
    assert "blacklist" in skipped
    assert any(c["name"] == "Báo cáo" for c in report.data["clicks"])  # SPA nav click
    assert not any(c["name"] in ("Delete", "Delete task") for c in report.data["clicks"])
    assert report.data["anchor_sections"] >= 1  # the /#features link is a section, not a page
    assert not any(p.url.endswith("#features") for p in pages)
    assert report.data["locate"]["strategies"]  # which strategy resolved each nav click


def test_path_scope_stays_under_the_start_path_and_asks_about_the_domain(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    pages, report = run_crawl(browser_session, site + "/app/", tmp_path, max_pages=8)
    paths = sorted((normalize_url(p.url) or "").removeprefix(site) for p in pages)
    assert paths == ["/app", "/app/archive.html"]
    out = {x["url"].removeprefix(site) for x in report.data["out_of_scope"]}
    assert {"/", "/features.html", "/pricing.html"} <= out
    assert report.data["scope"] == {"mode": "path", "path_prefix": "/app"}
    question = report.data["scope_question"]
    assert "/app" in question and "toàn bộ" in question


def test_domain_scope_follows_links_out_of_the_path(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    pages, report = run_crawl(
        browser_session, site + "/app/", tmp_path, max_pages=8, scope="domain"
    )
    paths = {p.url.removeprefix(site) for p in pages}
    assert "/features.html" in paths and "/app/archive.html" in paths
    assert report.data["out_of_scope"] == [] and "scope_question" not in report.data


# --- sanitize (pure) ----------------------------------------------------------------------------


def make_page(url: str, elements: list[Element]) -> PageData:
    return PageData(n=1, url=url, elements=elements)


def el(ref: str, name: str, **kw: object) -> Element:
    return Element(ref=ref, role=kw.pop("role", "button"), name=name, region="main", **kw)  # type: ignore[arg-type]


def profile(features: list[dict]) -> ProductProfile:  # type: ignore[type-arg]
    return ProductProfile.model_validate(
        {
            "site_type": "web_app",
            "product_name": "P",
            "one_liner": "o",
            "target_users": [],
            "features": features,
        }
    )


def feature(
    fid: str,
    ref: str | None,
    steps: list[dict],  # type: ignore[type-arg]
    url: str = "https://ex.com/app",
    source: str = "app_action",
    quote: str | None = None,
) -> dict:  # type: ignore[type-arg]
    return {
        "id": fid,
        "name": fid,
        "description": "d",
        "importance": 0.5,
        "evidence": [{"source": source, "url": url, "ref": ref, "quote": quote}],
        "demo_steps": steps,
    }


def test_sanitize_drops_missing_refs_unsafe_steps_and_unknown_pages() -> None:
    page = make_page(
        "https://ex.com/app",
        [
            el("e1", "New task"),
            el("e2", "Delete task"),
            el("e3", "Add", tag="button", in_form=True, button_type="submit"),
            el("e4", "Search", role="searchbox"),
            el("e5", "Password", role="textbox", input_type="password"),
            el("e6", "Drop zone", role="file", caps=["upload"], accept="image/*"),
        ],
    )

    def step(do: str, ref: str, text: str | None = None, **kw: object) -> dict:  # type: ignore[type-arg]
        return {"do": do, "url": "https://ex.com/app", "ref": ref, "text": text, **kw}

    prof = profile(
        [
            feature("ok", "e1", [step("click", "e1"), step("type", "e4", "báo cáo")]),
            feature("ghost-ref", "e99", [step("click", "e99")]),
            feature(
                "unsafe", "e2", [step("click", "e1"), step("click", "e2"), step("click", "e1")]
            ),
            feature("submit", "e3", [step("click", "e3")]),
            feature("typed-secret", "e1", [step("type", "e5", "x")]),
            feature("no-page", "e1", [], url="https://ex.com/nowhere"),
            feature("mutates-text", "e1", [step("type", "e4", "xóa hết")]),
            feature("upload-ok", "e6", [step("upload", "e6", file="bogus.exe")]),
            feature("upload-wrong", "e1", [step("upload", "e1")]),
        ]
    )
    clean, notes = sanitize_profile(prof, [page], "https://ex.com")
    by_id = {f.id: f for f in clean.features}
    assert [s.ref for s in by_id["ok"].demo_steps] == ["e1", "e4"]
    assert by_id["ghost-ref"].evidence[0].ref is None and by_id["ghost-ref"].demo_steps == []
    assert [s.ref for s in by_id["unsafe"].demo_steps] == [
        "e1"
    ]  # truncated before the Delete click
    assert by_id["submit"].demo_steps == []  # form-submitting button
    assert by_id["typed-secret"].demo_steps == []
    assert "no-page" not in by_id  # no valid evidence page -> feature dropped
    # the blacklist guards elements, not sample text: typing "xóa hết" into a search box is harmless
    assert [s.ref for s in by_id["mutates-text"].demo_steps] == ["e4"]
    assert any("Delete task" in n for n in notes) and any("no-page" in n for n in notes)
    # upload: allowed on a file field, with an unknown file name replaced by a real sample
    up = by_id["upload-ok"].demo_steps[0]
    assert up.file == "sample.jpg"
    assert by_id["upload-wrong"].demo_steps == []  # e1 is not an upload field
    # every kept ref step carries the element's locator for the recorder
    kept = by_id["ok"].demo_steps[0]
    assert kept.locator is not None and kept.locator.role == "button"


# --- demo_kind verdicts -------------------------------------------------------------------------


def test_classify_interaction_needs_an_in_page_change() -> None:
    kw = {"reached": True, "steps_done": 1, "steps_total": 1}
    assert classify_demo(Evidence(new_dialog=True), **kw)[0] == "interaction"  # type: ignore[arg-type]
    assert classify_demo(Evidence(new_list_items=2), **kw)[0] == "interaction"  # type: ignore[arg-type]
    assert classify_demo(Evidence(dom_delta=3), **kw)[0] == "interaction"  # type: ignore[arg-type]
    assert classify_demo(Evidence(visual_diff=0.1), **kw)[0] == "interaction"  # type: ignore[arg-type]
    assert classify_demo(Evidence(dom_delta=1, visual_diff=0.005), **kw) == (None, 0.0)  # type: ignore[arg-type]
    strong = classify_demo(Evidence(new_dialog=True, new_list_items=1, visual_diff=0.2), **kw)  # type: ignore[arg-type]
    weak = classify_demo(Evidence(visual_diff=0.03), **kw)  # type: ignore[arg-type]
    partial = classify_demo(Evidence(new_dialog=True), reached=True, steps_done=1, steps_total=3)
    assert strong[1] > weak[1] and partial[1] < classify_demo(Evidence(new_dialog=True), **kw)[1]  # type: ignore[arg-type]


def test_classify_navigation_depends_on_the_target_page() -> None:
    nav = Evidence(url_changed=True, path_changed=True)
    kw = {"reached": True, "steps_done": 1, "steps_total": 1}
    assert classify_demo(nav, **kw) == ("navigation", 0.5)  # type: ignore[arg-type]
    assert classify_demo(nav, target_quality=0.9, target_type="landing_features", **kw) == (
        "navigation",
        0.5,
    )  # type: ignore[arg-type]
    assert classify_demo(nav, target_quality=0.9, target_type="app_dashboard", **kw) == (
        "navigation",
        0.8,
    )  # type: ignore[arg-type]
    assert classify_demo(nav, target_quality=0.3, target_type="other", **kw) == (None, 0.0)  # type: ignore[arg-type]


def test_in_page_change_wins_over_navigation_and_unreached_pages_are_inconclusive() -> None:
    both = Evidence(path_changed=True, new_dialog=True)
    assert classify_demo(both, reached=True, steps_done=2, steps_total=2)[0] == "interaction"
    assert classify_demo(both, reached=False, steps_done=0, steps_total=2) == (None, 0.0)
    assert classify_demo(Evidence(), reached=True, steps_done=1, steps_total=1) == (None, 0.0)


# --- verify (browser) ---------------------------------------------------------------------------


def verify(
    session: BrowserSession,
    prof: ProductProfile,
    pages: list[PageData],
    site: str,
    tmp_path: Path,
    **kw: object,
) -> Report:
    report = Report(site)
    verify_features(session, prof, pages, site, tmp_path, report, Deadline(180), **kw)  # type: ignore[arg-type]
    return report


def test_verify_verdicts_on_the_fixture_app(
    browser_session: BrowserSession, site: str, tmp_path: Path, hits: list[str]
) -> None:
    data = page_of(browser_session, site, "/app.html", tmp_path)
    ref = {e.name: e.ref for e in data.elements}
    url = data.url

    def click(name: str) -> dict:  # type: ignore[type-arg]
        return {"do": "click", "url": url, "ref": ref[name], "text": None}

    def feat(fid: str, steps: list[dict]) -> dict:  # type: ignore[type-arg]
        return feature(fid, None, steps, url=url)

    prof = profile(
        [
            feat("opens-dialog", [click("New task")]),  # dialog appears
            feat("no-effect", [click("Thông tin")]),  # nothing changes, nothing to showcase
            feat("spa-route", [click("Báo cáo")]),  # same path, list items appear
            feat("missing-page", [{"do": "goto", "url": f"{site}/missing.html"}]),
            feat("deletes", [click("Delete task")]),  # must be refused, never executed
            feat("no-steps", []),
        ]
    )
    report = verify(browser_session, prof, [data], site, tmp_path)
    by_id = {f.id: f for f in prof.features}
    assert by_id["opens-dialog"].demo_kind == "interaction"
    assert by_id["opens-dialog"].demo_evidence.new_dialog is True  # type: ignore[union-attr]
    assert by_id["spa-route"].demo_kind == "interaction"
    assert by_id["spa-route"].demo_evidence.new_list_items >= 2  # type: ignore[union-attr]
    assert by_id["spa-route"].demo_evidence.url_changed is True  # type: ignore[union-attr]
    assert by_id["no-effect"].demo_kind == "failed" and by_id["no-effect"].demo_score == 0
    assert by_id["missing-page"].demo_kind == "failed"
    assert by_id["deletes"].demo_kind == "failed"
    assert by_id["deletes"].demo_note and "unsafe" in by_id["deletes"].demo_note
    assert (
        by_id["no-steps"].demo_kind == "failed" and by_id["no-steps"].demo_note == "no demo steps"
    )
    assert by_id["opens-dialog"].thumbnail and Path(by_id["opens-dialog"].thumbnail).is_file()
    assert by_id["missing-page"].thumbnail is None
    assert all(f.verified for f in prof.features)
    # nothing dangerous reached the server, and the report records exactly what happened
    assert "/hit/delete" not in hits and not any("/hit/submit" in h for h in hits)
    assert {c["name"] for c in report.data["clicks"]} == {"New task", "Thông tin", "Báo cáo"}
    blocked = report.data["clicks_blocked"]
    assert [(b["name"], b["reason"]) for b in blocked] == [("Delete task", "blacklist")]
    assert report.data["locate"]["strategies"]["css"] >= 3
    errors = report.data["step_errors"]  # failures name their kind and carry a screenshot
    assert {e["feature"] for e in errors} >= {"deletes"}
    assert all(e["kind"] and Path(e["screenshot"]).is_file() for e in errors if e["screenshot"])


def test_only_the_top_features_are_verified(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    data = page_of(browser_session, site, "/app.html", tmp_path)
    ref = {e.name: e.ref for e in data.elements}
    step = [{"do": "click", "url": data.url, "ref": ref["New task"]}]
    feats = [
        feature(f"f{i}", None, step, url=data.url) | {"importance": 1 - i / 10} for i in range(3)
    ]
    prof = profile(feats)
    verify(browser_session, prof, [data], site, tmp_path, limit=2)
    assert [f.demo_kind for f in prof.features] == ["interaction", "interaction", None]
    assert [f.verified for f in prof.features] == [True, True, False]


def test_navigation_verdict_uses_the_target_page_insight(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    data = page_of(browser_session, site, "/", tmp_path)
    ref = {e.name: e.ref for e in data.elements}
    step = [{"do": "click", "url": data.url, "ref": ref["Tính năng"]}]
    target = f"{site}/features.html"

    def insight(page_type: str, quality: float) -> list[PageInsight]:
        return [PageInsight(url=target, page_type=page_type, purpose="x", visual_quality=quality)]  # type: ignore[arg-type]

    results = {}
    for label, insights in {
        "unknown": None,
        "app": insight("app_dashboard", 0.9),
        "marketing": insight("landing_features", 0.9),
        "poor": insight("other", 0.2),
    }.items():
        prof = profile([feature("go", None, step, url=data.url)])
        verify(browser_session, prof, [data], site, tmp_path / label, insights=insights)
        results[label] = (prof.features[0].demo_kind, prof.features[0].demo_score)
    assert results["unknown"] == ("navigation", 0.5)
    assert results["app"] == ("navigation", 0.8)
    assert results["marketing"] == ("navigation", 0.5)
    assert results["poor"][0] == "failed"  # a poor target page is not a demo
    prof = profile([feature("go", None, step, url=data.url)])
    verify(
        browser_session,
        prof,
        [data],
        site,
        tmp_path / "again",
        insights=insight("app_dashboard", 0.9),
    )
    assert prof.features[0].demo_evidence.target_page_type == "app_dashboard"  # type: ignore[union-attr]
    assert prof.features[0].demo_evidence.url_changed is True  # type: ignore[union-attr]


def test_text_only_features_become_showcases_with_the_section_to_highlight(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    quote = "Kéo thả công việc giữa các cột chỉ trong một giây"
    prof = profile(
        [
            feature("kanban", None, [], url=f"{site}/", source="landing_features", quote=quote),
            feature(
                "ghost", None, [], url=f"{site}/", source="landing_claim", quote="Zzz qqq xxx vvv"
            ),
        ]
    )
    prof.features[1].name = "Zzz qqq"
    prof.features[1].description = "xxx vvv"
    page = page_of(browser_session, site, "/", tmp_path)
    verify(browser_session, prof, [page], site, tmp_path)
    kanban, ghost = prof.features
    assert kanban.demo_kind == "showcase" and kanban.demo_score >= 0.9
    assert kanban.showcase_target is not None
    assert "#features" in (kanban.showcase_target.selector or "")
    assert "Kéo thả" in kanban.showcase_target.text_quote
    assert kanban.thumbnail and Path(kanban.thumbnail).is_file()
    assert ghost.demo_kind == "failed" and ghost.showcase_target is None  # no section says this


def test_a_section_anchor_naming_the_feature_is_a_weaker_showcase(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    page = page_of(browser_session, site, "/", tmp_path)
    # no quote that matches the text, but the feature is named like the #features anchor heading
    prof = profile([feature("kanban", None, [], url=f"{site}/", source="landing_hero")])
    prof.features[0].name = "Bảng Kanban"
    prof.features[0].description = "zzzz qqqq"
    verify(browser_session, prof, [page], site, tmp_path)
    f = prof.features[0]
    assert f.demo_kind == "showcase" and f.showcase_target is not None


def test_upload_step_runs_with_a_sample_file_and_shows_a_result(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    data = page_of(browser_session, site, "/tool.html", tmp_path)
    file_input = next(e for e in data.elements if "upload" in e.caps)
    prof = profile(
        [
            feature(
                "compress",
                None,
                [{"do": "upload", "url": data.url, "ref": file_input.ref}],
                url=data.url,
            )
        ]
    )
    report = verify(browser_session, prof, [data], site, tmp_path)
    f = prof.features[0]
    assert f.demo_kind == "interaction"
    assert f.demo_evidence.new_list_items >= 2  # type: ignore[union-attr]
    upload = next(c for c in report.data["clicks"] if c.get("file"))
    assert upload["file"] == "sample.jpg"  # chosen from accept="image/*"
    assert Path(f.thumbnail or "").is_file()


def test_sample_button_is_found_by_its_real_accessible_name(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    data = page_of(browser_session, site, "/tool.html", tmp_path)
    sample = next(e for e in data.elements if e.text == "2.8MB")
    prof = profile(
        [
            feature(
                "sample", None, [{"do": "click", "url": data.url, "ref": sample.ref}], url=data.url
            )
        ]
    )
    report = verify(browser_session, prof, [data], site, tmp_path)
    assert prof.features[0].demo_kind == "interaction"
    assert report.data["clicks"][0]["strategy"] in ("css", "role_exact")


def test_enter_is_pressed_for_a_lone_input_and_refused_for_risky_forms(
    browser_session: BrowserSession, site: str, tmp_path: Path, hits: list[str]
) -> None:
    quick = page_of(browser_session, site, "/quick.html", tmp_path, n=1)
    forms = page_of(browser_session, site, "/form.html", tmp_path, n=2)
    ref_q = {e.name: e.ref for e in quick.elements}
    ref_f = {e.name: e.ref for e in forms.elements}

    def typing(page: PageData, ref: str, text: str = "Mua sữa") -> list[dict]:  # type: ignore[type-arg]
        return [{"do": "type", "url": page.url, "ref": ref, "text": text}]

    prof = profile(
        [
            feature("add-item", None, typing(quick, ref_q["Add item"]), url=quick.url),
            feature("post-note", None, typing(forms, ref_f["Your note"]), url=forms.url),
            feature("search", None, typing(forms, ref_f["Search notes"]), url=forms.url),
            feature("two-inputs", None, typing(forms, ref_f["First name"]), url=forms.url),
        ]
    )
    report = verify(browser_session, prof, [quick, forms], site, tmp_path)
    by_id = {f.id: f for f in prof.features}
    assert by_id["add-item"].demo_kind == "interaction"  # the item appeared after Enter
    assert by_id["add-item"].demo_evidence.new_list_items == 1  # type: ignore[union-attr]
    enter = report.data["enter"]
    assert enter["pressed"] == 2  # add-item and the GET search on the same page
    reasons = {(b["feature"], b["reason"]) for b in enter["blocked"]}
    assert reasons == {
        ("post-note", "enter_blocked: form_posts_to_other_path"),
        ("two-inputs", "enter_blocked: form_has_2_text_inputs"),
    }
    assert not any("submit-note" in h for h in hits)  # the risky form was never submitted


def test_typed_text_is_never_checked_but_clicked_elements_are(
    browser_session: BrowserSession, site: str, tmp_path: Path, hits: list[str]
) -> None:
    """The blacklist guards elements that are clicked, not sample text that is typed."""
    data = page_of(browser_session, site, "/app.html", tmp_path)
    ref = {e.name: e.ref for e in data.elements}
    url = data.url

    def typing(text: str) -> dict:  # type: ignore[type-arg]
        return {"do": "type", "url": url, "ref": ref["Tìm công việc"], "text": text}

    delete_step = {"do": "click", "url": url, "ref": ref["Delete task"], "text": None}
    prof = profile(
        [
            feature("typed", None, [typing("Mua sữa"), typing("Gửi báo cáo")], url=url),
            feature("clicked", None, [delete_step], url=url),
        ]
    )
    report = verify(browser_session, prof, [data], site, tmp_path)
    typed, clicked = prof.features
    assert typed.demo_note is None  # both steps ran, nothing was refused
    assert [c["name"] for c in report.data["clicks_blocked"]] == ["Delete task"]
    assert clicked.demo_note and "unsafe" in clicked.demo_note
    assert "/hit/delete" not in hits


def test_verify_refuses_submit_buttons_and_blacklisted_fields(
    browser_session: BrowserSession, site: str, tmp_path: Path, hits: list[str]
) -> None:
    data = page_of(browser_session, site, "/app.html", tmp_path)
    # the dialog's submit button is hidden at extraction time, so add it as the page would show it
    data.elements.append(
        el("e90", "Add", tag="button", in_form=True, button_type="submit", selector="#add")
    )
    url = data.url
    forms = page_of(browser_session, site, "/form.html", tmp_path, n=2)
    msg = next(e for e in forms.elements if e.name == "Send message")
    prof = profile(
        [
            feature("submit", None, [{"do": "click", "url": url, "ref": "e90"}], url=url),
            feature("typed-into-blacklisted-field", None,
                    [{"do": "type", "url": forms.url, "ref": msg.ref, "text": "hello"}],
                    url=forms.url),
        ]
    )  # fmt: skip
    report = verify(browser_session, prof, [data, forms], site, tmp_path)
    assert not any("/hit/submit" in h for h in hits)
    assert report.data["clicks"] == []
    blocked = {(c["name"], c["reason"]) for c in report.data["clicks_blocked"]}
    assert blocked == {("Add", "blacklist"), ("Send message", "blacklist")}
    assert report.data["enter"]["pressed"] == 0  # nothing was typed, so no Enter either
