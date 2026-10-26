import shutil
from pathlib import Path
from typing import Any

import pytest

from app.browser.session import BrowserSession
from app.producer.live_clip import (
    WAIT_PAD_MS,
    cuts_from_segments,
    live_usable,
    recording_from_live,
)
from app.producer.pipeline import produce
from app.producer.render import probe
from app.recorder import sync
from app.recorder.flow import FlowRecorder
from app.schemas.generated.flow_run import FlowRun
from app.schemas.generated.script import Script
from tests.test_flow_agent import FILL, step
from tests.test_flow_record import THEME, scene
from tests.test_live_film import run_live
from tests.test_producer import tiny_mp4

pytestmark = pytest.mark.slow


def seg(kind: str, a: int, b: int) -> dict[str, Any]:
    return {"kind": kind, "from_ms": a, "to_ms": b}


def test_waits_are_cut_with_a_pad_and_failed_tries_whole() -> None:
    planned = cuts_from_segments(
        [seg("llm_wait", 1000, 5000), seg("retry", 6000, 7000), seg("rejected", 8000, 8400)]
    )
    assert [(c.from_ms, c.to_ms) for c in planned.cuts] == [
        (1000 + WAIT_PAD_MS, 5000 - WAIT_PAD_MS), (6000, 7000), (8000, 8400),
    ]  # fmt: skip
    assert (planned.llm_wait_ms, planned.retry, planned.rejected) == (3600, 1, 1)


def test_a_short_wait_is_left_alone_and_touching_cuts_are_merged() -> None:
    planned = cuts_from_segments(
        [seg("llm_wait", 1000, 1500), seg("retry", 2000, 3000), seg("rejected", 3000, 3500)]
    )
    assert [(c.from_ms, c.to_ms) for c in planned.cuts] == [(2000, 3500)]  # 300 ms of wait: no cut
    assert planned.llm_wait_ms == 0


@pytest.fixture(scope="module")
def live_job(
    browser_session: BrowserSession, site: str, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, FlowRun]:
    base = tmp_path_factory.mktemp("live")
    wrong = step("select", "Reason category", value="Personal")  # a retry to cut as well
    right = step("select", "Reason category", value="Medical")
    plan = [FILL[0], wrong, right, *FILL[2:], step("stop_before_submit", "Apply", chapter="Gửi")]
    run, _, _ = run_live(browser_session, site, base, plan, delay=1.6)
    assert run.live is not None and run.status == "stopped_before_submit"
    return base / "job", run


def test_the_cut_clip_is_as_long_as_the_film_minus_what_was_cut(
    live_job: tuple[Path, FlowRun],
) -> None:
    job, run = live_job
    assert live_usable(job, run)
    rec = recording_from_live(job, run)
    raw_ms = int(probe(job / run.live.clip)["duration_ms"])  # type: ignore[union-attr]
    segments = [
        {
            "kind": s.kind,
            "from_ms": s.from_ms + run.live.sync_offset_ms,
            "to_ms": s.to_ms + run.live.sync_offset_ms,
        }
        for s in run.live.segments
    ]  # type: ignore[union-attr]
    planned = cuts_from_segments(segments)
    removed = sum(c.length for c in planned.cuts)
    assert rec.source == "live" and rec.llm_wait_cut_ms > 0 and rec.retry_cut == 1
    assert abs(rec.content_ms - (raw_ms - removed)) <= 150
    assert (
        rec.content_ms < raw_ms - 5000
    )  # six model waits and a retry are gone: seconds, not frames
    assert rec.sync_offset_ms == 0 and rec.failed_at is None
    assert [m.i for m in rec.marks] == [m.i for m in run.live.marks]  # type: ignore[union-attr]
    spans = [(m.start_ms, m.end_ms) for m in rec.marks]
    assert all(a < b for a, b in spans) and all(
        spans[n][1] <= spans[n + 1][0] + 60 for n in range(len(spans) - 1)
    )
    assert spans[-1][1] <= rec.content_ms + 100 and rec.start_offset_ms > rec.pulse_at_ms


