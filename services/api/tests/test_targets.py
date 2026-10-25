from typing import Any

from app.schemas.generated.product_profile import ProductProfile
from app.script.lite import LiteContext, PageIndex
from app.script.targets import nav_target, phrase_matches, resolve_by_text
from app.script.visuals import visual_for_scene
from tests.test_explorer import feature, profile

HOME = "https://hr.example.com/web/index.php/dashboard/index"
LEAVE = "https://hr.example.com/web/index.php/leave/viewLeaveModule"
ADMIN = "https://hr.example.com/web/index.php/admin/viewAdminModule"


def el(
    ref: str, role: str, name: str, region: str = "main", href: str | None = None
) -> dict[str, Any]:
    return {
        "ref": ref, "role": role, "name": name, "text": name, "region": region, "href": href,
        "locator": {"role": role, "name": name, "css": f"#{ref}"},
    }  # fmt: skip


# the explorer's view of an English dashboard (the real OrangeHRM one, shortened)
PAGE = {
    "url": HOME,
    "headings": [],
    "elements": [
        el("e1", "textbox", "Search", "nav"),
        el("e5", "link", "Leave", "nav", LEAVE),
        el("e10", "link", "Dashboard", "nav", HOME),
        el("e18", "button", "Assign Leave"),
        el("e21", "button", "Apply Leave"),
        el("e30", "link", "Upgrade", "header", "https://hr.example.com/upgrade"),
        el("e31", "link", "Admin", "nav", ADMIN),
    ],
}


def ctx(features: list[dict[str, Any]]) -> LiteContext:
    return LiteContext(profile(features), PageIndex({PageIndex.key(HOME): PAGE}), HOME)


def vi_feature(fid: str, name: str, quotes: list[str]) -> dict[str, Any]:
    f = feature(fid, None, [], url=HOME)
    f["name"] = name
    f["demo_kind"] = "failed"
    f["evidence"] = [{"source": "app_action", "url": HOME, "ref": None, "quote": q} for q in quotes]
    return f


def visual(c: LiteContext, fid: str):  # type: ignore[no-untyped-def]
    f = next(x for x in c.profile.features if x.id == fid)
    return visual_for_scene("feature_demo", f, HOME, scene_id="s2", lite=c)


# --- phrases, not loose words ---------------------------------------------------------------------


def test_only_whole_phrases_match_and_short_ones_must_be_the_whole_text() -> None:
    assert phrase_matches("Apply Leave", "Apply Leave")
    assert phrase_matches("quick launch", "Quick Launch panel")  # a phrase inside the text
    assert phrase_matches("Bảng điều khiển", "bang dieu khien")  # accents and case ignored
    assert not phrase_matches("điều", "Bảng điều khiển")  # a loose word of a longer text
    assert phrase_matches("HR", "HR")  # under 4 characters: only as the whole text
    assert not phrase_matches("HR", "HR Admin Portal")
    assert not phrase_matches("", "x") and not phrase_matches("x", "")


# --- the case of the OrangeHRM video -------------------------------------------------------------------


def test_a_vietnamese_feature_name_finds_the_menu_item_through_the_pages_own_word() -> None:
    c = ctx([vi_feature("dashboard_overview", "Bảng điều khiển tổng quan nhân sự", ["Dashboard"])])
    found = resolve_by_text(c.profile.features[0], c.pages.pages, HOME)
    assert found is not None and found.source == "nav"
    assert [e["name"] for e in found.elements] == ["Dashboard"]


def test_the_loose_words_of_the_translated_name_are_never_used() -> None:
    c = ctx([vi_feature("x", "Bảng điều khiển tổng quan nhân sự", [])])  # nothing the page said
    assert resolve_by_text(c.profile.features[0], c.pages.pages, HOME) is None
    result = visual(c, "x")
    assert result.visual["mode"] == "screenshot"  # nothing hovered
    assert any(w.startswith("no_target: s2") and "«x»" in w for w in result.warnings)
    used = " ".join(str(a.get("locator")) for a in result.visual["actions"]).lower()
    assert not any(w in used for w in ("khiển", "bảng", "điều"))


def test_a_name_in_brackets_is_the_pages_text_for_it() -> None:
    c = ctx([vi_feature("apply_leave", "Tạo đơn xin nghỉ phép (Apply Leave)", [])])
    found = resolve_by_text(c.profile.features[0], c.pages.pages, HOME)
    assert found is not None and found.source == "text"
    assert found.elements[0]["ref"] == "e21"  # the button, not the menu entry "Leave"


def test_the_feature_page_is_the_dashboard_so_the_menu_entry_is_just_pointed_at() -> None:
    c = ctx([vi_feature("dashboard_overview", "Bảng điều khiển", ["Dashboard"])])
    actions = visual(c, "dashboard_overview").visual["actions"]
    assert [a["do"] for a in actions] == ["goto", "hover", "highlight"]  # same page: no click
    assert actions[1]["locator"]["name"] == "Dashboard"


# --- the menu is the safe way to a feature on another page ---------------------------------------------


def test_a_menu_link_to_another_page_becomes_a_navigation_scene() -> None:
    c = ctx([vi_feature("leave", "Quản lý nghỉ phép", ["Leave"])])
    result = visual(c, "leave")
    kinds = [a["do"] for a in result.visual["actions"]]
    assert kinds == ["goto", "click", "wait"] and result.visual["mode"] == "recording"
    click = result.visual["actions"][1]
    assert click["locator"]["name"] == "Leave" and click["zoom"] is True
    assert any("menu điều hướng" in w and LEAVE in w for w in result.warnings)


def test_nav_target_only_for_plain_links_to_other_safe_pages() -> None:
    link = el("e5", "link", "Leave", "nav", LEAVE)
    assert nav_target(link, HOME, HOME) == LEAVE
    assert nav_target(el("e1", "button", "Leave", href=LEAVE), HOME, HOME) is None  # not a link
    assert nav_target(el("e2", "link", "Home", href=HOME), HOME, HOME) is None  # same page
    assert nav_target(el("e3", "link", "x", href="https://other.com/a"), HOME, HOME) is None
    for path in ("settings", "billing", "logout", "login", "admin/users"):
        other = el("e4", "link", "y", href=f"https://hr.example.com/{path}")
        assert nav_target(other, HOME, HOME) is None, path


def test_blocked_or_sensitive_entries_are_never_pointed_at_or_clicked() -> None:
    c = ctx([vi_feature("up", "Nâng gói", ["Upgrade"]), vi_feature("adm", "Quản trị", ["Admin"])])
    assert resolve_by_text(c.profile.features[0], c.pages.pages, HOME) is None  # blacklisted word
    admin = visual(c, "adm")
    assert all(a["do"] != "click" for a in admin.visual["actions"])  # /admin... is sensitive


def test_verified_evidence_refs_still_win_over_any_text_search() -> None:
    f = vi_feature("apply_leave", "Tạo đơn xin nghỉ phép (Apply Leave)", ["Leave"])
    f["evidence"][0]["ref"] = "e18"  # the explorer verified this button
    c = ctx([f])
    actions = visual(c, "apply_leave").visual["actions"]
    assert actions[1]["locator"]["name"] == "Assign Leave"


def test_profile_type_is_unchanged() -> None:
    assert isinstance(profile([]), ProductProfile)
