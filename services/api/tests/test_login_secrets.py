import logging
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.browser.auth_detect import LoginRequired
from app.core import credentials as creds
from app.core.credentials import CredentialStore, cleanup_job_secrets, sweep_old_jobs
from app.pipeline.file_frontend import FileFrontend
from app.pipeline.runner import JobConfig, JobResult
from app.pipeline.state import update_state
from app.session.credential_login import make_credential_login
from app.session.gate import LoginGate
from tests.auth_site import EMAIL, PASSWORD, AuthSite, running_site

OUTCOME: dict[str, Any] = {}


@pytest.fixture
def site() -> Iterator[AuthSite]:
    with running_site() as s:
        yield s


# --- the store ---------------------------------------------------------------------------------------


def test_credentials_are_encrypted_at_rest_and_round_trip(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path, Fernet.generate_key())
    store.save("demo@example.com", "s3cret-pass")
    raw = (tmp_path / "credentials.enc").read_bytes()
    assert b"s3cret-pass" not in raw and b"demo@example.com" not in raw
    assert store.load() == ("demo@example.com", "s3cret-pass")
    assert (
        CredentialStore(tmp_path, Fernet.generate_key()).load() is None
    )  # another key: unreadable
    store.delete()
    assert store.load() is None and not (tmp_path / "credentials.enc").exists()


def test_a_missing_key_is_generated_once_and_never_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(creds, "_generated", None)
    with caplog.at_level(logging.WARNING, logger="credentials"):
        first = creds.encryption_key({})
        again = creds.encryption_key({})
    assert first == again and len(caplog.records) == 1
    assert "CREDENTIAL_ENCRYPTION_KEY is not set" in caplog.text
    assert first.decode() not in caplog.text


def test_the_key_from_the_environment_is_used() -> None:
    key = Fernet.generate_key()
    assert creds.encryption_key({"CREDENTIAL_ENCRYPTION_KEY": key.decode()}) == key


def test_cleanup_removes_every_secret_and_the_sweep_only_touches_old_jobs(tmp_path: Path) -> None:
    def job(name: str, age_s: float) -> Path:
        d = tmp_path / name
        (d / "login_profile" / "Default").mkdir(parents=True)
        for f in ("credentials.enc", "storage_state.json", "login_result.json", "video.mp4"):
            (d / f).write_text("x")
        old = time.time() - age_s
        os.utime(d, (old, old))
        return d

    old, new = job("old", 25 * 3600), job("new", 60)
    assert sweep_old_jobs(tmp_path) == ["old"]
    assert not (old / "credentials.enc").exists() and not (old / "login_profile").exists()
    assert (old / "video.mp4").exists()  # the result stays
    assert (new / "credentials.enc").exists()
    cleanup_job_secrets(new)
    assert not (new / "storage_state.json").exists() and (new / "video.mp4").exists()


# --- way B through the API -----------------------------------------------------------------------------


def demo_pipeline(site: AuthSite) -> Callable[[JobConfig, FileFrontend], JobResult]:
    def pipeline(cfg: JobConfig, frontend: FileFrontend) -> JobResult:
        store = CredentialStore(cfg.job_dir)
        gate = LoginGate(
            cfg.job_dir.name, cfg.job_dir, frontend,
            credential_login=make_credential_login(cfg.job_dir, site.base),
            has_credentials=store.path.is_file,
        )  # fmt: skip
        outcome = gate.ask(LoginRequired(site.base + "/login", "requested", target_url=site.base))
        OUTCOME[cfg.job_dir.name] = outcome
        OUTCOME[cfg.job_dir.name + ":files"] = sorted(p.name for p in cfg.job_dir.iterdir())
        update_state(cfg.job_dir, status="done", step="done", progress_pct=100)
        return JobResult(0, "done")

    return pipeline


def until(check: Callable[[], Any], seconds: float = 90) -> Any:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("condition not reached in time")


def card_of(c: TestClient, job_id: str, not_id: str | None = None) -> dict[str, Any]:
    def card() -> dict[str, Any] | None:
        d = c.get(f"/api/jobs/{job_id}").json()
        p = d["pending"]
        ready = d["state"]["status"] == "waiting" and p and p["kind"] == "login_required"
        return p if ready and p["interaction_id"] != not_id else None

    return until(card)  # type: ignore[no-any-return]


