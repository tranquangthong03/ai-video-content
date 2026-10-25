import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from app.browser.auth_detect import LoginRequired
from app.browser.login_find import find_login_url, pick_login_link
from app.core.interaction import make_response
from app.pipeline.asker import Cancelled, redact
from app.pipeline.frontend import ScriptedFrontend
from app.pipeline.runner import JobConfig, run_job
from app.producer.pipeline import produce
from app.recorder.record import RecordResult
from app.schemas.generated.interaction import InteractionRequest
from app.schemas.generated.user_response import UserResponse
from app.session.gate import LoginGate
from tests.auth_site import AuthSite, running_site
from tests.test_fit_and_scene_writer import make_script
from tests.test_producer import tiny_mp4
from tests.test_script_writer import make_profile


class UserFrontend(ScriptedFrontend):
    """A user who answers each login_required card with a function of (request, answer number)."""

    def __init__(self, replies: list[Callable[[InteractionRequest], UserResponse]]) -> None:
        super().__init__({}, Console(quiet=True))
        self.replies = list(replies)
        self.asked: list[InteractionRequest] = []

    def ask(self, request: InteractionRequest) -> UserResponse:
        self.asked.append(request)
        return self.replies.pop(0)(request)


def signs_in(site: AuthSite, job_dir: Path, *, valid: bool = True) -> Callable[..., UserResponse]:
    """The user signs in (a session file appears), then presses "done"."""

    def reply(request: InteractionRequest) -> UserResponse:
        sid = site.new_session() if valid else "stale"
        cookie = {"name": "sid", "value": sid, "domain": "127.0.0.1", "path": "/", "expires": -1}
        (job_dir / "storage_state.json").write_text(
            json.dumps({"cookies": [cookie], "origins": []}), encoding="utf-8"
        )
        return make_response(request, "login_done")

    return reply


@pytest.fixture
def site() -> Any:
    with running_site() as s:
        yield s


# --- finding the login link ------------------------------------------------------------------------


def test_the_login_link_is_picked_by_text_then_by_href() -> None:
    links = [
        {"text": "Pricing", "href": "/pricing"},
        {"text": "Sign up free", "href": "/signup"},
        {"text": "Go to app", "href": "https://app.example.com/"},
        {"text": "Log in", "href": "/login"},
    ]
    assert pick_login_link(links, "https://example.com/") == "https://example.com/login"
    assert pick_login_link(links[:3], "https://example.com/") == "https://app.example.com/"
    assert (
        pick_login_link([{"text": "Đăng nhập", "href": "/dn"}], "https://x.vn") == "https://x.vn/dn"
    )
    assert pick_login_link([{"text": "Blog", "href": "/blog"}], "https://x.com") is None
    assert pick_login_link([{"text": "Log in", "href": "mailto:a@b.c"}], "https://x.com") is None


def test_the_login_link_of_the_fixture_landing(site: AuthSite) -> None:
    assert find_login_url(site.base + "/") == site.base + "/login"


# --- the gate ----------------------------------------------------------------------------------


def test_the_user_signs_in_and_lands_on_the_app(site: AuthSite, tmp_path: Path) -> None:
    ui = UserFrontend([signs_in(site, tmp_path)])
    gate = LoginGate("j1", tmp_path, ui)
    outcome = gate.ask(LoginRequired(site.base + "/login", "requested", target_url=site.base + "/"))
    assert outcome.url == site.base + "/app"  # /login sends a signed-in visitor to the app
    assert outcome.storage_state == tmp_path / "storage_state.json"
    card = ui.asked[0]
    assert card.kind == "login_required" and card.allowed_actions == [
        "login_done",
        "answer",
        "cancel",
    ]
    assert card.login is not None and card.login.login_url == site.base + "/login"
    assert card.login.methods == ["browser_window", "credentials", "upload_state"]
    assert card.login.can_enter_url is False and card.login.failure is None


def test_a_session_that_does_not_get_in_keeps_the_card_with_the_reason(
    site: AuthSite, tmp_path: Path
) -> None:
    ui = UserFrontend([signs_in(site, tmp_path, valid=False), signs_in(site, tmp_path)])
    outcome = LoginGate("j1", tmp_path, ui).ask(LoginRequired(site.base + "/login", "redirect"))
    assert outcome.url.endswith("/app")
    assert len(ui.asked) == 2
    assert ui.asked[1].login is not None
    assert ui.asked[1].login.failure == "Chưa vào được trang bên trong, vui lòng thử lại."


def test_done_without_any_session_file_is_refused(site: AuthSite, tmp_path: Path) -> None:
    ui = UserFrontend([lambda r: make_response(r, "login_done"), signs_in(site, tmp_path)])
    LoginGate("j1", tmp_path, ui).ask(LoginRequired(site.base + "/login", "redirect"))
    assert ui.asked[1].login is not None and ui.asked[1].login.failure is not None


def test_without_a_known_login_page_the_user_types_one(site: AuthSite, tmp_path: Path) -> None:
    ui = UserFrontend(
        [
            lambda r: make_response(r, "answer", answers={"login_url": site.base + "/login"}),
            signs_in(site, tmp_path),
        ]
    )
    outcome = LoginGate("j1", tmp_path, ui).ask(
        LoginRequired("", "requested", target_url=site.base)
    )
    assert ui.asked[0].login is not None and ui.asked[0].login.can_enter_url is True
    assert ui.asked[1].login is not None and ui.asked[1].login.login_url == site.base + "/login"
    assert outcome.url.endswith("/app")


def test_cancel_stops_the_job(site: AuthSite, tmp_path: Path) -> None:
    ui = UserFrontend([lambda r: make_response(r, "cancel")])
    with pytest.raises(Cancelled):
        LoginGate("j1", tmp_path, ui).ask(LoginRequired(site.base + "/login", "redirect"))


