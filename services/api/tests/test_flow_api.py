"""The web API carries the flow cards: select_flow, the storyboard, its pictures and the job spec."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.flow_choice import build_request
from app.flows.storyboard import build_request as storyboard_request
from app.pipeline.asker import ask as ask_user
from app.pipeline.file_frontend import FileFrontend
from app.pipeline.runner import JobConfig, JobResult
from app.pipeline.state import update_state
from app.schemas.generated.core_flow import CoreFlow
from tests.test_api import answer, create, job, until, waiting_for
from tests.test_flow_storyboard import make_run
from tests.test_select_flow import flow_dict

SEEN: list[JobConfig] = []
ANSWERS: dict[str, Any] = {}


def flow_pipeline(cfg: JobConfig, frontend: FileFrontend) -> JobResult:
    SEEN.append(cfg)
    job_id = cfg.job_dir.name
    flow = CoreFlow.model_validate(flow_dict("leave"))
    shared = (
        "https://opensource-demo.orangehrmlive.com/" if cfg.url.endswith("shared/") else cfg.url
    )
    ANSWERS["select"] = ask_user(frontend, cfg.job_dir, build_request(job_id, [flow], shared))
    (cfg.job_dir / "flow" / "steps").mkdir(parents=True, exist_ok=True)
    (cfg.job_dir / "flow" / "steps" / "s2.jpg").write_bytes(b"\xff\xd8\xff jpeg")
    run = make_run()
    run.steps[1].screenshot = "flow/steps/s2.jpg"
    ANSWERS["review"] = ask_user(frontend, cfg.job_dir, storyboard_request(job_id, flow, run))
    update_state(cfg.job_dir, status="done", step="done", progress_pct=100)
    (cfg.job_dir / "video.mp4").write_bytes(b"0" * 100)
    return JobResult(0, "done")


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    SEEN.clear()
    ANSWERS.clear()
    app = create_app(tmp_path / "jobs", flow_pipeline)
    app.state.poll = 0.02
    with TestClient(app) as c:
        c.app.state.runner.poll_s = 0.02
        yield c


def test_the_flow_cards_reach_the_browser_and_the_answers_reach_the_pipeline(
    client: TestClient,
) -> None:
    job_id = create(client)
    d = waiting_for(client, job_id, "select_flow")
    pending = d["pending"]
    assert pending["flows"][0]["id"] == "leave" and pending["flow_select"]["default"] == ["leave"]
    assert pending["flow_select"].get("submit_blocked_reason") is None  # None is not sent
    ok = answer(client, d, "answer", answers={"selected_flows": ["leave"], "allow_submit": "true"})
    assert ok.status_code == 200

    d = waiting_for(client, job_id, "flow_storyboard_review")
    review = d["pending"]["flow_review"]
    assert review["status"] == "stopped_before_submit" and len(review["steps"]) == 7
    assert d["pending"]["script_version"] == 1
    picture = client.get(f"/api/jobs/{job_id}/files/{review['steps'][1]['screenshot']}")
    assert picture.status_code == 200 and picture.content.startswith(b"\xff\xd8")
    assert answer(client, d, "edit", edit={"instruction": "bỏ bước 3"}).status_code == 200
    until(lambda: job(client, job_id)["state"]["status"] == "done")
    assert ANSWERS["select"].answers == {"selected_flows": ["leave"], "allow_submit": "true"}
    assert ANSWERS["review"].edit.instruction == "bỏ bước 3"


def test_a_shared_demo_site_tells_the_card_why_submit_cannot_be_turned_on(
    client: TestClient,
) -> None:
    job_id = create(client, "https://opensource-demo.orangehrmlive.com/shared/")
    d = waiting_for(client, job_id, "select_flow")
    assert "dùng chung" in d["pending"]["flow_select"]["submit_blocked_reason"]
    answer(client, d, "cancel")


def test_the_web_runs_the_core_flow_route_unless_the_job_says_otherwise(tmp_path: Path) -> None:
    import threading

    from app.api.worker import JOB_FILE, JobRunner

    seen: list[bool] = []

    def pipeline(cfg: JobConfig, frontend: Any) -> JobResult:
        seen.append(cfg.core_flow)
        return JobResult(0, "done")

    runner = JobRunner(tmp_path / "jobs", pipeline, start=False)  # driven by hand, no worker thread
    try:
        for job_id, extra in (("j1", {}), ("j2", {"core_flow": False})):
            directory = runner.create(job_id, "https://x.test/", has_auth=False)
            spec = json.loads((directory / JOB_FILE).read_text("utf-8"))
            (directory / JOB_FILE).write_text(json.dumps({**spec, **extra}), "utf-8")
            runner._run(job_id, threading.Event())
    finally:
        runner.stop()
    assert seen == [True, False]
