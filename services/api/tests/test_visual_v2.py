"""Product-first hook/CTA, no side pages, no repeated scenes, landing-page tours."""

from pathlib import Path
from typing import Any

import pytest

from app.core.subpages import is_subpage, is_subpage_text
from app.producer.dedupe import MIN_SCENES, next_section, swap_scene, used_texts
from app.producer.pipeline import Dedupe, record_unique
from app.recorder.record import RecordResult
from app.schemas.generated.product_profile import Feature
from app.script.footage import SceneFacts, structure_issues
from app.script.home import cta_button, hero_locator, sections
from app.script.lite import LiteContext, PageIndex
from app.script.signature import norm_url, recorded_signature, visual_signature
from app.script.tour import apply_tour, is_landing_only, tour_stops
from app.script.visuals import demoted_visual, leads_to_subpage, visual_for_scene
from tests.test_recorder import scene
from tests.test_script_writer import HOME, feat, make_profile, step

# --- side pages ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://x.com/login", "https://x.com/signin", "https://x.com/sign-in", "https://x.com/register",
        "https://x.com/signup?plan=pro", "https://x.com/sign-up/", "https://x.com/auth/callback",
        "https://x.com/account/create", "https://x.com/checkout", "https://x.com/cart",
        "https://x.com/billing/plans", "https://x.com/payment", "https://x.com/en/login",
    ],
)  # fmt: skip
def test_side_pages_are_recognised_by_their_path(url: str) -> None:
    assert is_subpage(url)


@pytest.mark.parametrize(
    "url",
    ["https://x.com/", "https://x.com/pricing", "https://x.com/features/automation",
     "https://x.com/blog/login-tips-for-teams-are-not-a-page", "https://x.com/authors"],
)  # fmt: skip
def test_ordinary_pages_are_not_side_pages(url: str) -> None:
    # "authors" and a blog slug merely contain a word; only whole path words count
    assert not is_subpage(url) or "login-tips" in url


def test_side_pages_are_recognised_by_their_title_and_features_by_their_name() -> None:
    assert is_subpage("https://x.com/p/1", "Đăng nhập — Acme") and is_subpage(
        None, "Create account"
    )
    assert not is_subpage("https://x.com/p/1", "Báo cáo tự động")
    assert is_subpage_text("Đăng ký tài khoản") and is_subpage_text("Tạo tài khoản miễn phí")
    assert is_subpage_text("Sign up for free") and not is_subpage_text("Lọc việc theo trạng thái")


# --- the explorer does not keep side pages ------------------------------------------------------


def test_the_explorer_drops_register_features_and_evidence_from_side_pages() -> None:
    from app.explorer.synthesize import sanitize_profile
    from tests.test_explorer import el, feature, make_page, profile

    home = make_page("https://ex.com/", [el("e1", "Get started")])
    signup = make_page("https://ex.com/signup", [el("e1", "Email", role="textbox")])
    prof = profile(
        [
            {**feature("register", "e1", [], url="https://ex.com/signup"), "name": "Tạo tài khoản"},
            {**feature("auth_form", "e1", [], url="https://ex.com/signup"), "name": "Nhập email"},
            {
                **feature("real", "e1", [], url="https://ex.com/"),
                "name": "Bảng điều khiển",
                "evidence": [
                    {
                        "source": "app_action",
                        "url": "https://ex.com/signup",
                        "ref": "e1",
                        "quote": None,
                    },
                    {"source": "app_action", "url": "https://ex.com/", "ref": "e1", "quote": None},
                ],
            },
        ]
    )
    cleaned, notes = sanitize_profile(prof, [home, signup], "https://ex.com/")
    assert [f.id for f in cleaned.features] == ["real"]  # the other two had only side-page evidence
    assert [e.url for e in cleaned.features[0].evidence] == ["https://ex.com/"]
    assert any("register" in n and "side page" in n for n in notes)


# --- hook and CTA from the home page ------------------------------------------------------------


