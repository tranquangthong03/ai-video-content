"""Explorer tests against the local fixture site (needs Playwright Chromium, no network, no LLM)."""

from pathlib import Path

import pytest

from app.explorer.browser import BrowserSession, detect_blockers, dismiss_cookie_banner
from app.explorer.extract import extract_page
from app.explorer.mapper import (
    Candidate,
    Frontier,
    candidates_from_links,
    crawl,
    normalize_url,
    pick_candidates_by_description,
    score_candidate,
)
from app.explorer.models import Element, PageData
from app.explorer.report import Deadline, Report
from app.explorer.synthesize import sanitize_profile
from app.explorer.verify import FeatureRun, compute_demo_score, verify_features
from app.schemas.generated.product_profile import ProductProfile

# --- mapper (pure) ------------------------------------------------------------------------------


def test_normalize_url() -> None:
    assert normalize_url("/a/?utm_source=x&b=1#top", "https://Ex.com/") == "https://ex.com/a?b=1"
    assert normalize_url("https://ex.com/#/active") == "https://ex.com/#/active"  # hash route kept
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


def test_candidates_drop_blacklisted_offsite_and_skip_reason_is_reported() -> None:
    report = Report("https://ex.com")
    raw = [
        {"href": "https://ex.com/features", "text": "Features", "region": "nav", "visible": True},
        {
            "href": "https://ex.com/account/delete",
            "text": "Account",
            "region": "nav",
            "visible": True,
        },
        {"href": "https://ex.com/p", "text": "Buy now", "region": "nav", "visible": True},
        {"href": "https://ex.com/logout", "text": "Out", "region": "footer", "visible": True},
        {"href": "https://other.com/x", "text": "Elsewhere", "region": "nav", "visible": True},
    ]
    found = candidates_from_links(raw, "https://ex.com/", "https://ex.com", 1, report)
    assert [c.url for c in found] == ["https://ex.com/features"]
    reasons = " ".join(s["reason"] for s in report.data["pages_skipped"])
    assert "Buy now" in reasons and "logout" in reasons and "delete" in reasons


def test_frontier_pops_best_first_and_never_twice() -> None:
    f = Frontier()
    f.add(Candidate("https://ex.com/low", "", "footer", 1, 0.2))
    f.add(Candidate("https://ex.com/high", "", "nav", 1, 5.0))
    f.add(Candidate("https://ex.com/high", "", "nav", 1, 4.0))  # lower duplicate ignored
    assert [f.pop().url, f.pop().url, f.pop()] == [
        "https://ex.com/high",
        "https://ex.com/low",
        None,
    ]  # type: ignore[union-attr]


def test_pick_candidates_by_description() -> None:
    cands = [
        {"url": "https://ex.com/reports", "text": "Báo cáo", "score": 1.0},
        {"url": "https://ex.com/settings", "text": "Cài đặt", "score": 3.0},
    ]
    assert pick_candidates_by_description(cands, [], "xem trang báo cáo reports") == [
        "https://ex.com/reports"
    ]
    assert pick_candidates_by_description(cands, ["https://ex.com/reports"], "reports") == []


# --- browser-driven -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def session(site: str):  # type: ignore[no-untyped-def]
    with BrowserSession(site) as s:
        yield s


def test_extract_assigns_stable_refs_and_stable_selectors(
    session: BrowserSession, site: str, tmp_path: Path
) -> None:
    def extract() -> PageData:
        ctx = session.new_context()
        page = ctx.new_page()
        page.goto(f"{site}/app.html")
        data = extract_page(page, 1, tmp_path)
        ctx.close()
        return data

    first, second = extract(), extract()
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


def test_hidden_dialog_fields_are_not_extracted(
    session: BrowserSession, site: str, tmp_path: Path
) -> None:
    ctx = session.new_context()
    page = ctx.new_page()
    page.goto(f"{site}/app.html")
    names = {e.name for e in extract_page(page, 1, tmp_path).elements}
    ctx.close()
    assert "Task title" not in names and "Add" not in names


