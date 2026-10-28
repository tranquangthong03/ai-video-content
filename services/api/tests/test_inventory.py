from pathlib import Path

from app.browser.session import BrowserSession
from app.producer.trim import Cut, shift_actions
from app.recorder.inventory import MAX_ITEMS, REGIONS
from tests.test_recorder import goto, loc, rec

KINDS = {
    "input", "button", "list_item", "heading", "paragraph", "card", "image", "media",
    "nav", "sidebar", "footer", "dialog", "other",
}  # fmt: skip


def typed_scene(session: BrowserSession, site: str, tmp_path: Path):  # type: ignore[no-untyped-def]
    visual = {
        "mode": "recording",
        "actions": [
            goto(site, "/todo.html"),
            {"do": "type", "locator": loc("#new"), "text": "Mua sữa"},
        ],
    }
    return rec(session, site, tmp_path, visual, speech_ms=1500)


def test_snapshots_list_visible_items_with_the_documented_fields(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    r = typed_scene(browser_session, site, tmp_path)
    assert r.inventory and [s["t_ms"] for s in r.inventory] == sorted(
        s["t_ms"] for s in r.inventory
    )
    for snap in r.inventory:
        assert 0 < len(snap["items"]) <= MAX_ITEMS
        for it in snap["items"]:
            assert set(it) - {"filled", "loaded"} == {
                "id",
                "role",
                "tag",
                "text",
                "bbox",
                "kind",
                "is_new",
                "region",
            }
            assert ("filled" in it) == (it["kind"] == "input")  # `filled`: was it typed into
            assert ("loaded" not in it) or it["tag"] in ("img", "video", "canvas")  # media only
            assert it["kind"] in KINDS and it["region"] in REGIONS and len(it["text"]) <= 80
            b = it["bbox"]
            assert (
                0 <= b["x"] and 0 <= b["y"] and b["x"] + b["w"] <= 1440 and b["y"] + b["h"] <= 900
            )
    last = r.inventory[-1]["items"]
    assert any(i["kind"] == "heading" and i["text"] == "Việc cần làm" for i in last)
    assert any(i["kind"] == "input" and i["tag"] == "input" for i in last)


def test_the_action_log_points_at_the_input_in_the_snapshots(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    r = typed_scene(browser_session, site, tmp_path)
    typing = next(a for a in r.action_log if a["do"] == "type")
    assert typing["end_ms"] >= typing["t_ms"] + 7 * 90  # seven characters at 90 ms or more
    assert typing["target_text"] or typing["item_id"]
    after = [s for s in r.inventory if s["t_ms"] >= typing["t_ms"]]
    ids = {i["id"] for s in after for i in s["items"]}
    assert typing["item_id"] in ids  # the element worked on is always listed


def test_elements_that_appear_after_an_action_are_marked_new(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    r = typed_scene(browser_session, site, tmp_path)
    new_texts = {i["text"] for s in r.inventory for i in s["items"] if i["is_new"]}
    assert "Mua sữa" in new_texts  # the todo that Enter added
    before = [i for i in r.inventory[0]["items"] if i["kind"] == "heading"]
    assert before and not any(i["is_new"] for i in before)


def test_trim_moves_the_action_times_with_the_cuts() -> None:
    cuts = [Cut(0, 500), Cut(2000, 3000)]
    actions = [{"t_ms": 1500, "end_ms": 3500, "do": "type", "item_id": "e1"}]
    moved = shift_actions(actions, cuts)
    assert moved == [{"t_ms": 1000, "end_ms": 2000, "do": "type", "item_id": "e1"}]


def test_scroll_to_and_highlight_frame_the_heading_and_its_content_not_the_whole_section(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    heading = loc("#paths-title", text="Lộ trình học theo vai trò")
    visual = {
        "mode": "recording",
        "actions": [
            goto(site, "/sections.html"),
            {"do": "scroll_to", "locator": heading},
            {"do": "highlight", "locator": heading, "ms": 900},
        ],
    }
    r = rec(browser_session, site, tmp_path, visual, speech_ms=1000)
    assert r.warnings == [] and r.steps_ok == 2
    section = next(f for f in r.focus_log if f["kind"] == "section")["bbox"]
    # the section is 1000 px tall; the block is the heading plus the two paragraphs below it
    assert 60 < section["h"] < 300 and section["w"] < 800
    assert not any(
        f["kind"] == "scroll" for f in r.focus_log
    )  # no more "biggest block at the centre"


def test_an_element_that_arrives_a_few_seconds_late_is_waited_for(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    visual = {
        "mode": "recording",
        "actions": [
            goto(site, "/late.html"),
            {"do": "hover", "locator": loc(None, role="button", name="Apply Leave")},
        ],
    }
    r = rec(browser_session, site, tmp_path, visual, speech_ms=1000)
    assert r.warnings == [] and r.steps_ok == 1 and r.kind == "recording"