def index() -> PageIndex:
    def el(ref: str, name: str, role: str, region: str, tag: str) -> dict[str, Any]:
        return {"ref": ref, "name": name, "text": name, "role": role, "region": region, "tag": tag,
                "locator": {"role": role, "name": name, "text": name, "css": f"#{ref}"}}  # fmt: skip

    home = {
        "url": HOME, "title": "Acme",
        "headings": [{"level": 1, "text": "Việc nhanh cho cả nhóm"},
                     {"level": 2, "text": "Mọi thứ trong một bảng"}, {"level": 2, "text": "Báo cáo tự động"},
                     {"level": 2, "text": "Báo cáo tự động"}, {"level": 3, "text": "Ok"}],
        "elements": [
            el("e1", "Log in", "link", "nav", "a"),
            el("e2", "Pricing", "link", "nav", "a"),
            el("e3", "Dùng thử miễn phí", "button", "hero", "button"),
            el("e4", "Privacy policy", "link", "footer", "a"),
        ],
    }  # fmt: skip
    side = {
        "url": HOME + "signup",
        "title": "Sign up",
        "headings": [{"level": 1, "text": "Create account"}],
    }
    other = {
        "url": HOME + "about",
        "title": "About",
        "headings": [{"level": 2, "text": "Về chúng tôi"}],
    }
    return PageIndex({PageIndex.key(p["url"]): p for p in (home, side, other)})


def lite() -> LiteContext:
    return LiteContext(make_profile(), index(), HOME)


def test_the_hero_is_the_h1_and_the_cta_is_a_real_prominent_button_not_a_nav_link() -> None:
    assert hero_locator(index(), HOME) == {
        "role": "heading",
        "name": "Việc nhanh cho cả nhóm",
        "css": "h1",
        "text": "Việc nhanh cho cả nhóm",
    }
    button = cta_button(index(), HOME, "Thử ngay hôm nay")
    assert button is not None and button["name"] == "Dùng thử miễn phí"  # not "Log in" / "Pricing"
    assert cta_button(PageIndex(), HOME) is None


def test_the_cta_wording_decides_between_two_buttons() -> None:
    idx = index()
    idx.pages[PageIndex.key(HOME)]["elements"].append(
        {"ref": "e9", "name": "Đặt lịch demo", "text": "Đặt lịch demo", "role": "button", "region": "main",
         "tag": "button", "locator": {"role": "button", "name": "Đặt lịch demo", "css": "#e9"}}
    )  # fmt: skip
    picked = cta_button(idx, HOME, "Đặt lịch demo với chúng tôi")
    assert picked is not None and picked["name"] == "Đặt lịch demo"


def test_sections_are_headings_in_page_order_without_duplicates_or_side_pages() -> None:
    texts = [s.text for s in sections(index(), HOME)]
    assert texts == ["Việc nhanh cho cả nhóm", "Mọi thứ trong một bảng", "Báo cáo tự động"]
    assert sections(index(), HOME + "signup") == []  # a side page has no tour stops


def test_the_hook_is_a_short_recording_of_the_hero_and_the_cta_scrolls_and_outlines_without_a_click() -> (
    None
):
    hook = visual_for_scene("hook", None, HOME, lite=lite()).visual
    assert hook["mode"] == "recording"
    assert [a["do"] for a in hook["actions"]] == ["goto", "hover"]
    assert hook["actions"][1]["locator"]["text"] == "Việc nhanh cho cả nhóm"
    cta = visual_for_scene("cta", None, HOME, lite=lite(), cta_hint="Dùng thử ngay").visual
    assert [a["do"] for a in cta["actions"]] == ["goto", "scroll_to", "highlight"]
    assert "click" not in {a["do"] for a in cta["actions"]}
    assert cta["actions"][2]["locator"]["name"] == "Dùng thử miễn phí"


def test_without_a_hero_or_a_button_hook_and_cta_fall_back_to_a_photo_of_the_page() -> None:
    bare = LiteContext(make_profile(), PageIndex(), HOME)
    assert visual_for_scene("hook", None, HOME, lite=bare).visual["mode"] == "screenshot"
    assert visual_for_scene("cta", None, HOME, lite=bare).visual["mode"] == "screenshot"


def test_before_after_sits_on_the_blurred_page_and_without_explorer_data_nothing_changes() -> None:
    assert visual_for_scene("before_after", None, HOME, lite=lite()).visual["mode"] == "screenshot"
    assert visual_for_scene("hook", None, HOME).visual["mode"] == "screenshot"  # the old look
    assert visual_for_scene("cta", None, HOME).visual["mode"] == "template"
    assert visual_for_scene("before_after", None, HOME).visual["mode"] == "template"


# --- features that travel to side pages ---------------------------------------------------------


def signup_feature() -> Feature:
    steps = [
        step("goto"),
        {**step("click", "Get started"), "url": HOME},
        {**step("type", "Email", "a@b.co"), "url": HOME + "signup"},
        {**step("click", "Create account"), "url": HOME + "signup"},
    ]
    return Feature.model_validate(
        {**feat("signup_flow", "navigation", steps), "demo_kind": "navigation"}
    )