def test_the_logs_follow_the_cuts_so_the_pulse_is_where_the_log_says(
    live_job: tuple[Path, FlowRun],
) -> None:
    job, run = live_job
    rec = recording_from_live(job, run)
    assert rec.clip_path is not None
    seen = sync.find_pulse(rec.clip_path)  # the clip's own clock = the log clock now
    assert seen is not None and abs(seen - rec.pulse_at_ms) <= 150
    assert not sync.video_has_pulse(rec.clip_path, rec.start_offset_ms, fps=15)
    assert all(
        0 <= e["t_ms"] <= rec.content_ms + 100
        for e in rec.focus_log + rec.click_log + rec.inventory
    )


def test_a_chapter_cut_from_the_live_clip_is_a_normal_recording(
    live_job: tuple[Path, FlowRun], tmp_path: Path
) -> None:
    job, run = live_job
    recorder = FlowRecorder(run, job, live=recording_from_live(job, run))
    recorder._record(None, tmp_path, {})  # type: ignore[arg-type]  # nothing to record: it is there
    results = [
        recorder._chapter(recorder.recording, c.id, tmp_path, f"s_{c.id}") for c in run.chapters
    ]  # type: ignore[arg-type]
    assert all(r.kind == "recording" and r.clip_path and r.clip_path.is_file() for r in results)
    assert all(r.inventory and r.focus_log and r.action_log for r in results)
    total = sum(r.content_ms for r in results)
    assert abs(total - recorder.recording.content_ms) < 400  # type: ignore[union-attr]
    hook = recorder._hook(recorder.recording, tmp_path, "sh")  # type: ignore[arg-type]
    assert hook is not None and hook.kind == "recording"


def make_script(run: FlowRun, site: str) -> Script:
    chapters = [c.id for c in run.chapters][:2]
    scenes = [scene("s1", "hook").model_dump()]
    scenes += [scene(f"s{i + 2}", "feature_demo", c).model_dump() for i, c in enumerate(chapters)]
    scenes += [scene("s9", "cta").model_dump()]
    script = Script.model_validate({
        "title": "t", "goal": "tutorial", "aspect_ratio": "9:16", "target_duration_s": 30,
        "headline": "Xin nghỉ trong một phút", "theme": THEME, "flow_id": run.flow_id, "scenes": scenes,
    })  # fmt: skip
    for sc in script.scenes:
        sc.root.visual.mode = "recording"
    script.scenes[-1].root.visual.page = site + "/flow_home.html"
    return script


def test_produce_uses_the_live_clip_and_does_not_replay(
    browser_session: BrowserSession,
    site: str,
    live_job: tuple[Path, FlowRun],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    src, run = live_job
    job = tmp_path / "job"
    shutil.copytree(src, job)
    (job / "flow" / "flow_approved.json").write_text(run.model_dump_json(), encoding="utf-8")
    import app.recorder.flow as flow_mod

    def no_replay(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("the flow was replayed although a live clip exists")

    monkeypatch.setattr(flow_mod, "record_flow", no_replay)
    seen: list[dict[str, Any]] = []

    def render(props: dict[str, Any], out: Path, work: Path) -> Any:
        seen.append(props)
        tiny_mp4(out)
        return type("R", (), {"render_ms": 1})()

    result = produce(
        make_script(run, site), url=site + "/flow_apply.html", job_dir=job, session=browser_session,
        render=render, progress=None,
    )  # fmt: skip
    flow = result.report["flow"]
    assert flow["clip_source"] == "live" and flow["llm_wait_cut_ms"] > 0
    assert flow["retry_segments_cut"] == 1 and flow["replay_failed_at"] is None
    assets = seen[0]["assets"]
    assert (
        all(assets[i].get("clip_url") for i in ("s1", "s2", "s3"))
        and result.report["dropped_scenes"] == []
    )
    assert result.report["footage_ratio"] >= 0.5
