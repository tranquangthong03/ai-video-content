from app.core.budget import (
    budget_for,
    content_budget_s,
    oversize_warning,
    recommended_duration_s,
)
from tests.test_explorer import feature, profile


def prof(kinds: list[str | None]):  # type: ignore[no-untyped-def]
    return profile([{**feature(f"f{i}", None, []), "demo_kind": k} for i, k in enumerate(kinds)])


def test_budget_adds_hook_cta_one_before_after_and_what_each_feature_earns() -> None:
    assert content_budget_s(prof([])) == 13
    assert content_budget_s(prof(["interaction", "interaction"])) == 33  # todomvc
    assert content_budget_s(prof(["interaction", "navigation", "showcase"])) == 13 + 10 + 6 + 5


def test_features_that_cannot_be_demonstrated_earn_nothing() -> None:
    assert content_budget_s(prof(["failed", None, "interaction"])) == 23


def test_recommended_duration_is_the_largest_level_the_budget_covers() -> None:
    assert [recommended_duration_s(s) for s in (13, 29, 30, 44, 45, 59, 60, 90)] == [
        30,
        30,
        30,
        30,
        45,
        45,
        60,
        60,
    ]


def test_budget_object_and_oversize_warning() -> None:
    b = budget_for(prof(["interaction", "interaction"]))
    assert (b.content_budget_s, b.recommended_duration_s, b.demonstrable) == (33, 30, 2)
    assert oversize_warning(30, b) is None and oversize_warning(15, b) is None
    text = oversize_warning(60, b) or ""
    assert "2 tính năng trình diễn được" in text and "60s" in text and "30s" in text
    rich = budget_for(prof(["interaction"] * 5))
    assert rich.recommended_duration_s == 60 and oversize_warning(60, rich) is None
