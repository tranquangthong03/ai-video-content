import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.browser.session import BrowserSession
from app.flows.agent import FlowAgent
from app.recorder import sync
from app.recorder.live import LiveFilm, classify_failures, same_element
from app.schemas.generated.flow_run import FlowRun
from tests.test_flow_agent import FILL, flow_for, make_caller, step

pytestmark = pytest.mark.slow


def sig(name: str = "yyyy-dd-mm", x: float = 100, y: float = 200, index: int = 0) -> dict[str, Any]:
    return {"tag": "input", "name": name, "x": x, "y": y, "index": index}


def attempt(
    ok: bool, s: dict[str, Any] | None, start: int, do: str = "pick_date"
) -> dict[str, Any]:
    return {"start": start, "end": start + 800, "ok": ok, "do": do, "sig": s, "step": None}


# --- which failed attempt is a retry ----------------------------------------------------------


def test_the_same_resolved_element_is_told_by_tag_name_place_and_index() -> None:
    assert same_element(sig(), sig(x=105, y=196))  # within 8 px
    assert not same_element(sig(), sig(x=109))  # 9 px away
    assert not same_element(sig(), sig(y=300, index=1))  # the other field of the same name
    assert not same_element(sig(), sig(index=1))
    assert not same_element(sig(), {**sig(), "tag": "select"})
    assert not same_element(sig(), sig(name="To Date"))
    assert not same_element(None, sig()) and not same_element(sig(), None)


def test_a_wrong_try_on_one_field_and_a_right_one_on_the_other_are_not_retries() -> None:
    first, second = sig(y=200, index=0), sig(y=300, index=1)  # two fields called «yyyy-dd-mm»
    segments = classify_failures([attempt(False, first, 1000), attempt(True, second, 3000)])
    assert [(s["kind"], s["from_ms"]) for s in segments] == [("rejected", 1000)]


def test_a_wrong_try_followed_by_a_right_one_on_the_same_field_is_a_retry() -> None:
    first = sig(y=200, index=0)
    segments = classify_failures(
        [
            attempt(False, first, 1000),
            attempt(False, sig(y=300, index=1), 2500),
            attempt(True, sig(y=203), 4000),
        ]
    )
    assert [(s["kind"], s["from_ms"]) for s in segments] == [("retry", 1000), ("rejected", 2500)]
    other_kind = classify_failures(
        [attempt(False, first, 1000), attempt(True, first, 3000, do="type")]
    )
    assert other_kind[0]["kind"] == "rejected"  # a different kind of action is not a second try
    assert (
        classify_failures([attempt(False, None, 500), attempt(True, first, 900)])[0]["kind"]
        == "rejected"
    )


# --- the film made while the agent runs ---------------------------------------------------------


@pytest.fixture
def live(browser_session: BrowserSession) -> Iterator[BrowserSession]:
    yield browser_session


def run_live(
    session: BrowserSession,
    site: str,
    tmp_path: Path,
    plan: list[dict[str, Any]],
    delay: float = 0.0,
) -> tuple[FlowRun, LiveFilm, dict[str, Any]]:
    caller, llm = make_caller(tmp_path, plan)
    if delay:  # a model that takes its time, like the real one
        answer = llm.handler
        llm.handler = lambda prompt: (time.sleep(delay), answer(prompt))[1]
    job = tmp_path / "job"
    flow = flow_for(site)
    film = LiveFilm(session, job, root_url=flow.start_url, seed="t")
    run = FlowAgent(session, caller, flow, job, film=film).run()
    logs = json.loads((job / run.live.logs).read_text("utf-8")) if run.live else {}  # type: ignore[union-attr]
    return run, film, logs


def test_the_agent_leaves_a_clip_logs_marks_and_one_wait_per_question(
    live: BrowserSession, site: str, tmp_path: Path
) -> None:
    plan = [*FILL, step("stop_before_submit", "Apply")]
    run, film, logs = run_live(live, site, tmp_path, plan)
    assert run.status == "stopped_before_submit" and run.live is not None
    clip = tmp_path / "job" / run.live.clip
    assert clip.is_file() and run.live.content_ms > 0
    assert run.live.start_offset_ms > run.live.pulse_at_ms + sync.PULSE_MS  # the pulse is cut off
    assert abs(run.live.sync_offset_ms) < sync.MAX_OFFSET_MS
    assert [m.i for m in run.live.marks] == list(
        range(2, len(run.steps) + 1)
    )  # every step but goto
    waits = [s for s in run.live.segments if s.kind == "llm_wait"]
    assert len(waits) == run.llm_calls == 6
    assert all(m.end_ms - m.start_ms >= 1400 for m in run.live.marks[:5])  # each one is held
    assert logs["focus_log"] and logs["inventory"] and logs["action_log"] and logs["click_log"]
    assert not (tmp_path / "job" / "flow" / "live" / "raw").exists()  # only the mp4 stays


def test_nothing_moves_on_the_page_while_the_model_is_asked(
    live: BrowserSession, site: str, tmp_path: Path
) -> None:
    plan = [*FILL, step("stop_before_submit", "Apply")]
    run, film, logs = run_live(live, site, tmp_path, plan)
    assert run.live is not None and film.rec is not None
    waits = [(s.from_ms, s.to_ms) for s in run.live.segments if s.kind == "llm_wait"]
    system_events = [e["t_ms"] for e in logs["click_log"]]  # clicks, hovers, scrolls
    system_events += [f["t_ms"] for f in logs["focus_log"]] + [
        a["t_ms"] for a in logs["action_log"]
    ]
    system_events += film.rec.marks  # the cursor moving, a key typed
    for t in system_events:
        assert not any(a < t < b for a, b in waits), f"something happened at {t} ms during a wait"


def test_a_wrong_option_then_the_right_one_leaves_a_retry_to_cut(
    live: BrowserSession, site: str, tmp_path: Path
) -> None:
    wrong = step("select", "Reason category", value="Personal")
    right = step("select", "Reason category", value="Medical")
    plan = [FILL[0], wrong, right, *FILL[2:], step("stop_before_submit", "Apply")]
    run, _, _ = run_live(live, site, tmp_path, plan)
    assert run.live is not None and run.status == "stopped_before_submit"
    kinds = [s.kind for s in run.live.segments if s.kind != "llm_wait"]
    assert kinds == ["retry"]
    retry = next(s for s in run.live.segments if s.kind == "retry")
    assert "select" in retry.note and "Reason category" in retry.note
    assert not any(m.start_ms < retry.to_ms and retry.from_ms < m.end_ms for m in run.live.marks)


def test_a_made_up_ref_is_a_rejected_segment_and_no_step(
    live: BrowserSession, site: str, tmp_path: Path
) -> None:
    plan = [step("click", "!invented"), *FILL, step("stop_before_submit", "Apply")]
    run, _, _ = run_live(live, site, tmp_path, plan)
    assert run.live is not None
    assert [s.kind for s in run.live.segments if s.kind != "llm_wait"] == ["rejected"]