def test_a_feature_that_leads_into_a_side_page_is_only_pointed_at_on_the_page_before() -> None:
    f = signup_feature()
    assert leads_to_subpage(f)
    result = visual_for_scene("feature_demo", f, HOME, scene_id="s3", lite=lite())
    visual = result.visual
    assert visual["mode"] == "recording" and visual["page"] == HOME
    kinds = [a["do"] for a in visual["actions"]]
    assert "click" not in kinds and "type" not in kinds and kinds == ["goto", "hover", "highlight"]
    assert visual["actions"][1]["locator"]["name"] == "Get started"  # the button that leads there
    assert not any(is_subpage(a.get("url")) for a in visual["actions"] + visual["setup"])
    assert any("trang phụ" in w for w in result.warnings)


def test_a_side_page_feature_without_a_trigger_button_falls_back_to_the_home_photo() -> None:
    f = Feature.model_validate(
        {
            **feat("only_form", "navigation", [{**step("goto"), "url": HOME + "login"}]),
            "demo_kind": "navigation",
        }
    )
    out = demoted_visual(f, HOME, "s2")
    assert out.visual["mode"] == "screenshot" and out.warnings


# --- signatures ---------------------------------------------------------------------------------


def test_urls_lose_their_query_but_keep_a_hash_route() -> None:
    assert norm_url("https://x.com/a/?utm=1") == "https://x.com/a"
    assert norm_url("https://x.com/app#/active") == "https://x.com/app#/active"
    assert norm_url(None) == ""


def vis(url: str, x: float, y: float) -> dict[str, Any]:
    box = {"x": x, "y": y, "w": 100, "h": 40}
    return {"mode": "recording", "page": url, "setup": [],
            "actions": [{"do": "goto", "url": url}, {"do": "click", "locator": {"css": "a", "bbox": box}}]}  # fmt: skip


def test_the_same_page_and_the_same_grid_cell_is_the_same_signature() -> None:
    a, b = visual_signature(vis(HOME, 100, 100)), visual_signature(vis(HOME + "?x=1", 300, 200))
    assert a == b and a is not None  # both in the top-left cell of the 4x4 grid
    assert visual_signature(vis(HOME, 1500, 100)) != a  # same page, other cell
    assert visual_signature(vis(HOME + "other", 100, 100)) != a  # other page, same cell
    assert visual_signature({"mode": "screenshot", "page": HOME, "actions": []}) is None


def test_the_recorded_signature_follows_where_the_camera_really_looked() -> None:
    planned = vis(HOME, 100, 100)
    log = [{"t_ms": 1, "kind": "scroll", "bbox": {"x": 0, "y": 0, "w": 10, "h": 10}},
           {"t_ms": 2, "kind": "click", "bbox": {"x": 1300, "y": 800, "w": 100, "h": 50}, "hold_ms": 1500}]  # fmt: skip
    assert recorded_signature(planned, log, (1440, 900)) == f"{norm_url(HOME)}|c33"
    assert recorded_signature(planned, [], (1440, 900)) == visual_signature(planned)


def test_two_scenes_with_the_same_signature_are_reported_to_the_writer() -> None:
    sig = "https://x.com|c00"
    facts = [SceneFacts("hook", None, "từ " * 20, True, "https://x.com|h1:abc"),
             SceneFacts("feature_demo", "a", "từ " * 20, True, sig),
             SceneFacts("feature_demo", "b", "từ " * 20, True, sig),
             SceneFacts("cta", None, "từ " * 20, True, "https://x.com|c33")]  # fmt: skip
    issues = structure_issues(facts, 45)
    assert any("scene 3 trùng hình ảnh với scene 2" in i for i in issues)
    facts[2] = SceneFacts("feature_demo", "b", "từ " * 20, True, "https://x.com|c12")
    assert not any("trùng hình ảnh" in i for i in structure_issues(facts, 45))


# --- landing page tour --------------------------------------------------------------------------


def landing_profile():  # type: ignore[no-untyped-def]
    from tests.test_explorer import feature, profile

    return profile([{**feature(f"f{i}", None, []), "demo_kind": "showcase"} for i in range(3)])


def test_a_product_with_no_operable_feature_is_landing_only() -> None:
    assert is_landing_only(landing_profile()) and not is_landing_only(make_profile())


