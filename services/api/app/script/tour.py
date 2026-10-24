"""Landing-only products: a tour of the page, one different section per demo scene.

When no feature of the product can be operated (no interaction / navigation), every feature_demo
becomes a showcase of the next section of the page, in page order, never the same one twice.
"""

from typing import Any

from app.schemas.generated.product_profile import ProductProfile
from app.script.home import Section, hero_locator, section_actions, sections
from app.script.lite import LiteContext


def is_landing_only(profile: ProductProfile) -> bool:
    return not any(f.demo_kind in ("interaction", "navigation") for f in profile.features)


def tour_stops(lite: LiteContext) -> list[Section]:
    """Sections of the home page first, then of the other explored pages, in page order."""
    hero = hero_locator(lite.pages, lite.home_url)
    skip = {hero["text"].lower()} if hero else set()  # the hook already shows the hero
    stops: list[Section] = []
    home_key = next((k for k in lite.pages.pages if k == lite.pages.key(lite.home_url)), None)
    order = ([home_key] if home_key else []) + [k for k in lite.pages.pages if k != home_key]
    for key in order:
        stops += [
            s for s in sections(lite.pages, lite.pages.pages[key].get("url") or key)
            if s.text.lower() not in skip
        ]  # fmt: skip
    return stops


def apply_tour(scenes: list[dict[str, Any]], lite: LiteContext, warnings: list[str]) -> None:
    """Give each feature_demo scene its own section (in place). Scenes beyond the sections stay."""
    stops = tour_stops(lite)
    taken = 0
    for scene in scenes:
        if scene["type"] != "feature_demo":
            continue
        if taken >= len(stops):
            warnings.append(
                f"{scene['id']}: không còn section nào khác của trang để làm tour, giữ cảnh quay cũ"
            )
            continue
        stop = stops[taken]
        taken += 1
        scene["visual"] = {
            "mode": "recording",
            "page": stop.url,
            "setup": [],
            "show_setup": False,
            "actions": section_actions(stop),
        }
