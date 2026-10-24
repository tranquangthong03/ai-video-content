from pathlib import Path

import pytest
from PIL import Image

from app.browser.session import BrowserSession
from app.script.theme import (
    FALLBACK_PRIMARY,
    contrast_ratio,
    derive_theme,
    dominant_from_image,
    hex_to_rgb,
    highlight_color,
    hue_gap,
    is_neutral,
    opposite_hue,
    parse_css_color,
    rank_css_colors,
)

# --- color helpers --------------------------------------------------------------------------------


def test_parse_css_color_forms() -> None:
    assert parse_css_color("rgb(225, 29, 72)") == ((225, 29, 72), 1.0)
    assert parse_css_color("rgba(0, 0, 0, 0)") == ((0, 0, 0), 0.0)
    assert parse_css_color("rgba(1, 2, 3, 0.5)") == ((1, 2, 3), 0.5)
    assert parse_css_color("#0ea5e9") == ((14, 165, 233), 1.0)
    assert parse_css_color("#fff") == ((255, 255, 255), 1.0)
    assert parse_css_color("transparent") is None and parse_css_color(None) is None


def test_neutral_colors_are_not_brand_colors() -> None:
    for neutral in ((255, 255, 255), (0, 0, 0), (107, 114, 128), (17, 17, 17), (250, 250, 252)):
        assert is_neutral(neutral), neutral
    for brand in ((225, 29, 72), (79, 70, 229), (14, 165, 233), (251, 191, 36)):
        assert not is_neutral(brand), brand


def test_highlight_color_matches_the_typescript_implementation() -> None:
    expected = {
        "#1E3A8A": "#5779db",
        "#4F46E5": "#756eeb",
        "#FBBF24": "#fbbf24",
        "#0F766E": "#128d83",
        "#B91C1C": "#e34444",
        "#111827": "#637fbb",
    }
    for primary, out in expected.items():
        assert highlight_color(primary) == out, primary
        assert contrast_ratio(out, "#0B1426") >= 4.5


def test_opposite_hue_is_far_from_the_primary() -> None:
    for primary in ("#E11D48", "#4F46E5", "#10B981"):
        accent = opposite_hue(primary)
        assert hue_gap(hex_to_rgb(primary), hex_to_rgb(accent)) > 150


def test_rank_css_colors_groups_shades_drops_neutrals_and_background() -> None:
    data = {
        "page_bg": ["rgb(255, 255, 255)", "rgba(0, 0, 0, 0)"],
        "buttons": [
            {"color": "rgb(225, 29, 72)", "area": 1000},
            {"color": "rgb(226, 30, 73)", "area": 1000},  # same brand color, a shade away
            {"color": "rgb(107, 114, 128)", "area": 9999},  # grey
            {"color": "rgba(14, 165, 233, 0.2)", "area": 9999},  # translucent
            {"color": "rgb(255, 255, 255)", "area": 9999},
        ],
        "links": [{"color": "rgb(14, 165, 233)", "area": 3000}],
    }
    ranked = rank_css_colors(data)
    assert [r["color"] for r in ranked] == ["#e11d48", "#0ea5e9"]
    assert ranked[0]["area"] == 2000 and ranked[1]["area"] == 990  # links count for a third


def test_background_colored_buttons_are_not_picked() -> None:
    data = {
        "page_bg": ["rgb(11, 20, 38)"],
        "buttons": [{"color": "rgb(12, 22, 40)", "area": 5000}],
        "links": [],
    }
    assert rank_css_colors(data) == []


def test_dominant_from_image_skips_background_neutrals_and_media(tmp_path: Path) -> None:
    img = Image.new("RGB", (1920, 1080), "white")
    img.paste((124, 58, 237), (0, 0, 1920, 160))  # purple header
    img.paste((249, 115, 22), (100, 180, 1400, 500))  # big orange photo
    without_media = dominant_from_image(img, (1920, 1080), [])
    with_media = dominant_from_image(img, (1920, 1080), [{"x": 100, "y": 180, "w": 1300, "h": 320}])
    assert without_media is not None and with_media is not None
    assert hue_gap(hex_to_rgb(with_media), (124, 58, 237)) < 15  # purple once the photo is excluded
    assert hue_gap(hex_to_rgb(without_media), (249, 115, 22)) < 15  # the photo wins otherwise
    assert dominant_from_image(Image.new("RGB", (1920, 1080), "white"), (1920, 1080), []) is None


# --- derive_theme on fixture sites -------------------------------------------------------------


def derive(session: BrowserSession, site: str, path: str, tmp_path: Path):  # type: ignore[no-untyped-def]
    return derive_theme(session, f"{site}{path}", tmp_path)


def test_primary_comes_from_the_main_button_and_accent_from_the_nav_links(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    result = derive(browser_session, site, "/brand_css.html", tmp_path)
    assert result.source == "css" and result.theme.primary == "#E11D48"
    assert result.accent_source == "css" and result.theme.accent == "#0EA5E9"
    report = result.report()
    assert report["source"] == "css" and report["highlight"] == highlight_color("#E11D48")
    assert report["candidates"][0]["color"] == "#e11d48"
    assert result.theme.font == "Be Vietnam Pro" and result.theme.caption_style == "karaoke"


def test_the_header_logo_is_saved(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    result = derive(browser_session, site, "/brand_css.html", tmp_path)
    assert result.logo_path is not None and result.logo_path.suffix == ".svg"
    assert result.logo_path.read_text().startswith("<svg")
    assert result.theme.logo_asset == str(result.logo_path)


def test_meta_theme_color_wins_and_the_accent_is_the_opposite_hue(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    result = derive(browser_session, site, "/brand_meta.html", tmp_path)
    assert result.source == "meta" and result.theme.primary == "#10B981"
    # the red button is a brand color too and has a different hue: it becomes the accent
    assert result.accent_source == "css" and result.theme.accent == "#E11D48"


def test_a_white_meta_theme_color_is_ignored(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    result = derive(browser_session, site, "/brand_meta_white.html", tmp_path)
    assert result.source == "css" and result.theme.primary == "#7C3AED"
    assert result.accent_source == "opposite_hue"


def test_screenshot_is_used_when_css_has_no_brand_color_and_media_is_ignored(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    result = derive(browser_session, site, "/brand_shot.html", tmp_path)
    assert result.source == "screenshot"
    assert (
        hue_gap(hex_to_rgb(result.theme.primary), (124, 58, 237)) < 15
    )  # purple header, not the orange photo


def test_fallback_when_nothing_has_a_brand_color(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    result = derive(browser_session, site, "/brand_gray.html", tmp_path)
    assert result.source == "fallback" and result.theme.primary == FALLBACK_PRIMARY
    assert result.notes


def test_an_unreachable_site_falls_back_without_raising(
    browser_session: BrowserSession, tmp_path: Path
) -> None:
    result = derive_theme(browser_session, "http://127.0.0.1:9/nothing", tmp_path)
    assert result.source == "fallback" and any("không mở lại" in n for n in result.notes)


@pytest.mark.parametrize("primary", ["#1E3A8A", "#4F46E5", "#FBBF24"])
def test_highlight_never_goes_below_the_contrast_floor(primary: str) -> None:
    assert contrast_ratio(highlight_color(primary), "#0B1426") >= 4.5
