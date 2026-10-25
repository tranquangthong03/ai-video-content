"""Way B end to end on the fixture site with a sign-in (docs/manual-test-login.md is way A by hand).

Usage (from services/api):  uv run python scripts/acceptance_login.py <job-dir>

Serves tests/fixtures/site_auth, runs run_job with requires_login=True (the landing is public,
"Log in" leads to a 2-step form) and a user who answers the login card with a demo account. The
rest of the questions get the --auto answers. Needs the LLM key of .env, like any real run.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # services/api, for `app`
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))  # the fixture server

from auth_site import EMAIL, PASSWORD, running_site  # noqa: E402
from rich.console import Console  # noqa: E402

from app.core.credentials import CredentialStore  # noqa: E402
from app.core.interaction import make_response  # noqa: E402
from app.pipeline.explore_cli import ConsoleReporter  # noqa: E402
from app.pipeline.frontend import ScriptedFrontend  # noqa: E402
from app.pipeline.runner import JobConfig, run_job  # noqa: E402
from app.schemas.generated.interaction import InteractionRequest  # noqa: E402
from app.schemas.generated.user_response import UserResponse  # noqa: E402


class DemoUser(ScriptedFrontend):
    def __init__(self, job_dir: Path, console: Console) -> None:
        super().__init__({}, console)
        self.job_dir = job_dir
        self.log: list[str] = []

    def ask(self, request: InteractionRequest) -> UserResponse:
        if request.kind != "login_required":
            return super().ask(request)
        assert request.login is not None
        self.log.append(f"login_required ({request.login.reason}) at {request.login.login_url}")
        CredentialStore(self.job_dir).save(EMAIL, PASSWORD)  # what POST /login/credentials does
        return make_response(request, "answer", answers={"login_method": "credentials"})


def main() -> int:
    job_dir = Path(sys.argv[1])
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    console = Console()
    with running_site() as site:
        cfg = JobConfig(
            url=site.base + "/", job_dir=job_dir, requires_login=True, timeout=600, core_flow=False
        )
        user = DemoUser(job_dir, console)
        result = run_job(cfg, user, ConsoleReporter(console))
        summary = {
            "exit": result.exit_code,
            "status": result.status,
            "asked": user.log,
            "site_url": site.base,
            "posts": site.posts,
            "paths_visited": sorted(set(site.hits)),
        }
    (job_dir / "acceptance_login.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
