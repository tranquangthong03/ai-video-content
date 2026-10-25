from pathlib import Path

from app.browser.session import BrowserSession
from app.explorer.mapper import (
    description_words,
    explore_targeted,
    pick_candidates_by_description,
    relevance,
    words_match,
)
from app.explorer.report import Report
from app.explorer.synthesize import synthesize
from app.llm.json_call import JsonCaller
from app.pipeline.explore_run import merge_profiles
from app.schemas.generated.page_insight import PageInsight
from tests.conftest import FakeLLM
from tests.test_explorer import feature, page_of, profile

CANDIDATES = [
    {"url": "https://ex.com/learning-paths", "text": "Learning Paths", "score": 1.0},
    {"url": "https://ex.com/lo-trinh", "text": "Lộ trình theo vai trò", "score": 1.0},
    {"url": "https://ex.com/pricing", "text": "Bảng giá", "score": 5.0},
    {"url": "https://ex.com/login", "text": "Đăng nhập học viên", "score": 9.0},
    {"url": "https://ex.com/checkout", "text": "Lộ trình thanh toán", "score": 9.0},
]


def test_fuzzy_words_ignore_accents_plural_and_typos() -> None:
    assert description_words("Lộ trình học theo vai trò") == {"trinh", "hoc", "vai", "tro"}
    assert words_match("path", "paths") and words_match("learn", "learning")
    assert words_match("recomendation", "recommendation")  # one missing letter
    assert not words_match("report", "export")


def test_description_with_english_and_vietnamese_finds_both_links() -> None:
    picked = pick_candidates_by_description(
        CANDIDATES, [], "Lộ trình học theo vai trò (Learning Paths)"
    )
    assert set(picked[:2]) == {"https://ex.com/learning-paths", "https://ex.com/lo-trinh"}
    assert (
        relevance("Lo trinh vai tro", "Lộ trình theo vai trò", "https://ex.com/x") == 3
    )  # accents off


def test_side_pages_are_never_picked_even_when_the_words_match() -> None:
    picked = pick_candidates_by_description(CANDIDATES, [], "đăng nhập lộ trình thanh toán")
    assert "https://ex.com/login" not in picked and "https://ex.com/checkout" not in picked
    assert picked == ["https://ex.com/lo-trinh"]


def test_visited_pages_are_not_picked_again() -> None:
    assert pick_candidates_by_description(CANDIDATES, [c["url"] for c in CANDIDATES], "paths") == []


def test_targeted_exploration_starts_at_the_url_and_stays_under_its_prefix(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    ctx = browser_session.new_context()
    report = Report(site)
    pages = explore_targeted(
        ctx.new_page(), [site + "/app/"], site + "/", tmp_path, report, first_n=5
    )
    ctx.close()
    paths = [p.url.removeprefix(site) for p in pages]
    assert paths[0].startswith("/app") and len(paths) <= 3
    assert all(p.startswith("/app") for p in paths)  # prefix of the first seed
    assert [p.n for p in pages] == list(range(5, 5 + len(pages)))


def test_targeted_exploration_by_description_goes_to_the_matching_link(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    ctx = browser_session.new_context()
    seeds = pick_candidates_by_description(
        [
            {"url": site + "/pricing.html", "text": "Giá", "score": 1.0},
            {"url": site + "/features.html", "text": "Tính năng", "score": 1.0},
        ],
        [],
        "xem trang giá cả",
    )
    pages = explore_targeted(
        ctx.new_page(),
        seeds,
        site + "/",
        tmp_path,
        Report(site),
        first_n=2,
        description="giá",
    )
    ctx.close()
    assert seeds == [site + "/pricing.html"]
    assert pages[0].url.endswith("/pricing.html") and len(pages) <= 3
    assert not any("logout" in p.url or "delete" in p.url for p in pages)  # blacklist holds


def test_synthesize_for_new_pages_lists_existing_features_and_asks_to_reuse_keys(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    seen: list[str] = []

    def handler(prompt: str) -> dict:  # type: ignore[type-arg]
        seen.append(prompt)
        return {
            "site_type": "web_app",
            "product_name": "P",
            "one_liner": "o",
            "target_users": [],
            "features": [],
        }

    page = page_of(browser_session, site, "/features.html", tmp_path)
    insight = PageInsight(
        url=page.url,
        title=page.title,
        page_type="landing_features",
        purpose="p",
        visual_quality=0.5,
    )
    old = profile([{**feature("create_item_f", None, []), "intent_key": "create_item"}])
    caller = JsonCaller(FakeLLM(handler), cache_dir=tmp_path / "c")
    synthesize(caller, site, "web_app", [page], [insight], Report(site), existing=old)
    prompt = seen[0]
    assert "<existing_features>" in prompt and "[create_item]" in prompt
    synthesize(caller, site, "web_app", [page], [insight], Report(site))
    assert "<existing_features>" not in seen[1] and "intent_key" in seen[1]


def test_merge_profiles_skips_new_features_with_the_same_intent_or_name() -> None:
    old = profile([{**feature("add", None, []), "name": "Tạo việc", "intent_key": "create_item"}])
    new = profile(
        [
            {
                **feature("n1", None, []),
                "name": "Thêm công việc nhanh",
                "intent_key": "create_item",
            },
            {**feature("n2", None, []), "name": "TAO VIEC"},
            {**feature("n3", None, []), "name": "Lộ trình theo vai trò", "intent_key": "paths"},
        ]
    )
    merged = merge_profiles(old, new)
    assert [f.id for f in merged.features] == ["add", "n3"]
