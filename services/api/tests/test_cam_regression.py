"""The focus cases found on the three M1 videos (frames saved in tests/fixtures/cam), kept as tests."""

import json
from pathlib import Path
from typing import Any

from app.producer.focus_rules import build_focus_track, trusted_actions

FIX = Path(__file__).parent / "fixtures" / "cam"


def track_of(job: str, scene: str, *, final_chapter: bool = False) -> tuple[Any, dict[str, Any]]:
    """The focus track the rules make for a saved scene (the planner's own plan, as it was)."""
    inv = json.loads((FIX / job / f"{scene}.json").read_text(encoding="utf-8"))
    foc = json.loads((FIX / job / f"focus_{scene}.json").read_text(encoding="utf-8"))
    lead = foc["lead_ms"]
    inventory = [{**e, "t_ms": e["t_ms"] - lead} for e in inv["inventory"]]
    actions = [
        {**a, "t_ms": a["t_ms"] - lead, "end_ms": a["end_ms"] - lead} for a in inv["action_log"]
    ]
    typing_end = max([a["end_ms"] for a in actions if a["do"] == "type"], default=0.0)
    result = build_focus_track(
        duration_ms=max(p["to_ms"] for p in foc["phrases"]) + 800,
        clip=(1440, 900),
        inventory=inventory,
        action_log=actions,
        phrases=foc["phrases"],
        plan=foc["plan"],
        legacy_focus=[],
        submit_after_ms=typing_end if final_chapter else None,
    )
    return result, foc


def focus_texts(result: Any) -> list[str]:
    return [t["text"] for t in result.track if t["framing"] != "establish"]


def test_an_element_id_that_now_names_another_element_is_not_believed() -> None:
    """«Add» (list page) and «Cancel» (form page) were both e75: the camera went to Cancel."""
    action = {"t_ms": 1000, "end_ms": 1100, "do": "click", "target_text": "Add", "item_id": "e75"}
    cancel = {"id": "e75", "kind": "button", "region": "main", "text": "Cancel", "is_new": False,
              "bbox": {"x": 1149, "y": 477, "w": 108, "h": 32}}  # fmt: skip
    kept = trusted_actions([action], [{"t_ms": 1000, "items": [cancel]}])
    assert kept[0]["item_id"] is None  # the id now belongs to «Cancel»: dropped
    same = trusted_actions([action], [{"t_ms": 1000, "items": [{**cancel, "text": "Add"}]}])
    assert same[0]["item_id"] == "e75"  # when it still says Add, it is believed


def test_the_camera_no_longer_goes_to_cancel_or_reset_while_the_voice_says_add() -> None:
    result, foc = track_of("orangehrm", "s2")
    assert "bấm nút Add" in " ".join(p["text"] for p in foc["phrases"])
    texts = focus_texts(result)
    assert not any(t in ("Cancel", "Reset", "Search") for t in texts)  # the wrong buttons of N4
    assert any("Add" in t or "PIM" in t for t in texts)  # something the voice names


def test_the_name_the_voice_says_is_the_field_that_holds_it_and_save_comes_last() -> None:
    result, foc = track_of("orangehrm", "s4", final_chapter=True)
    assert "Nguyen Van An" in " ".join(p["text"] for p in foc["phrases"])
    focus = [t for t in result.track if t["framing"] != "establish"]
    named = next(t for t in focus if "Nguyen" in t["text"])
    assert named["item_kind"] == "input"
    assert not any(t["text"] == "Cancel" for t in focus)
    save = [t for t in focus if t["text"] == "Save"]
    assert save and all(
        t["t_ms"] >= named["t_ms"] for t in save
    )  # the button after the filled form


def test_the_submit_button_is_not_the_focus_before_the_last_chapter() -> None:
    result, _ = track_of("orangehrm", "s3", final_chapter=False)
    assert not any(t["text"] in ("Save", "Cancel") for t in result.track)


def test_a_page_that_is_one_big_canvas_gets_its_control_panel_not_the_picture() -> None:
    result, _ = track_of("squoosh", "s2")
    focus = [t for t in result.track if t["framing"] != "establish"]
    assert focus and not any(t["item_kind"] in ("media", "image") for t in focus)
    assert all(t["bbox"]["w"] < 1440 for t in focus)  # a part of the page, never all of it
    assert result.metrics["media_replaced"] >= 1


def test_todomvc_never_looks_at_the_sidebar() -> None:
    for scene in ("s2", "s3", "s4", "s5"):
        result, _ = track_of("todomvc", scene)
        assert not any(t["region"] == "aside" for t in result.track), scene
