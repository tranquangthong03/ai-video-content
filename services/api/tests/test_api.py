"""The web API over a fake pipeline: create -> waiting -> respond -> ... -> done, queue, cancel."""

import json
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.worker import RESTART_ERROR, JobRunner
from app.core.interaction import make_request
from app.pipeline.file_frontend import FileFrontend
from app.pipeline.runner import JobConfig, JobResult
from app.pipeline.state import update_state

KINDS = ("confirm_understanding", "choose_concept", "outline_review", "script_review")
GATE = threading.Event()  # lets a test hold the fake pipeline before it asks anything


def fake_pipeline(cfg: JobConfig, frontend: FileFrontend) -> JobResult:
    """Asks the four questions like the real pipeline, then 'renders' a tiny video."""
    job_id = cfg.job_dir.name
    GATE.wait(5)
    update_state(
        cfg.job_dir, step="explore", progress_text="Đang phân tích trang 4/15", progress_pct=30
    )
    for kind in KINDS:
        extra: dict[str, Any] = {}
        if kind == "script_review":
            extra["script_version"] = 1
            script = {"title": "t", "headline": "h", "target_duration_s": 30, "scenes": [
                {"id": "s1", "type": "hook", "voiceover": "một hai ba bốn năm sáu bảy tám",
                 "key_point": "k", "visual": {"mode": "screenshot", "actions": []}}]}  # fmt: skip
            (cfg.job_dir / "scripts").mkdir(exist_ok=True)
            (cfg.job_dir / "scripts" / "v1.json").write_text(json.dumps(script), encoding="utf-8")
        request = make_request(job_id, kind, f"câu hỏi {kind}", **extra)
        response = frontend.ask(request)
        with (cfg.job_dir / "interactions.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "request": request.model_dump(mode="json", exclude_none=True),
                "response": response.model_dump(mode="json", exclude_none=True),
            }) + "\n")  # fmt: skip
    (cfg.job_dir / "video.mp4").write_bytes(b"0123456789" * 100)
    (cfg.job_dir / "report.json").write_text(
        json.dumps({"headline": "h", "target_ms": 30000, "actual_ms": 29000, "scenes": [],
                    "footage_ratio": 0.6}), encoding="utf-8")  # fmt: skip
    update_state(cfg.job_dir, status="done", step="done", progress_pct=100)
    return JobResult(0, "done")


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    GATE.set()
    app = create_app(tmp_path / "jobs", fake_pipeline)
    app.state.poll = 0.02
    with TestClient(app) as c:
        c.app.state.runner.poll_s = 0.02
        yield c


def until(check: Callable[[], Any], seconds: float = 6) -> Any:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("condition not reached in time")


def job(c: TestClient, job_id: str) -> dict[str, Any]:
    return c.get(f"/api/jobs/{job_id}").json()  # type: ignore[no-any-return]


def waiting_for(c: TestClient, job_id: str, kind: str) -> dict[str, Any]:
    until(
        lambda: (
            job(c, job_id)["state"]["status"] == "waiting"
            and job(c, job_id)["pending"]["kind"] == kind
        )
    )
    return job(c, job_id)


def answer(c: TestClient, d: dict[str, Any], action: str, **extra: Any):  # type: ignore[no-untyped-def]
    p = d["pending"]
    body = {"interaction_id": p["interaction_id"], "job_id": p["job_id"], "action": action, **extra}
    return c.post(f"/api/jobs/{p['job_id']}/respond", json=body)


def create(c: TestClient, url: str = "https://example.com/") -> str:
    r = c.post("/api/jobs", data={"url": url})
    assert r.status_code == 201, r.text
    return r.json()["state"]["job_id"]  # type: ignore[no-any-return]


# --- the whole flow ----------------------------------------------------------------------------


def test_a_job_goes_from_waiting_questions_to_a_downloadable_video(client: TestClient) -> None:
    job_id = create(client)
    d = waiting_for(client, job_id, "confirm_understanding")
    assert d["state"]["status"] == "waiting" and d["state"]["progress_text"].startswith(
        "Đang phân tích"
    )
    assert [s["id"] for s in d["steps"]][0] == "explore" and d["video_url"] is None

    assert answer(client, d, "answer").status_code == 200
    answer(
        client,
        waiting_for(client, job_id, "choose_concept"),
        "answer",
        answers={"concept_id": "recommended"},
    )
    answer(client, waiting_for(client, job_id, "outline_review"), "approve")
    d = waiting_for(client, job_id, "script_review")
    extra = d["pending_extra"]
    assert (
        extra["scenes"][0]["shot"] == "ảnh" and extra["headline"] == "h" and extra["version"] == 1
    )
    answer(client, d, "approve", base_version=1)

    d = until(lambda: (x := job(client, job_id))["state"]["status"] == "done" and x)
    assert (
        d["video_url"] == f"/api/jobs/{job_id}/files/video.mp4"
        and d["report"]["footage_ratio"] == 0.6
    )
    assert [h["kind"] for h in d["history"]] == list(KINDS) and d["pending"] is None
    assert client.get(d["video_url"]).content == b"0123456789" * 100
    attach = client.get(d["video_url"] + "?download=1")
    assert "attachment" in attach.headers["content-disposition"]
    ranged = client.get(d["video_url"], headers={"Range": "bytes=0-9"})
    assert ranged.status_code == 206 and ranged.content == b"0123456789"
    assert job_id in [j["job_id"] for j in client.get("/api/jobs").json()]


# --- answers are checked, in Vietnamese --------------------------------------------------------