def test_an_expired_session_is_checked_against_the_page_that_was_wanted(
    site: AuthSite, tmp_path: Path
) -> None:
    ui = UserFrontend([signs_in(site, tmp_path)])
    need = LoginRequired(
        site.base + "/login", "session_expired", target_url=site.base + "/app/items"
    )
    assert LoginGate("j1", tmp_path, ui).ask(need).url == site.base + "/app/items"


def test_secrets_never_reach_the_interaction_log(site: AuthSite, tmp_path: Path) -> None:
    ui = UserFrontend(
        [
            lambda r: make_response(
                r,
                "answer",
                answers={"login_method": "credentials", "username": "u", "password": "p"},
            ),
            lambda r: make_response(r, "cancel"),
        ]
    )
    with pytest.raises(Cancelled):
        LoginGate("j1", tmp_path, ui).ask(LoginRequired(site.base + "/login", "redirect"))
    log = (tmp_path / "interactions.jsonl").read_text(encoding="utf-8")
    assert '"password": "p"' not in log and '"username": "u"' not in log and "***" in log
    assert redact({"a": [{"Password": "x"}], "b": ""}) == {"a": [{"Password": "***"}], "b": ""}


# --- inside the pipeline ---------------------------------------------------------------------------


class StopHere(Exception):
    pass


def test_requires_login_asks_first_and_explores_from_the_app_page(
    site: AuthSite, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    class FakeExplorer:
        def __init__(
            self, url: str, job_dir: Path, *a: Any, storage_state: Path | None = None, **k: Any
        ):
            seen["url"], seen["storage"], seen["scope"] = url, storage_state, k.get("scope")

        def run(self) -> None:
            raise StopHere

    monkeypatch.setattr("app.pipeline.runner.ExploreRunner", FakeExplorer)
    monkeypatch.setattr("app.pipeline.runner.make_caller", lambda cfg: (None, None))
    ui = UserFrontend([signs_in(site, tmp_path)])
    cfg = JobConfig(url=site.base + "/", job_dir=tmp_path, requires_login=True)
    with pytest.raises(StopHere):
        run_job(cfg, ui)
    assert ui.asked[0].login is not None and ui.asked[0].login.login_url == site.base + "/login"
    assert (
        seen["url"] == site.base + "/app"
    )  # exploring starts where the sign-in led, not the landing
    assert seen["storage"] == tmp_path / "storage_state.json"


def test_an_expired_session_in_the_middle_of_exploring_asks_and_resumes(
    site: AuthSite, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    class FakeExplorer:
        def __init__(self, url: str, *a: Any, storage_state: Path | None = None, **k: Any):
            self.url, self.storage_state = url, storage_state

        def run(self) -> None:
            calls.append("run")
            if len(calls) == 1:
                raise LoginRequired(site.base + "/login", "session_expired", target_url=self.url)
            raise StopHere

        def use_session(self, storage_state: Path | None, url: str | None = None) -> None:
            calls.append(f"use_session {url}")
            self.storage_state = storage_state

    monkeypatch.setattr("app.pipeline.runner.ExploreRunner", FakeExplorer)
    monkeypatch.setattr("app.pipeline.runner.make_caller", lambda cfg: (None, None))
    ui = UserFrontend([signs_in(site, tmp_path)])
    cfg = JobConfig(url=site.base + "/app", job_dir=tmp_path)
    with pytest.raises(StopHere):
        run_job(cfg, ui)
    assert calls == ["run", f"use_session {site.base}/app", "run"]  # the same start page, redone
    assert cfg.storage_state == tmp_path / "storage_state.json"


def test_an_expired_session_while_recording_redoes_that_scene_only(
    site: AuthSite, tmp_path: Path
) -> None:
    script, _ = make_script(tmp_path, 45)
    recorded: list[str] = []
    logins: list[str] = []

    def recorder(
        session: Any, scene: Any, out_dir: Path, speech_ms: int, **kw: Any
    ) -> RecordResult:
        s = scene.root
        if s.visual.mode == "screenshot":
            img = out_dir / f"{s.id}.png"
            img.parent.mkdir(parents=True, exist_ok=True)
            img.write_bytes(b"png")
            return RecordResult(kind="screenshot", image_path=img)
        if s.visual.mode != "recording":
            return RecordResult(kind="template")
        recorded.append(f"{s.id}:{session.storage_state}")
        if s.id == "s3" and not logins:
            raise LoginRequired(site.base + "/login", "session_expired")
        return RecordResult(
            kind="recording", clip_path=tiny_mp4(out_dir / f"{s.id}.mp4"), start_offset_ms=500,
            setup_end_ms=500, content_ms=9000, steps_ok=1,
        )  # fmt: skip

    def on_login(need: LoginRequired) -> Path:
        logins.append(need.reason)
        return tmp_path / "new_state.json"

    class Session:
        storage_state: Path | None = tmp_path / "old_state.json"

    def render(props: dict[str, Any], out: Path, work: Path) -> Any:
        tiny_mp4(out)
        return type("R", (), {"render_ms": 1})()

    produce(
        script, url=site.base, job_dir=tmp_path / "job", session=Session(),  # type: ignore[arg-type]
        render=render, profile=make_profile(), recorder=recorder, on_login=on_login,
    )  # fmt: skip
    assert logins == ["session_expired"]
    s3 = [r for r in recorded if r.startswith("s3")]
    assert s3[0].endswith("old_state.json") and s3[1].endswith("new_state.json")
    assert [r.split(":")[0] for r in recorded].count("s2") == 1  # earlier scenes are not redone
