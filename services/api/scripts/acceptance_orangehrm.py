"""Acceptance on the real OrangeHRM demo (docs/login-acceptance/orangehrm-*.md).

Usage (from services/api):
  uv run python scripts/acceptance_orangehrm.py main <job-dir>
      way B, 2 features, a 6+ minute wait on the script review
  uv run python scripts/acceptance_orangehrm.py expired <job-dir> <finished-job-dir>
      way C: a saved session without its login cookie

The demo site is shared: nothing here creates, edits or deletes data (the request guard only lets
the sign-in post through; the report shows what it let through and refused).
"""

import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # services/api, for `app`

from rich.console import Console  # noqa: E402

from app.core.credentials import CredentialStore  # noqa: E402
from app.core.features import fold  # noqa: E402
from app.core.interaction import make_response  # noqa: E402
from app.pipeline.explore_cli import ConsoleReporter  # noqa: E402
from app.pipeline.frontend import ScriptedFrontend  # noqa: E402
from app.pipeline.runner import JobConfig, run_job  # noqa: E402
from app.schemas.generated.interaction import InteractionRequest  # noqa: E402
from app.schemas.generated.user_response import UserResponse  # noqa: E402

SITE = "https://opensource-demo.orangehrmlive.com/"
HOME = SITE + "web/index.php/dashboard/index"
LOGIN = SITE + "web/index.php/auth/login"
WAIT_S = 6 * 60 + 20  # on the script review: longer than the 6 minutes asked for
WANTED = [("dashboard", "quick launch", "bang dieu khien"), ("leave", "my actions", "nghi phep")]


def has_any(text: str, words: tuple[str, ...]) -> bool:
    return any(w in fold(text) for w in words)


class OrangeUser(ScriptedFrontend):
    def __init__(self, job_dir: Path, console: Console) -> None:
        super().__init__({}, console)
        self.job_dir = job_dir
        self.log: list[dict[str, object]] = []
        self.reviews = 0

    def note(self, event: str, **fields: object) -> None:
        self.log.append({"at": time.strftime("%H:%M:%S"), "event": event, **fields})

    def ask(self, request: InteractionRequest) -> UserResponse:
        if request.kind == "login_required":
            assert request.login is not None
            self.note("login_required", reason=request.login.reason, failure=request.login.failure,
                      message=request.message)  # fmt: skip
            CredentialStore(self.job_dir).save("Admin", "admin123")  # what /login/credentials does
            return make_response(request, "answer", answers={"login_method": "credentials"})
        if request.kind == "select_features" and request.profile and request.selection:
            picked: list[str] = []
            for words in WANTED:
                found = next(
                    (
                        f.id
                        for f in request.profile.features
                        if f.id not in picked and has_any(f"{f.id} {f.name} {f.description}", words)
                    ),
                    None,
                )
                if found:
                    picked.append(found)
            picked += [f for f in request.selection.default if f not in picked][: 2 - len(picked)]
            self.note("select_features", picked=picked)
            return make_response(request, "answer", answers={"selected_features": picked})
        if request.kind == "script_review" and self.reviews == 0:
            self.reviews += 1
            self.note("script_review_wait", seconds=WAIT_S)
            time.sleep(WAIT_S)  # the session may run out while the user reads
            self.note("script_review_approve")
        return super().ask(request)


def main_run(job_dir: Path) -> int:
    console = Console()
    user = OrangeUser(job_dir, console)
    cfg = JobConfig(
        url=SITE, job_dir=job_dir, requires_login=True, timeout=900, core_flow=False
    )  # the feature route (the flow route has its own driver)
    result = run_job(cfg, user, ConsoleReporter(console))
    (job_dir / "acceptance_orangehrm.json").write_text(
        json.dumps({"exit": result.exit_code, "status": result.status, "user": user.log},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )  # fmt: skip
    return result.exit_code


class ExpiredUser(ScriptedFrontend):
    """Way C: nobody can bring a new session, so the card is read and then cancelled."""

    def __init__(self, console: Console) -> None:
        super().__init__({}, console)
        self.cards: list[dict[str, object]] = []

    def ask(self, request: InteractionRequest) -> UserResponse:
        if request.kind == "login_required":
            assert request.login is not None
            self.cards.append({"reason": request.login.reason, "message": request.message,
                               "login_url": request.login.login_url})  # fmt: skip
            return make_response(request, "cancel")
        return super().ask(request)


def expired_run(job_dir: Path, finished: Path) -> int:
    """A job at the produce step whose saved session has lost its login cookie."""
    from playwright.sync_api import sync_playwright

    job_dir.mkdir(parents=True, exist_ok=True)
    for name in ("confirmed_profile.json", "outline_approved.json", "script_approved.json"):
        shutil.copy(finished / name, job_dir / name)
    (job_dir / "state.json").unlink(missing_ok=True)
    state = job_dir / "storage_state.json"
    with sync_playwright() as pw:  # a real, signed-in session...
        from app.browser.login import perform_login

        browser = pw.chromium.launch()
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(LOGIN, wait_until="domcontentloaded")
        attempt = perform_login(page, "Admin", "admin123")
        ctx.storage_state(path=str(state))
        browser.close()
    data = json.loads(state.read_text(encoding="utf-8"))
    data["cookies"] = [c for c in data["cookies"] if c["name"] != "orangehrm"]  # ...made to expire
    state.write_text(json.dumps(data), encoding="utf-8")
    console = Console()
    user = ExpiredUser(console)
    cfg = JobConfig(url=HOME, job_dir=job_dir, storage_state=state, from_step="produce",
                    app_home_url=HOME, login_url=LOGIN)  # fmt: skip
    result = run_job(cfg, user, ConsoleReporter(console))
    summary = {
        "fresh_login_ok": attempt.ok,
        "cards": user.cards,
        "status": result.status,
        "video_exists": (job_dir / "video.mp4").is_file(),
    }
    (job_dir / "acceptance_expired.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    mode, target = sys.argv[1], Path(sys.argv[2])
    code = main_run(target) if mode == "main" else expired_run(target, Path(sys.argv[3]))
    sys.exit(code)
