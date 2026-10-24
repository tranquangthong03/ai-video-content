"""Demo links in the mapper and the quality of showcase_target."""

from pathlib import Path

from app.browser.session import BrowserSession
from app.browser.urls import related_domain
from app.explorer.mapper import (
    candidates_from_links,
    is_auth_url,
    is_demo_like,
    score_candidate,
)
from app.explorer.report import Report
from app.explorer.verify import find_showcase
from tests.test_explorer import feature, link, page_of, profile

ROOT = "https://ex.com"


def many_nav_links() -> list[dict]:  # type: ignore[type-arg]
    """Enough nav links that main-region links would normally be ignored."""
    return [link(f"https://ex.com/p{i}", f"Page {i}") for i in range(4)]


def candidates(extra: list[dict]) -> dict[str, object]:  # type: ignore[type-arg]
    found = candidates_from_links([*many_nav_links(), *extra], f"{ROOT}/", ROOT, 1, Report(ROOT))
    return {c.url: c for c in found}


def test_main_region_demo_links_are_kept_when_there_is_a_nav() -> None:
    found = candidates(
        [
            link("https://ex.com/live", "View live demo", "main"),
            link("https://ex.com/trial", "Try it free", "main"),
            link("https://ex.com/play", "Playground", "main"),
            link("https://ex.com/dung-thu", "Dùng thử miễn phí", "main"),
            link("https://ex.com/ui", "Trải nghiệm ngay", "main"),
            link(
                "https://ex.com/about", "About us", "main"
            ),  # an ordinary main link is still dropped
        ]
    )
    for path in ("live", "trial", "play", "dung-thu", "ui"):
        assert f"https://ex.com/{path}" in found, path
    assert "https://ex.com/about" not in found
    assert found["https://ex.com/live"].demo is True  # type: ignore[attr-defined]


def test_a_demo_link_may_live_on_a_subdomain_of_the_root_domain() -> None:
    found = candidates(
        [
            link("https://demo.ex.com/dashboard", "Live demo", "main"),
            link("https://blog.ex.com/post", "Read our blog", "nav"),  # not a demo: other site
            link("https://other.com/demo", "Live demo", "main"),  # different domain entirely
        ]
    )
    assert "https://demo.ex.com/dashboard" in found
    assert not any("blog.ex.com" in u or "other.com" in u for u in found)
    assert related_domain("https://demo.ex.com", ROOT) and not related_domain(
        "https://ex.org", ROOT
    )


def test_auth_pages_never_take_a_demo_slot() -> None:
    for path in ("/login", "/signin", "/register", "/signup", "/auth/callback", "/log-in"):
        url = f"https://ex.com{path}"
        assert is_auth_url(url), path
        assert is_demo_like(url, "Get started") is False, path
        assert score_candidate(url, "nav", 1, text="Try the demo") == score_candidate(url, "nav", 1)
    assert is_demo_like("https://ex.com/demo", "") is True
    assert is_demo_like("https://ex.com/x", "Live demo") is True
    found = candidates([link("https://ex.com/register", "Get started", "main")])
    assert "https://ex.com/register" not in found  # not a demo link, and a main link otherwise
    nav = candidates_from_links(
        [*many_nav_links(), link("https://ex.com/login", "Try for free", "nav")],
        f"{ROOT}/", ROOT, 1, Report(ROOT),
    )  # fmt: skip
    login = next(c for c in nav if c.url.endswith("/login"))
    assert login.demo is False  # still a normal page, just not a demo candidate


# --- showcase_target ----------------------------------------------------------------------------


def showcase(session: BrowserSession, site: str, tmp_path: Path, quote: str):  # type: ignore[no-untyped-def]
    page = page_of(session, site, "/marketing.html", tmp_path)
    prof = profile(
        [
            feature(
                "f", None, [], url=f"{site}/marketing.html", source="landing_features", quote=quote
            )
        ]
    )
    return find_showcase(session, prof.features[0], {page.url: page}, tmp_path)


def test_showcase_skips_toc_footer_and_tiny_blocks(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    # the quote appears in the TOC, in the footer, in a small paragraph and in a real section
    found = showcase(browser_session, site, tmp_path, "Báo cáo tự động theo tuần")
    assert found is not None
    target, score, shot = found
    assert "#reports" in (target.selector or "")  # the section with heading + paragraph
    assert "toc" not in (target.selector or "") and "footer" not in (target.selector or "")
    assert "nav" not in (target.selector or "").split(" > ")
    assert score >= 0.6 and Path(shot).is_file()
    assert "Báo cáo tự động" in target.text_quote  # heading + text for the highlight caption


def test_showcase_takes_the_block_around_a_matching_heading(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    # "Xuất dữ liệu CSV" is a small h3 inside a short div: the usable block is the section
    found = showcase(browser_session, site, tmp_path, "Xuất dữ liệu CSV")
    assert found is not None
    assert "#export" in (found[0].selector or "")


def test_showcase_returns_nothing_when_only_navigation_matches(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    page = page_of(browser_session, site, "/marketing.html", tmp_path)
    # exists only in the TOC and the footer
    prof = profile(
        [feature("f", None, [], url=page.url, source="landing_features",
                 quote="tự động theo tuần, xuất dữ liệu CSV")]
    )  # fmt: skip
    found = find_showcase(browser_session, prof.features[0], {page.url: page}, tmp_path)
    # the whole quote only exists in the TOC and the footer (each real section has half of it),
    # and navigation blocks are never highlighted
    assert found is None
    ghost = profile(
        [feature("g", None, [], url=page.url, source="landing_features", quote="zzz qqq www eee")]
    )
    assert find_showcase(browser_session, ghost.features[0], {page.url: page}, tmp_path) is None