def test_cookie_banner_is_dismissed_by_button_or_hidden(session: BrowserSession) -> None:
    ctx = session.new_context()
    page = ctx.new_page()
    page.set_content(
        '<div id="cookie-banner"><button onclick="this.parentElement.remove()">Accept all</button></div><p>x</p>'
    )
    assert dismiss_cookie_banner(page) is True
    assert page.locator("#cookie-banner").count() == 0
    page.set_content('<div class="cookie-wall">Nothing to click</div><p>x</p>')
    assert dismiss_cookie_banner(page) is False
    assert not page.locator(".cookie-wall").is_visible()
    ctx.close()


def test_detect_blockers(session: BrowserSession) -> None:
    ctx = session.new_context()
    page = ctx.new_page()
    page.set_content('<title>Sign in</title><input type="password">')
    assert detect_blockers(page, 200) == {"needs_login": True, "captcha": False, "http_error": None}
    page.set_content("<title>Just a moment...</title><p>Checking</p>")
    blockers = detect_blockers(page, 403)
    assert blockers["captcha"] is True and blockers["http_error"] == 403
    ctx.close()


def test_crawl_visits_important_pages_first_and_never_blacklisted_ones(
    session: BrowserSession, site: str, tmp_path: Path, hits: list[str]
) -> None:
    ctx = session.new_context()
    report = Report(site)
    pages, _ = crawl(ctx.new_page(), ctx, site, tmp_path, report, Deadline(120), max_pages=6)
    ctx.close()
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
    # the SPA nav click on the fixture (aside > Báo cáo) was recorded
    assert any(c["name"] == "Báo cáo" for c in report.data["clicks"])
    assert not any(c["name"] in ("Delete", "Delete task") for c in report.data["clicks"])


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
        }  # fmt: skip
    )


def feature(fid: str, ref: str | None, steps: list[dict], url: str = "https://ex.com/app") -> dict:  # type: ignore[type-arg]
    return {
        "id": fid, "name": fid, "description": "d", "importance": 0.5,
        "evidence": [{"source": "app_action", "url": url, "ref": ref, "quote": None}],
        "demo_steps": steps,
    }  # fmt: skip


def test_sanitize_drops_missing_refs_unsafe_steps_and_unknown_pages() -> None:
    page = make_page(
        "https://ex.com/app",
        [
            el("e1", "New task"),
            el("e2", "Delete task"),
            el("e3", "Add", tag="button", in_form=True, button_type="submit"),
            el("e4", "Search", role="searchbox"),
            el("e5", "Password", role="textbox", input_type="password"),
        ],
    )

    def step(do: str, ref: str, text: str | None = None) -> dict:  # type: ignore[type-arg]
        return {"do": do, "url": "https://ex.com/app", "ref": ref, "text": text}

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


# --- verify -------------------------------------------------------------------------------------


def test_demo_score_levels() -> None:
    assert compute_demo_score(FeatureRun(reached=False, steps_total=2)) == 0.0
    assert (
        compute_demo_score(FeatureRun(reached=True, steps_total=2, steps_done=2, any_change=True))
        == 1.0
    )
    assert (
        compute_demo_score(FeatureRun(reached=True, steps_total=2, steps_done=2, any_change=False))
        == 0.5
    )
    assert (
        compute_demo_score(FeatureRun(reached=True, steps_total=2, steps_done=1, any_change=True))
        == 0.5
    )


def app_page(session: BrowserSession, site: str, tmp_path: Path) -> PageData:
    ctx = session.new_context()
    page = ctx.new_page()
    page.goto(f"{site}/app.html")
    data = extract_page(page, 1, tmp_path)
    ctx.close()
    return data


