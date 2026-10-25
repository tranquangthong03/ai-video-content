"""Core-flow acceptance on real sites (docs/core-flow/).

Usage (from services/api):
  uv run python scripts/acceptance_flow.py <orangehrm|todomvc|squoosh> <job-dir>
  uv run python scripts/acceptance_flow.py <site> <job-dir> --report-only   # rebuild the report

The user is played by a script:
- orangehrm: signs in with the demo account (way B) and describes "Nhân viên xin nghỉ phép 2 ngày
  rồi xem trạng thái đơn"; policy stop (the demo site is shared: nothing may be written, the report
  checks that the request count is 0).
- todomvc: picks the proposed "list of tasks" flow (or describes it), submit allowed (the data only
  lives in the browser that films it).
- squoosh: picks the proposed "compress and compare" flow (or describes it); nothing is sent.
A storyboard that did not reach its goal is rerun once ("regenerate"), then approved if usable.
"""

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # services/api, for `app`
sys.path.insert(0, str(Path(__file__).resolve().parent))  # this folder, for flow_report

from rich.console import Console  # noqa: E402

from app.core.credentials import CredentialStore  # noqa: E402
from app.core.features import fold  # noqa: E402
from app.core.interaction import make_response  # noqa: E402
from app.pipeline.explore_cli import ConsoleReporter  # noqa: E402
from app.pipeline.frontend import ScriptedFrontend  # noqa: E402
from app.pipeline.runner import JobConfig, run_job  # noqa: E402
from app.schemas.generated.interaction import InteractionRequest  # noqa: E402
from app.schemas.generated.user_response import UserResponse  # noqa: E402

OUT = Path(__file__).resolve().parents[3] / "docs" / "core-flow"


@dataclass
class Site:
    url: str
    description: str  # what the user would write in "describe the flow you want"
    keywords: list[str] = field(default_factory=list)  # a proposed flow with these is picked
    describe_only: bool = False  # always describe (do not look at the proposals)
    requires_login: bool = False
    credentials: tuple[str, str] | None = None
    allow_submit: bool = False


SITES = {
    "orangehrm": Site(
        "https://opensource-demo.orangehrmlive.com/",
        "Nhân viên xin nghỉ phép 2 ngày rồi xem trạng thái đơn",
        describe_only=True,
        requires_login=True,
        credentials=("Admin", "admin123"),
    ),
    "todomvc": Site(
        "https://todomvc.com/examples/react/dist/",
        "Lên danh sách việc trong ngày: thêm 3 việc, đánh dấu xong 1 việc rồi lọc việc còn lại "
        "(Active)",
        keywords=["danh sach viec", "viec trong ngay", "todo", "cong viec"],
        allow_submit=True,
    ),
    "squoosh": Site(
        "https://squoosh.app/",
        "Nén một ảnh mẫu rồi so sánh ảnh trước và sau khi nén",
        keywords=["nen anh", "compress", "so sanh"],
    ),
}


def match(flow_text: str, keywords: list[str]) -> bool:
    haystack = fold(flow_text)
    return any(k in haystack for k in keywords)


class FlowUser(ScriptedFrontend):
    def __init__(self, site: Site, job_dir: Path, console: Console) -> None:
        super().__init__({}, console)
        self.site, self.job_dir = site, job_dir
        self.log: list[dict[str, object]] = []
        self.described = False
        self.regenerated = False

    def note(self, event: str, **fields: object) -> None:
        self.log.append({"at": time.strftime("%H:%M:%S"), "event": event, **fields})

    def ask(self, request: InteractionRequest) -> UserResponse:
        if request.kind == "login_required":
            assert self.site.credentials is not None, "this site should not need a sign-in"
            CredentialStore(self.job_dir).save(
                *self.site.credentials
            )  # what /login/credentials does
            self.note("login_required", reason=request.login.reason if request.login else None)
            return make_response(request, "answer", answers={"login_method": "credentials"})
        if request.kind == "select_flow":
            return self.select_flow(request)
        if request.kind == "flow_storyboard_review":
            return self.review(request)
        return super().ask(request)

    def select_flow(self, request: InteractionRequest) -> UserResponse:
        flows = request.flows or []
        titles = [f"{f.id}: {f.title}" for f in flows]
        own = next((f for f in flows if f.source == "user"), None)
        proposed = next(
            (
                f
                for f in flows
                if f.source != "user"
                and match(f"{f.title} {f.goal} {' '.join(f.expected_steps)}", self.site.keywords)
            ),
            None,
        )
        if own is not None:
            chosen = own
        elif proposed is not None and not self.site.describe_only:
            chosen = proposed
        elif not self.described:
            self.described = True
            self.note("describe_flow", text=self.site.description, proposals=titles)
            ids = list(request.flow_select.default) if request.flow_select else []
            return make_response(
                request, "answer",
                answers={"selected_flows": ids, "flow_description": self.site.description},
            )  # fmt: skip
        else:
            chosen = flows[0]
        answers: dict[str, str | list[str]] = {"selected_flows": [chosen.id]}
        blocked = request.flow_select.submit_blocked_reason if request.flow_select else None
        if self.site.allow_submit and chosen.needs_submit and not blocked:
            answers.update(allow_submit="true", submit_confirmed="true")
        self.note(
            "select_flow",
            chosen=chosen.id,
            title=chosen.title,
            needs_submit=chosen.needs_submit,
            allow_submit="allow_submit" in answers,
            blocked=blocked,
            proposals=titles,
        )
        return make_response(request, "answer", answers=answers)

    def review(self, request: InteractionRequest) -> UserResponse:
        run = request.flow_review
        assert run is not None
        self.note(
            "storyboard", status=run.status, steps=len(run.steps), warnings=run.warnings,
            notes=[s.note for s in run.steps],
        )  # fmt: skip
        if run.status in ("partial", "failed") and not self.regenerated:
            self.regenerated = True
            self.note("regenerate")
            return make_response(request, "regenerate")
        action = "approve" if run.status != "failed" and len(run.steps) >= 2 else "cancel"
        self.note(action)
        return make_response(request, action)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    name, job_dir = sys.argv[1], Path(sys.argv[2])
    site = SITES[name]
    code = 0
    if "--report-only" not in sys.argv:
        console = Console()
        user = FlowUser(site, job_dir, console)
        cfg = JobConfig(
            url=site.url, job_dir=job_dir, requires_login=site.requires_login, max_pages=15,
            timeout=900, core_flow=True,
        )  # fmt: skip
        started = time.monotonic()
        result = run_job(cfg, user, ConsoleReporter(console))
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "acceptance_flow.json").write_text(
            json.dumps(
                {"site": name, "exit": result.exit_code, "status": result.status,
                 "seconds": round(time.monotonic() - started, 1), "user": user.log},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )  # fmt: skip
        code = result.exit_code
    try:
        import flow_report

        numbers = flow_report.build(job_dir, OUT, name)
        print(json.dumps(numbers, ensure_ascii=False, indent=2))
    except SystemExit as e:  # no flow run: the job fell back to features or failed early
        print(f"no report: {e}")
    return code


if __name__ == "__main__":
    sys.exit(main())
