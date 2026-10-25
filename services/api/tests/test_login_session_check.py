import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from app.core.credentials import CredentialStore
from app.core.interaction import make_response
from app.pipeline import runner
from app.pipeline.frontend import ScriptedFrontend
from app.pipeline.runner import JobConfig, JobResult, run_job
from app.schemas.generated.interaction import InteractionRequest
from app.schemas.generated.user_response import UserResponse
from tests.auth_site import EMAIL, PASSWORD, AuthSite, running_site
from tests.test_fit_and_scene_writer import make_script
from tests.test_script_writer import make_outline, make_profile


@pytest.fixture
def site() -> Iterator[AuthSite]:
    with running_site() as s:
        yield s


class User(ScriptedFrontend):
    def __init__(self, replies: list[Callable[[InteractionRequest], UserResponse]]) -> None:
        super().__init__({}, Console(quiet=True))
        self.replies = list(replies)
        self.asked: list[InteractionRequest] = []

    def ask(self, request: InteractionRequest) -> UserResponse:
        self.asked.append(request)
        return self.replies.pop(0)(request)


def cookie_file(path: Path, sid: str) -> Path:
    cookie = {"name": "sid", "value": sid, "domain": "127.0.0.1", "path": "/", "expires": -1}
    path.write_text(json.dumps({"cookies": [cookie], "origins": []}), encoding="utf-8")
    return path


def job_ready_to_produce(tmp_path: Path, spec: dict[str, Any]) -> Path:
    """A job dir that is at the step after the script review (what produce needs is written)."""
    job = tmp_path / "job"
    job.mkdir()
    script, _ = make_script(tmp_path, 45)
    (job / "script_approved.json").write_text(script.model_dump_json(), encoding="utf-8")
    (job / "confirmed_profile.json").write_text(make_profile().model_dump_json(), encoding="utf-8")
    (job / "outline_approved.json").write_text(make_outline().model_dump_json(), encoding="utf-8")
    (job / "job.json").write_text(json.dumps(spec), encoding="utf-8")
    return job


def go(job: Path, cfg: JobConfig, user: User, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """run_job up to the produce step, which is replaced by a probe of what it would use."""
    seen: dict[str, Any] = {}

    def fake_produce(cfg: JobConfig, rep: Any, progress: Any, tracker: Any, profile: Any,
                     script: Any, caller: Any = None, on_login: Any = None,
                     ensure_session: Any = None) -> JobResult:  # fmt: skip
        assert ensure_session is not None
        ensure_session()
        seen["storage_state"] = cfg.storage_state
        return JobResult(0, "done")

    monkeypatch.setattr(runner, "run_produce_step", fake_produce)
    monkeypatch.setattr(runner, "make_caller", lambda cfg: (None, None))
    run_job(cfg, user)
    return seen


def log_of(job: Path) -> list[dict[str, Any]]:
    return json.loads((job / "login_log.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_a_session_that_is_still_good_is_checked_and_nobody_is_asked(
    site: AuthSite, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = job_ready_to_produce(tmp_path, {"url": site.base + "/"})
    state = cookie_file(job / "storage_state.json", site.new_session())
    cfg = JobConfig(url=site.base + "/", job_dir=job, storage_state=state, from_step="produce",
                    app_home_url=site.base + "/app")  # fmt: skip
    user = User([])
    seen = go(job, cfg, user, monkeypatch)
    assert user.asked == [] and seen["storage_state"] == state
    event = next(e for e in log_of(job) if e["event"] == "verify_before_produce")
    assert event["ok"] is True and event["opened"] == site.base + "/app"


def test_a_session_that_expired_while_reviewing_asks_to_sign_in_again(
    site: AuthSite, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = job_ready_to_produce(tmp_path, {"url": site.base + "/"})
    stale = cookie_file(job / "storage_state.json", "stale")

    def signs_in(request: InteractionRequest) -> UserResponse:
        cookie_file(job / "storage_state.json", site.new_session())  # the window / auth.json
        return make_response(request, "login_done")

    cfg = JobConfig(url=site.base + "/", job_dir=job, storage_state=stale, from_step="produce",
                    app_home_url=site.base + "/app", login_url=site.base + "/login")  # fmt: skip
    user = User([signs_in])
    seen = go(job, cfg, user, monkeypatch)
    card = user.asked[0]
    assert card.kind == "login_required" and card.login is not None
    assert card.login.reason == "session_expired_review"
    assert "duyệt kịch bản" in card.message and "đăng nhập lại để quay video" in card.message
    assert seen["storage_state"] == job / "storage_state.json"
    events = [e["event"] for e in log_of(job)]
    assert events[:2] == ["verify_before_produce", "login_required"]
    assert "verify_session" in events


def test_with_a_demo_account_the_session_is_renewed_without_a_question(
    site: AuthSite, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = job_ready_to_produce(tmp_path, {"url": site.base + "/"})
    stale = cookie_file(job / "storage_state.json", "stale")
    CredentialStore(job).save(EMAIL, PASSWORD)
    cfg = JobConfig(url=site.base + "/", job_dir=job, storage_state=stale, from_step="produce",
                    app_home_url=site.base + "/app", login_url=site.base + "/login")  # fmt: skip
    user = User([])
    go(job, cfg, user, monkeypatch)
    assert user.asked == []
    events = {e["event"]: e for e in log_of(job)}
    assert events["auto_relogin"]["ok"] is True and events["verify_session"]["ok"] is True
    assert EMAIL not in (job / "login_log.json").read_text(encoding="utf-8")


def test_a_job_that_lost_its_session_file_asks_instead_of_recording_the_login_page(
    site: AuthSite, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The OrangeHRM case: job.json still says there is a session, the file is gone."""
    job = job_ready_to_produce(tmp_path, {"url": site.base + "/"})
    cfg = JobConfig(url=site.base + "/", job_dir=job, storage_state=None, from_step="produce",
                    app_home_url=site.base + "/app", login_url=site.base + "/login")  # fmt: skip

    def signs_in(request: InteractionRequest) -> UserResponse:
        cookie_file(job / "storage_state.json", site.new_session())
        return make_response(request, "login_done")

    user = User([signs_in])
    seen = go(job, cfg, user, monkeypatch)
    assert user.asked[0].login is not None
    assert user.asked[0].login.reason == "session_expired_review"
    assert seen["storage_state"] == job / "storage_state.json"


def test_a_public_site_is_not_checked_at_all(
    site: AuthSite, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = job_ready_to_produce(tmp_path, {"url": site.base + "/"})
    cfg = JobConfig(url=site.base + "/", job_dir=job, from_step="produce")
    user = User([])
    go(job, cfg, user, monkeypatch)
    assert user.asked == [] and not (job / "login_log.json").exists()


def test_the_app_home_after_a_sign_in_is_kept_for_the_next_run(
    site: AuthSite, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = job_ready_to_produce(tmp_path, {"url": site.base + "/", "storage_state": None})
    cfg = JobConfig(url=site.base + "/", job_dir=job, storage_state=None, from_step="produce",
                    app_home_url=site.base + "/app", login_url=site.base + "/login")  # fmt: skip

    def signs_in(request: InteractionRequest) -> UserResponse:
        cookie_file(job / "storage_state.json", site.new_session())
        return make_response(request, "login_done")

    go(job, cfg, User([signs_in]), monkeypatch)
    spec = json.loads((job / "job.json").read_text(encoding="utf-8"))
    assert spec["app_home_url"] == site.base + "/app" and spec["login_url"] == site.base + "/login"
    assert spec["storage_state"] == "storage_state.json"