def test_verify_scores_features_and_never_clicks_delete_or_submit(
    session: BrowserSession, site: str, tmp_path: Path, hits: list[str]
) -> None:
    data = app_page(session, site, tmp_path)
    ref = {e.name: e.ref for e in data.elements}
    url = data.url

    def feat(fid: str, steps: list[dict]) -> dict:  # type: ignore[type-arg]
        return feature(fid, None, steps, url=url) | {"importance": 0.5}

    def click(name: str) -> dict:  # type: ignore[type-arg]
        return {"do": "click", "url": url, "ref": ref[name], "text": None}

    prof = profile(
        [
            feat("opens-dialog", [click("New task")]),  # dialog appears -> clear change
            feat("no-effect", [click("Thông tin")]),  # nothing changes -> page reached only
            feat("spa-route", [click("Báo cáo")]),  # URL + heading change
            feat(
                "missing-page",
                [{"do": "goto", "url": f"{site}/missing.html", "ref": None, "text": None}],
            ),
            feat("deletes", [click("Delete task")]),  # must be refused, never executed
            feat("no-steps", []),
        ]
    )
    report = Report(site)
    verify_features(session, prof, [data], site, tmp_path, report, Deadline(120))
    score = {f.id: f.demo_score for f in prof.features}
    assert score["opens-dialog"] == 1.0
    assert score["no-effect"] == 0.5
    assert score["spa-route"] == 1.0
    assert score["missing-page"] == 0.0
    assert score["deletes"] == 0.5  # page reached, the unsafe step refused
    by_id = {f.id: f for f in prof.features}
    assert by_id["deletes"].demo_note and "stopped" in by_id["deletes"].demo_note
    assert by_id["opens-dialog"].thumbnail and Path(by_id["opens-dialog"].thumbnail).is_file()
    assert by_id["missing-page"].thumbnail is None
    assert by_id["no-steps"].verified and by_id["no-steps"].demo_note == "no demo steps"
    # nothing dangerous ever reached the server, and the report proves what was (not) clicked
    assert "/hit/delete" not in hits and not any("/hit/submit" in h for h in hits)
    clicked = {c["name"] for c in report.data["clicks"]}
    assert clicked == {"New task", "Thông tin", "Báo cáo"}
    assert [c["name"] for c in report.data["clicks_blocked"]] == ["Delete task"]


def test_verify_refuses_submit_buttons_and_blacklisted_fields(
    session: BrowserSession, site: str, tmp_path: Path, hits: list[str]
) -> None:
    data = app_page(session, site, tmp_path)
    # the dialog fields are hidden at extraction time, so add them as the page would show them
    data.elements += [
        Element(ref="e90", role="button", name="Add", region="main", tag="button", in_form=True,
                button_type="submit", selector="#add"),
        Element(ref="e91", role="textbox", name="Send message", region="main", tag="input",
                input_type="text", selector="#title"),
    ]  # fmt: skip
    url = data.url
    prof = profile(
        [
            feature(
                "submit", None, [{"do": "click", "url": url, "ref": "e90", "text": None}], url=url
            ),
            feature(
                "typed-into-blacklisted-field",
                None,
                [{"do": "type", "url": url, "ref": "e91", "text": "hello"}],
                url=url,
            ),
        ]
    )
    report = Report(site)
    verify_features(session, prof, [data], site, tmp_path, report, Deadline(120))
    assert not any("/hit/submit" in h for h in hits)
    assert {c["name"] for c in report.data["clicks_blocked"]} == {"Add", "Send message"}
    assert report.data["clicks"] == []


def test_verify_types_blacklist_words_but_still_blocks_blacklisted_elements(
    session: BrowserSession, site: str, tmp_path: Path, hits: list[str]
) -> None:
    """The blacklist guards elements that are clicked, not sample text that is typed."""
    data = app_page(session, site, tmp_path)
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
    report = Report(site)
    verify_features(session, prof, [data], site, tmp_path, report, Deadline(120))
    typed, clicked = prof.features
    assert typed.demo_note is None  # both steps ran, nothing was refused
    assert [c["name"] for c in report.data["clicks_blocked"]] == ["Delete task"]
    assert clicked.demo_note and "stopped" in clicked.demo_note
    assert "/hit/delete" not in hits
