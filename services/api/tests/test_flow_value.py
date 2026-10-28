"""value_actions and empty-state signals, on the saved data of the four snapshots (T0, no browser).

aisoeasy (a signed-in, brand-new account; the flow only moves from Home to Learn to a course that
failed to load) must be labelled; todomvc, orangehrm and squoosh must not be.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from app.core.flow_value import (
    EMPTY_WARNING,
    NAVIGATION_ONLY,
    empty_signals,
    empty_warning,
    inventory_texts,
    label_for,
    page_texts,
    value_actions_expected,
    value_actions_of_run,
)
from app.schemas.generated.core_flow import CoreFlow
from app.schemas.generated.flow_run import FlowRun

GOLDEN = Path(__file__).parent / "golden"
GOOD = ("todomvc", "orangehrm", "squoosh")


def load(name: str, rel: str) -> Any:
    return json.loads((GOLDEN / name / rel).read_text(encoding="utf-8"))


def run_of(name: str) -> FlowRun:
    return FlowRun.model_validate(load(name, "flow/flow_run.json"))


def flows_of(name: str) -> list[CoreFlow]:
    return [CoreFlow.model_validate(f) for f in load(name, "selected_flow.json")["flows"]]


def pages_of(name: str) -> list[str]:
    texts: list[str] = []
    for f in sorted((GOLDEN / name / "explore" / "pages").glob("*.json")):
        texts += page_texts(json.loads(f.read_text(encoding="utf-8")))
    return texts


def test_the_aisoeasy_run_only_navigates_and_is_labelled() -> None:
    run = run_of("aisoeasy")
    logs = load("aisoeasy", "flow/live/logs.json")
    assert value_actions_of_run(run) < 2
    assert value_actions_of_run(run, logs) < 2
    assert label_for(value_actions_of_run(run, logs)) == NAVIGATION_ONLY


@pytest.mark.parametrize("name", GOOD)
def test_runs_that_fill_and_choose_are_not_labelled(name: str) -> None:
    run = run_of(name)
    logs = load(name, "flow/live/logs.json")
    assert value_actions_of_run(run, logs) >= 2
    assert label_for(value_actions_of_run(run, logs)) is None


@pytest.mark.parametrize("name", GOOD)
def test_the_proposed_flows_of_the_good_snapshots_are_not_labelled(name: str) -> None:
    assert all(value_actions_expected(f) >= 2 for f in flows_of(name))


def test_the_proposed_aisoeasy_flows_that_only_look_are_labelled() -> None:
    counts = {f.title: value_actions_expected(f) for f in flows_of("aisoeasy")}
    first = next(c for t, c in counts.items() if "dashboard" in t)
    assert first < 2, counts


def test_an_empty_account_and_an_error_page_are_two_signs_of_no_data() -> None:
    signals = empty_signals(
        pages_of("aisoeasy") + inventory_texts(load("aisoeasy", "flow/live/logs.json"))
    )
    assert len(signals) >= 2, signals
    assert empty_warning(signals) == EMPTY_WARNING


@pytest.mark.parametrize("name", GOOD)
def test_pages_with_data_raise_no_empty_warning(name: str) -> None:
    signals = empty_signals(pages_of(name) + inventory_texts(load(name, "flow/live/logs.json")))
    assert empty_warning(signals) is None, signals


@pytest.mark.parametrize(
    "text",
    [
        "0/1 courses completed",
        "0 days in a row",
        "No data",
        "Nothing here yet",
        "Chưa có nhân viên",
        "Course not found.",
    ],
)
def test_each_kind_of_sign_is_recognised(text: str) -> None:
    assert empty_signals([text])


@pytest.mark.parametrize(
    "text", ["10 items left", "Large photo 2.8MB", "Add employee", "Records Found (20)"]
)
def test_ordinary_text_is_not_a_sign(text: str) -> None:
    assert empty_signals([text]) == []


# --- the cards (B4: saved data of the four snapshots) -----------------------------------------------


def test_the_select_flow_card_labels_the_navigation_only_flows_and_warns_about_an_empty_account() -> (
    None
):
    from app.core.flow_choice import build_request
    from app.core.flow_value import explored_texts

    flows = flows_of("aisoeasy")
    warning = empty_warning(empty_signals(explored_texts(GOLDEN / "aisoeasy")))
    request = build_request("j", flows, "https://aisoeasy.co/", empty_warning=warning)
    sel = request.flow_select
    assert sel is not None and sel.empty_warning == EMPTY_WARNING
    labelled = [fid for fid, q in sel.quality.items() if q.label]
    assert labelled and all(sel.quality[fid].estimated for fid in sel.quality)


@pytest.mark.parametrize("name", GOOD)
def test_the_select_flow_card_raises_no_false_alarm_for_good_flows(name: str) -> None:
    from app.core.flow_choice import build_request
    from app.core.flow_value import explored_texts

    warning = empty_warning(empty_signals(explored_texts(GOLDEN / name)))
    request = build_request("j", flows_of(name), "https://x.test/", empty_warning=warning)
    assert request.flow_select is not None
    assert request.flow_select.empty_warning is None
    assert not any(q.label for q in request.flow_select.quality.values())


def test_the_storyboard_of_the_aisoeasy_run_warns_before_the_approve_button() -> None:
    from app.core.flow_value import quality_of_run
    from app.flows.storyboard import build_request

    run, flow = run_of("aisoeasy"), flows_of("aisoeasy")[0]
    quality = quality_of_run(run, GOLDEN / "aisoeasy")
    assert quality.label == NAVIGATION_ONLY and quality.empty_warning == EMPTY_WARNING
    request = build_request("j", flow, run, quality=quality)
    assert request.flow_quality is not None and request.flow_quality.label == NAVIGATION_ONLY
    assert "approve" in request.allowed_actions  # a warning, not a block


@pytest.mark.parametrize("name", GOOD)
def test_the_storyboard_of_the_good_runs_has_no_warning(name: str) -> None:
    from app.core.flow_value import quality_of_run

    q = quality_of_run(run_of(name), GOLDEN / name)
    assert q.label is None and q.empty_warning is None and q.value_actions >= 2


def test_discovery_ranks_the_flows_that_only_navigate_last() -> None:
    from app.core.flow_value import rank_by_value

    good = flows_of("todomvc")[0]
    nav = flows_of("aisoeasy")[0]
    assert [f.id for f in rank_by_value([nav, good])] == [good.id, nav.id]
    assert [f.id for f in rank_by_value([good, nav])] == [good.id, nav.id]