def test_bad_answers_are_refused_with_a_vietnamese_message(client: TestClient) -> None:
    job_id = create(client)
    d = waiting_for(client, job_id, "confirm_understanding")
    stale = {"interaction_id": "int_old", "job_id": job_id, "action": "answer"}
    r = client.post(f"/api/jobs/{job_id}/respond", json=stale)
    assert r.status_code == 409 and "đã được trả lời" in r.json()["detail"]
    r = answer(client, d, "approve")  # not allowed for confirm_understanding
    assert r.status_code == 422 and "không hợp lệ ở bước này" in r.json()["detail"]
    r = client.post(f"/api/jobs/{job_id}/respond", json={"action": "answer"})
    assert r.status_code == 422 and "Dữ liệu gửi lên không hợp lệ" in r.json()["detail"]
    assert answer(client, d, "answer").status_code == 200
    waiting_for(client, job_id, "choose_concept")  # the pipeline moved on to the next question
    again = answer(client, d, "answer")  # the first question answered a second time
    assert again.status_code == 409 and "đã được trả lời" in again.json()["detail"]


def test_a_stale_script_version_is_a_conflict(client: TestClient) -> None:
    job_id = create(client)
    for kind, action in (("confirm_understanding", "answer"), ("choose_concept", "answer"),
                         ("outline_review", "approve")):  # fmt: skip
        answer(client, waiting_for(client, job_id, kind), action)
    d = waiting_for(client, job_id, "script_review")
    r = answer(client, d, "approve", base_version=0)
    assert r.status_code == 409 and "bản mới nhất là v1" in r.json()["detail"]


def test_urls_and_login_files_are_validated(client: TestClient) -> None:
    for bad in ("not a url", "ftp://example.com", "javascript:alert(1)", ""):
        r = client.post("/api/jobs", data={"url": bad})
        assert r.status_code == 422, bad
    r = client.post("/api/jobs", data={"url": "ftp://example.com"})
    assert "http" in r.json()["detail"]
    r = client.post(
        "/api/jobs", data={"url": "https://x.com"}, files={"storage_state": ("a.json", b"nope")}
    )
    assert r.status_code == 422 and "JSON" in r.json()["detail"]
    ok = client.post("/api/jobs", data={"url": "https://x.com"},
                     files={"storage_state": ("auth.json", b'{"cookies": []}')})  # fmt: skip
    assert ok.status_code == 201


# --- files -------------------------------------------------------------------------------------


def test_files_are_served_only_from_inside_the_job_dir(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    job_id = create(client, "https://x.com")
    waiting_for(client, job_id, "confirm_understanding")
    for path in ("../../secret.txt", "..%2F..%2Fsecret.txt", "%2e%2e/%2e%2e/secret.txt", "/etc/passwd",
                 "job.json", "storage_state.json"):  # fmt: skip
        assert client.get(f"/api/jobs/{job_id}/files/{path}").status_code == 404, path
    assert client.get(f"/api/jobs/{job_id}/files/state.json").status_code == 200
    assert client.get("/api/jobs/..%2F..%2F/files/x").status_code == 404
    assert client.get("/api/jobs/nope").status_code == 404


# --- queue and cancel --------------------------------------------------------------------------


def test_the_second_job_waits_in_the_queue_then_runs_by_itself(client: TestClient) -> None:
    first, second = create(client), create(client)
    waiting_for(client, first, "confirm_understanding")
    d = job(client, second)
    assert d["state"]["status"] == "queued" and d["queue_position"] == 1
    for kind, action in (("confirm_understanding", "answer"), ("choose_concept", "answer"),
                         ("outline_review", "approve"), ("script_review", "approve")):  # fmt: skip
        answer(client, waiting_for(client, first, kind), action)
    until(lambda: job(client, first)["state"]["status"] == "done")
    d = waiting_for(client, second, "confirm_understanding")  # started on its own
    assert d["queue_position"] is None


def test_cancel_takes_effect_while_waiting_and_for_a_queued_job(client: TestClient) -> None:
    first, second = create(client), create(client)
    waiting_for(client, first, "confirm_understanding")
    assert client.post(f"/api/jobs/{second}/cancel").json()["state"]["status"] == "cancelled"
    started = time.monotonic()
    client.post(f"/api/jobs/{first}/cancel")
    until(lambda: job(client, first)["state"]["status"] == "cancelled", 3)
    assert time.monotonic() - started < 2 and job(client, first)["pending"] is None
    assert client.post(f"/api/jobs/{first}/cancel").status_code == 409  # already over


# --- restart and resume ------------------------------------------------------------------------


def test_after_a_restart_running_and_waiting_jobs_are_failed_and_can_resume(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    old = JobRunner(root, fake_pipeline, start=False)
    for name, status in (
        ("jrun", "running"),
        ("jwait", "waiting"),
        ("jqueue", "queued"),
        ("jdone", "done"),
    ):
        old.create(name, "https://x.com", has_auth=False)
        update_state(root / name, status=status)
    (root / "jwait" / "pending.json").write_text("{}", encoding="utf-8")
    old.queue.clear()

    app = create_app(root, fake_pipeline)
    with TestClient(app) as c:
        states = {j["job_id"]: j for j in c.get("/api/jobs").json()}
        assert states["jrun"]["status"] == "failed" and states["jrun"]["error"] == RESTART_ERROR
        assert (
            states["jwait"]["status"] == "failed" and not (root / "jwait" / "pending.json").exists()
        )
        assert states["jdone"]["status"] == "done"
        d = until(
            lambda: (x := job(c, "jqueue"))["state"]["status"] in ("running", "waiting") and x
        )  # queued went on
        assert job(c, "jrun")["can_resume"] is True
        assert c.post("/api/jobs/jqueue/resume").status_code == 409  # still running
        r = c.post("/api/jobs/jrun/resume")
        assert r.status_code == 200 and r.json()["state"]["status"] in (
            "queued",
            "running",
            "waiting",
        )
        assert d is not None