def send_credentials(c: TestClient, card: dict[str, Any], user: str, password: str) -> None:
    job_id = card["job_id"]
    assert (
        c.post(
            f"/api/jobs/{job_id}/login/credentials", json={"username": user, "password": password}
        ).status_code
        == 200
    )
    body = {
        "interaction_id": card["interaction_id"], "job_id": job_id, "action": "answer",
        "answers": {"login_method": "credentials"},
    }  # fmt: skip
    assert c.post(f"/api/jobs/{job_id}/respond", json=body).status_code == 200


def everything_in(directory: Path) -> str:
    return "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in directory.rglob("*") if p.is_file()
    )


def test_a_demo_account_signs_in_and_leaves_no_trace_of_itself(
    tmp_path: Path, site: AuthSite
) -> None:
    with TestClient(create_app(tmp_path / "jobs", demo_pipeline(site))) as c:
        c.app.state.runner.poll_s = 0.05  # type: ignore[attr-defined]
        job_id = c.post("/api/jobs", data={"url": site.base + "/"}).json()["state"]["job_id"]
        directory = tmp_path / "jobs" / job_id
        card = card_of(c, job_id)

        send_credentials(c, card, "wrong@example.com", "nope")  # an unknown account first
        again = card_of(c, job_id, card["interaction_id"])
        assert (
            "Sai thông tin" in again["login"]["failure"]
            and "cửa sổ đăng nhập" in again["login"]["failure"]
        )
        assert (directory / "credentials.enc").is_file()

        send_credentials(c, again, EMAIL, PASSWORD)
        until(lambda: c.get(f"/api/jobs/{job_id}").json()["state"]["status"] == "done")
        until(lambda: not (directory / "credentials.enc").exists())  # gone when the job ended
        assert OUTCOME[job_id].url == site.base + "/app"
        assert "storage_state.json" in OUTCOME[job_id + ":files"]  # it existed while the job ran
        assert not (directory / "storage_state.json").exists()  # and is gone now
        assert not (directory / "login_result.json").exists()

        text = everything_in(directory)
        assert PASSWORD not in text and "nope" not in text and EMAIL not in text
        detail = str(c.get(f"/api/jobs/{job_id}").json())
        assert PASSWORD not in detail and EMAIL not in detail and "nope" not in detail
        log = (directory / "interactions.jsonl").read_text(encoding="utf-8")
        assert '"login_method": "credentials"' in log
        assert site.posts[-2:] == ["POST /login/identify", "POST /login/password"]


def test_the_login_posts_of_the_sign_in_are_in_the_report_without_bodies(
    tmp_path: Path, site: AuthSite
) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    CredentialStore(job_dir).save(EMAIL, PASSWORD)
    assert make_credential_login(job_dir, site.base)(site.base + "/login", site.base) is None
    report = (job_dir / "login_report.json").read_text(encoding="utf-8")
    assert "127.0.0.1" in report and PASSWORD not in report and EMAIL not in report
    assert (job_dir / "storage_state.json").is_file()


def test_the_private_files_of_a_job_are_not_served(tmp_path: Path, site: AuthSite) -> None:
    with TestClient(create_app(tmp_path / "jobs", demo_pipeline(site))) as c:
        c.app.state.runner.poll_s = 0.05  # type: ignore[attr-defined]
        job_id = c.post("/api/jobs", data={"url": site.base + "/"}).json()["state"]["job_id"]
        directory = tmp_path / "jobs" / job_id
        card_of(c, job_id)
        (directory / "credentials.enc").write_bytes(b"x")
        (directory / "storage_state.json").write_text("{}")
        (directory / "login_result.json").write_text("{}")
        (directory / "login_profile" / "Default").mkdir(parents=True)
        (directory / "login_profile" / "Default" / "Cookies").write_text("c")
        (directory / "public.txt").write_text("ok")
        for name in ("credentials.enc", "storage_state.json", "login_result.json", "job.json",
                     "login_profile/Default/Cookies"):  # fmt: skip
            assert c.get(f"/api/jobs/{job_id}/files/{name}").status_code == 404, name
        assert c.get(f"/api/jobs/{job_id}/files/public.txt").status_code == 200
        c.post(f"/api/jobs/{job_id}/cancel")


