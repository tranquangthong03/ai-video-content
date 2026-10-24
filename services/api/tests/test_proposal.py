import pytest

from app.core.interaction import ALLOWED_ACTIONS, check_response, make_request, make_response
from app.proposal.concepts import ConceptDecision, normalize_concepts, read_decision
from app.proposal.outline import apply_ops, outline_from_concept
from app.proposal.understanding import ProfileEdits, apply_edits, build_request, merge_response
from app.schemas.generated.beat_op import BeatOp
from app.schemas.generated.outline import Outline
from app.schemas.generated.product_profile import ProductProfile
from app.schemas.generated.video_concept import VideoConcept


def profile() -> ProductProfile:
    def feat(fid: str, name: str, score: float) -> dict:  # type: ignore[type-arg]
        return {"id": fid, "name": name, "description": f"{name} mô tả", "importance": 0.5,
                "evidence": [], "demo_score": score, "verified": True}  # fmt: skip

    return ProductProfile.model_validate(
        {"site_type": "web_app", "product_name": "TaskFlow", "one_liner": "Quản lý việc",
         "target_users": ["Nhóm nhỏ"], "open_questions": ["Ai là khách hàng?"],
         "features": [feat("f1", "Kanban", 1.0), feat("f2", "Nhắc việc", 0.5), feat("f3", "Báo cáo", 0)]}
    )  # fmt: skip


def concept(i: int, angle: str, rec: bool, ids: list[str]) -> VideoConcept:
    return VideoConcept.model_validate(
        {
            "id": f"c{i}",
            "angle": angle,
            "title": f"T{i}",
            "goal": "awareness",
            "hook_example": "h",
            "feature_ids": ids,
            "beats": ["Hook mở đầu", "Demo Kanban", "Demo Nhắc việc", "CTA"],
            "duration_s": 30,
            "why": "w",
            "recommended": rec,
        }  # fmt: skip
    )


def outline() -> Outline:
    return outline_from_concept(concept(1, "overview", True, ["f1", "f2"]), profile())


def ops(*raw: dict) -> list[BeatOp]:  # type: ignore[type-arg]
    return [BeatOp.model_validate(r) for r in raw]


# --- outline ops --------------------------------------------------------------------------------


def test_outline_from_concept_numbers_beats_and_links_named_features() -> None:
    o = outline()
    assert [b.id for b in o.beats] == ["b1", "b2", "b3", "b4"]
    assert (
        o.beats[1].feature_id == "f1"
        and o.beats[2].feature_id == "f2"
        and o.beats[0].feature_id is None
    )


def test_set_changes_only_the_target_beat() -> None:
    before = outline()
    result = apply_ops(
        before,
        ops({"op": "set", "beat_id": "b2", "text": "Kéo thả trong 1 giây", "feature_id": "f1"}),
    )
    after = result.outline
    assert after.beats[1].text == "Kéo thả trong 1 giây"
    for i in (0, 2, 3):  # untouched beats stay exactly the same
        assert after.beats[i] == before.beats[i]
    assert after.version == before.version + 1 and result.errors == []
    assert len(result.changes) == 1 and "b2" in result.changes[0]
    assert before.beats[1].text == "Demo Kanban"  # the input outline is not mutated


def test_delete_insert_move_and_ids_are_never_reused() -> None:
    result = apply_ops(
        outline(),
        ops(
            {"op": "delete", "beat_id": "b3"},
            {"op": "insert", "after_beat_id": "b1", "text": "Con số gây sốc", "feature_id": None},
            {"op": "move", "beat_id": "b4", "after_beat_id": None},
        ),
    )
    out = result.outline
    assert [b.id for b in out.beats] == ["b4", "b1", "b5", "b2"]  # b5, not a reused b3
    assert out.beats[2].text == "Con số gây sốc"


def test_insert_at_start_and_unknown_ids_are_reported_not_applied() -> None:
    result = apply_ops(
        outline(),
        ops(
            {"op": "insert", "after_beat_id": None, "text": "Mở đầu mới"},
            {"op": "set", "beat_id": "b99", "text": "x"},
            {"op": "delete", "beat_id": "b98"},
            {"op": "move", "beat_id": "b1", "after_beat_id": "b97"},
        ),
    )
    assert result.outline.beats[0].text == "Mở đầu mới"
    assert len(result.errors) == 3 and len(result.outline.beats) == 5
    assert [b.id for b in result.outline.beats][1:] == [
        "b1",
        "b2",
        "b3",
        "b4",
    ]  # failed move restored b1


def test_set_meta_validates_values() -> None:
    result = apply_ops(
        outline(),
        ops(
            {"op": "set_meta", "field": "duration_s", "value": 45},
            {"op": "set_meta", "field": "goal", "value": "conversion"},
            {"op": "set_meta", "field": "title", "value": "Tiêu đề mới"},
            {"op": "set_meta", "field": "duration_s", "value": 50},
            {"op": "set_meta", "field": "goal", "value": "viral"},
        ),
    )
    assert (result.outline.duration_s, result.outline.goal, result.outline.title) == (
        45,
        "conversion",
        "Tiêu đề mới",
    )
    assert len(result.errors) == 2


