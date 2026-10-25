from pathlib import Path

import pytest

from app.core.features import (
    check_selection,
    default_selection,
    merge_duplicates,
    name_similarity,
)
from app.core.interaction import check_response, make_request, make_response
from app.schemas.generated.product_profile import ProductProfile
from tests.test_explorer import feature, profile

TODOMVC = Path(__file__).parent / "fixtures" / "profiles" / "todomvc_verified.json"


def real_profile() -> ProductProfile:
    return ProductProfile.model_validate_json(TODOMVC.read_text(encoding="utf-8"))


def test_real_todomvc_profile_merges_the_two_edit_features() -> None:
    merged, dropped = merge_duplicates(real_profile())
    ids = [f.id for f in merged.features]
    assert dropped == [("edit_todo_dblclick", "edit_todo")]
    assert ids == ["create_todo", "edit_todo", "filter_todos"]
    kept = merged.features[1]
    assert kept.demo_kind == "interaction" and kept.thumbnail  # best verdict + its thumbnail


def test_merge_does_not_touch_the_input_and_keeps_evidence() -> None:
    base = real_profile()
    merged, _ = merge_duplicates(base)
    assert len(base.features) == 4 and len(merged.features) == 3


def test_same_intent_key_merges_whatever_the_names() -> None:
    a = {**feature("a", None, []), "name": "Add task", "intent_key": "create_item"}
    b = {**feature("b", None, []), "name": "Quick entry", "intent_key": "create_item"}
    merged, dropped = merge_duplicates(profile([a, b]))
    assert len(merged.features) == 1 and len(dropped) == 1


def test_similar_names_without_accents_merge_but_different_ones_do_not() -> None:
    assert name_similarity("Chỉnh sửa việc", "chinh sua viec cần làm") >= 0.8
    assert name_similarity("Tạo việc cần làm mới", "Chỉnh sửa việc cần làm tại chỗ") < 0.8


def test_prefix_ids_with_their_own_working_demos_stay_separate() -> None:
    def feat(fid: str, target: str) -> dict:  # type: ignore[type-arg]
        step = {"do": "click", "locator": {"role": "button", "name": target}}
        return {
            **feature(fid, None, [step]),
            "name": f"Tinh nang {target}",
            "demo_kind": "interaction",
        }

    merged, dropped = merge_duplicates(
        profile([feat("create", "Alpha"), feat("create_project_template", "Beta")])
    )
    assert dropped == [] and len(merged.features) == 2


def test_prefix_ids_on_different_pages_stay_separate() -> None:
    a = {
        **feature("edit_todo", None, [], url="https://ex.com/a"),
        "name": "Mot",
        "demo_kind": "failed",
    }
    b = {
        **feature("edit_todo_x", None, [], url="https://ex.com/b"),
        "name": "Hai",
        "demo_kind": "failed",
    }
    assert merge_duplicates(profile([a, b]))[1] == []


def test_same_page_and_same_target_merge() -> None:
    step = {"do": "click", "locator": {"role": "button", "name": "Save"}}
    a = {**feature("alpha_x", None, [step]), "name": "Luu mot"}
    b = {**feature("beta_y", None, [step]), "name": "Hoan tat khac"}
    c = {**feature("gamma_z", None, [step], url="https://ex.com/other"), "name": "Khac hoan toan"}
    merged, _ = merge_duplicates(profile([a, b, c]))
    assert [f.id for f in merged.features] == ["alpha_x", "gamma_z"]


def test_user_added_feature_wins_over_a_site_twin() -> None:
    site = {**feature("site", None, []), "name": "Tao viec", "demo_kind": "interaction"}
    mine = {**feature("u1", None, []), "name": "Tao viec", "source": "user"}
    merged, _ = merge_duplicates(profile([site, mine]))
    assert [f.id for f in merged.features] == ["u1"]


def test_default_selection_prefers_best_demos_and_caps_at_three() -> None:
    kinds = ["failed", "showcase", "interaction", "navigation", "interaction"]
    feats = [{**feature(f"f{i}", None, []), "demo_kind": k} for i, k in enumerate(kinds)]
    feats[2]["demo_score"] = 0.9
    chosen = default_selection(profile(feats))
    assert chosen == ["f2", "f4", "f3"]


def test_default_selection_tops_up_to_two_when_little_is_demonstrable() -> None:
    feats = [{**feature(f"f{i}", None, []), "demo_kind": k} for i, k in enumerate(["failed", None])]
    assert len(default_selection(profile(feats))) == 2


def test_real_profile_default_selection_skips_failed_features() -> None:
    merged, _ = merge_duplicates(real_profile())
    assert default_selection(merged) == ["create_todo", "edit_todo"]


@pytest.mark.parametrize(
    ("selected", "ok"),
    [
        (["a"], True),
        (["a", "b", "c", "d"], True),
        ([], False),
        (["a", "a"], False),
        (["a", "zz"], False),
        (["a", "b", "c", "d", "e"], False),
        ("a", False),
    ],
)
def test_check_selection(selected: object, ok: bool) -> None:
    feats = [feature(i, None, []) for i in "abcde"]
    assert (check_selection(profile(feats), selected) == []) is ok


def test_select_features_request_validates_the_answer() -> None:
    p = profile([feature("a", None, []), feature("b", None, [])])
    req = make_request("j", "select_features", "chọn", profile=p.model_dump())
    assert req.allowed_actions == ["answer", "explore_more", "cancel"]
    good = make_response(req, "answer", answers={"selected_features": ["b", "a"]})
    bad = make_response(req, "answer", answers={"selected_features": ["x"]})
    assert check_response(req, good) == [] and check_response(req, bad)
    assert check_response(req, make_response(req, "approve"))  # not allowed here