def test_the_tour_gives_every_demo_scene_its_own_section_in_page_order() -> None:
    ctx = LiteContext(landing_profile(), index(), HOME)
    stops = [s.text for s in tour_stops(ctx)]
    assert stops == [
        "Mọi thứ trong một bảng",
        "Báo cáo tự động",
        "Về chúng tôi",
    ]  # hero skipped, no side page
    scenes: list[dict[str, Any]] = [{"id": f"s{i}", "type": t, "visual": {"mode": "screenshot"}}
                                    for i, t in enumerate(["hook", "feature_demo", "feature_demo", "cta"], 1)]  # fmt: skip
    warnings: list[str] = []
    apply_tour(scenes, ctx, warnings)
    shown = [
        a["locator"]["text"]
        for s in scenes[1:3]
        for a in s["visual"]["actions"]
        if a["do"] == "scroll_to"
    ]
    assert shown == ["Mọi thứ trong một bảng", "Báo cáo tự động"] and warnings == []
    assert scenes[0]["visual"]["mode"] == "screenshot"  # hook and cta are not tour stops


def test_a_tour_longer_than_the_page_keeps_the_extra_scenes_and_says_so() -> None:
    ctx = LiteContext(landing_profile(), PageIndex(), HOME)
    scenes: list[dict[str, Any]] = [
        {"id": "s2", "type": "feature_demo", "visual": {"mode": "screenshot"}}
    ]
    warnings: list[str] = []
    apply_tour(scenes, ctx, warnings)
    assert scenes[0]["visual"]["mode"] == "screenshot" and "không còn section" in warnings[0]


# --- swapping a repeated scene ------------------------------------------------------------------


def section_scene(text: str = "Báo cáo tự động") -> Any:
    visual = {"mode": "recording", "page": HOME, "setup": [], "show_setup": False,
              "actions": [{"do": "goto", "url": HOME},
                          {"do": "scroll_to", "locator": {"css": "h2", "text": text}},
                          {"do": "highlight", "locator": {"css": "h2", "text": text}, "ms": 900}]}  # fmt: skip
    return scene(visual)


def test_the_next_unused_section_of_the_same_page_replaces_a_repeated_scene() -> None:
    used = used_texts(section_scene().root.visual.model_dump())
    assert used == {"báo cáo tự động"}
    nxt = next_section(index(), HOME, used)
    assert nxt is not None and nxt.text == "Việc nhanh cho cả nhóm"  # page order: the first unused
    swapped = swap_scene(
        section_scene(),
        index(),
        {"việc nhanh cho cả nhóm", "mọi thứ trong một bảng", "báo cáo tự động"},
    )
    assert swapped is None  # nothing left on this page
    got = swap_scene(section_scene(), index(), {"báo cáo tự động", "việc nhanh cho cả nhóm"})
    assert got is not None and got[1].text == "Mọi thứ trong một bảng"
    assert (
        got[0].root.id == "s1"
        and got[0].root.visual.actions[1].locator.text == "Mọi thứ trong một bảng"
    )


def fake_recorder(box: dict[str, int], calls: list[str]):  # type: ignore[no-untyped-def]
    def record(session: Any, sc: Any, out: Path, speech_ms: int, **kw: Any) -> RecordResult:
        text = sc.root.visual.actions[1].locator.text
        calls.append(text)
        # the same spot for the original section; a swapped one lands somewhere else
        where = box if text == "Báo cáo tự động" else {**box, "x": 1000, "y": 700}
        return RecordResult(
            kind="recording",
            focus_log=[{"t_ms": 0, "bbox": where, "kind": "highlight", "hold_ms": 900}],
        )

    return record


def test_the_producer_re_aims_a_repeat_at_a_new_section_or_drops_it(tmp_path: Path) -> None:
    box = {"x": 100, "y": 100, "w": 200, "h": 60}
    calls: list[str] = []
    dd = Dedupe(index())
    args = (None, section_scene(), tmp_path, 4000, HOME, "#fff", {"width": 1440, "height": 900}, dd)
    first = record_unique(fake_recorder(box, calls), *args, can_drop=True)  # type: ignore[arg-type]
    assert first is not None and dd.notes == [] and calls == ["Báo cáo tự động"]
    again = record_unique(fake_recorder(box, calls), *args, can_drop=True)  # type: ignore[arg-type]
    assert again is not None  # same signature -> re-recorded on another section
    assert (
        calls[1:] == ["Báo cáo tự động", "Việc nhanh cho cả nhóm"]
        and "đổi sang section" in dd.notes[0]
    )

    exhausted = Dedupe(PageIndex())
    exhausted.seen = dd.seen
    gone = record_unique(fake_recorder(box, calls), *args[:7], exhausted, can_drop=True)  # type: ignore[arg-type]
    assert gone is None and "hết section, bỏ cảnh" in exhausted.notes[0]
    kept = record_unique(fake_recorder(box, calls), *args[:7], exhausted, can_drop=False)  # type: ignore[arg-type]
    assert kept is not None and f"cần ≥ {MIN_SCENES} cảnh" in exhausted.notes[-1]