def test_unknown_feature_ids_are_unlinked_with_a_warning_and_beat_count_is_checked() -> None:
    result = apply_ops(
        outline(),
        ops(
            {"op": "set", "beat_id": "b2", "text": "x", "feature_id": "nope"},
            {"op": "delete", "beat_id": "b4"},
        ),
        valid_feature_ids={"f1", "f2"},
    )
    assert result.outline.beats[1].feature_id is None
    assert any("nope" in w for w in result.warnings) and any("3 beat" in w for w in result.warnings)


def test_no_ops_means_no_change_and_no_version_bump() -> None:
    result = apply_ops(outline(), [])
    assert result.outline == outline() and result.changes == []


# --- understanding ------------------------------------------------------------------------------


def test_request_lists_features_and_open_questions_as_text_questions() -> None:
    request = build_request("job1", profile())
    assert request.kind == "confirm_understanding"
    assert request.allowed_actions == ["answer", "edit", "explore_more", "cancel"]
    assert request.profile is not None and len(request.profile.features) == 3
    assert [q.type for q in request.questions] == ["text"]


def test_apply_edits_excludes_edits_text_and_adds_user_features() -> None:
    base = profile()
    request = build_request("job1", base)
    response = make_response(
        request, "edit",
        profile_edit={"exclude_feature_ids": ["f3"], "one_liner": "Mới", "target_users": ["Freelancer"],
                      "added_features": [{"name": "Lịch", "description": "Xem lịch"}]},
        answers={"oq1": "Nhóm nhỏ"},
    )  # fmt: skip
    edits = merge_response(ProfileEdits(), response)
    result = apply_edits(base, edits)
    assert [f.id for f in result.features] == ["f1", "f2", "u1"]
    added = result.features[-1]
    assert added.source == "user" and added.demo_score == 0 and added.verified is False
    assert (result.one_liner, result.target_users) == ("Mới", ["Freelancer"])
    assert len(base.features) == 3 and base.one_liner == "Quản lý việc"  # base untouched
    assert edits.answers == {"oq1": "Nhóm nhỏ"}
    # exclusions accumulate across rounds
    more = merge_response(
        edits, make_response(request, "edit", profile_edit={"exclude_feature_ids": ["f2"]})
    )
    assert [f.id for f in apply_edits(base, more).features] == ["f1", "u1"]


# --- concepts / interaction ---------------------------------------------------------------------


def test_normalize_concepts_keeps_one_recommended_and_real_feature_ids() -> None:
    cs = [concept(1, "overview", True, ["f1", "zzz"]), concept(2, "deep_dive", True, ["f2"]),
          concept(3, "pain_solution", False, [])]  # fmt: skip
    cs[2].id = "c1"  # duplicate id
    fixed = normalize_concepts(cs, profile())
    assert [c.recommended for c in fixed] == [True, False, False]
    assert fixed[0].feature_ids == ["f1"] and len({c.id for c in fixed}) == 3


def test_read_decision_variants() -> None:
    cs = [
        concept(1, "overview", False, []),
        concept(2, "deep_dive", True, []),
        concept(3, "pain_solution", False, []),
    ]
    request = make_request("j", "choose_concept", "m")

    def decide(action: str, **kw: object) -> ConceptDecision:
        return read_decision(cs, make_response(request, action, **kw))

    assert decide("answer", answers={"concept_id": "c3", "notes": "30s"}).concept.id == "c3"  # type: ignore[union-attr]
    assert decide("answer", answers={"concept_id": "recommended"}).concept.id == "c2"  # type: ignore[union-attr]
    assert decide("answer", answers={"concept_id": "1"}).concept.id == "c1"  # type: ignore[union-attr]
    assert decide("regenerate", answers={"notes": "ngắn hơn"}).notes == "ngắn hơn"
    assert decide("cancel").kind == "cancel"
    with pytest.raises(ValueError):
        decide("answer", answers={"concept_id": "nope"})


def test_allowed_actions_per_kind_and_response_checks() -> None:
    assert ALLOWED_ACTIONS == {
        "confirm_understanding": ["answer", "edit", "explore_more", "cancel"],
        "choose_concept": ["answer", "regenerate", "cancel"],
        "outline_review": ["approve", "edit", "regenerate", "cancel"],
    }
    request = make_request("j", "choose_concept", "m")
    assert request.allowed_actions == ["answer", "regenerate", "cancel"]
    assert check_response(request, make_response(request, "answer")) == []
    assert check_response(request, make_response(request, "approve"))  # not allowed here
    other = make_request("j", "choose_concept", "m")
    assert check_response(request, make_response(other, "answer"))  # wrong interaction_id