def test_the_credentials_endpoint_wants_a_waiting_login_and_both_fields(
    tmp_path: Path, site: AuthSite
) -> None:
    with TestClient(create_app(tmp_path / "jobs", demo_pipeline(site))) as c:
        c.app.state.runner.poll_s = 0.05  # type: ignore[attr-defined]
        job_id = c.post("/api/jobs", data={"url": site.base + "/"}).json()["state"]["job_id"]
        card_of(c, job_id)
        empty = c.post(
            f"/api/jobs/{job_id}/login/credentials", json={"username": " ", "password": ""}
        )
        assert empty.status_code == 422 and "password" not in empty.text.lower().replace(
            "mật khẩu", ""
        )
        c.post(f"/api/jobs/{job_id}/cancel")
        until(lambda: c.get(f"/api/jobs/{job_id}").json()["state"]["status"] == "cancelled")
        late = c.post(
            f"/api/jobs/{job_id}/login/credentials", json={"username": "a", "password": "b"}
        )
        assert late.status_code == 409


def test_a_demo_account_renews_an_expired_session_without_asking(
    tmp_path: Path, site: AuthSite
) -> None:
    class NoQuestions:
        def info(self, text: str) -> None:
            pass

        def ask(self, request: Any) -> Any:
            raise AssertionError("the user must not be asked")

    CredentialStore(tmp_path).save(EMAIL, PASSWORD)
    gate = LoginGate(
        "j", tmp_path, NoQuestions(),  # type: ignore[arg-type]
        credential_login=make_credential_login(tmp_path, site.base),
        has_credentials=lambda: True,
    )  # fmt: skip
    need = LoginRequired(site.base + "/login", "session_expired", target_url=site.base + "/app")
    assert gate.ask(need).url == site.base + "/app"


# --- a failed job keeps its session, a finished or cancelled one does not -------------------------------


def _job_with_secrets(tmp_path: Path) -> Path:
    job = tmp_path / "job"
    (job / "login_profile").mkdir(parents=True)
    CredentialStore(job).save("u", "p")
    (job / "storage_state.json").write_text("{}")
    return job


@pytest.mark.parametrize(
    ("status", "kept"), [("done", False), ("cancelled", False), ("failed", True)]
)
def test_run_job_cleans_secrets_only_for_done_and_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str, kept: bool
) -> None:
    from app.pipeline import runner

    job = _job_with_secrets(tmp_path)
    monkeypatch.setattr(runner, "_run", lambda *a, **k: JobResult(0, status))  # type: ignore[arg-type]
    runner.run_job(JobConfig(url="https://x.com/", job_dir=job), None)  # type: ignore[arg-type]
    assert (job / "credentials.enc").exists() is kept
    assert (job / "storage_state.json").exists() is kept
    assert (job / "login_profile").exists() is kept


@pytest.mark.parametrize(
    ("outcome", "kept"), [("done", False), ("cancelled", False), ("failed", True)]
)
def test_the_web_worker_cleans_secrets_only_for_done_and_cancelled(
    tmp_path: Path, outcome: str, kept: bool
) -> None:
    def pipeline(cfg: JobConfig, frontend: FileFrontend) -> JobResult:
        for name, content in (("credentials.enc", "x"), ("storage_state.json", "{}")):
            (cfg.job_dir / name).write_text(content)
        update_state(cfg.job_dir, status=outcome, error="x" if outcome == "failed" else None)
        return JobResult(0, outcome)  # type: ignore[arg-type]

    with TestClient(create_app(tmp_path / "jobs", pipeline)) as c:
        c.app.state.runner.poll_s = 0.05  # type: ignore[attr-defined]
        job_id = c.post("/api/jobs", data={"url": "https://example.com/"}).json()["state"]["job_id"]
        until(lambda: c.get(f"/api/jobs/{job_id}").json()["state"]["status"] == outcome)
        time.sleep(0.4)  # the worker's cleanup runs right after the pipeline returns
        directory = tmp_path / "jobs" / job_id
        assert (directory / "credentials.enc").exists() is kept
        assert (directory / "storage_state.json").exists() is kept
