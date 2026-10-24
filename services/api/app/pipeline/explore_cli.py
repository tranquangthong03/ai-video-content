"""CLI: understand a website and agree on a video outline.

uv run python -m app.pipeline.explore_cli --url <url> [--storage-state auth.json]
    [--job-dir out/<name>] [--max-pages 15] [--resume] [--answers answers.json --auto]
    [--timeout 300] [--max-tokens 400000]
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from rich.console import Console
from rich.table import Table

from app.browser.session import BrowserSession
from app.core.usage import BudgetExceeded, UsageTracker
from app.explorer.mapper import BlockedByChallenge
from app.explorer.report import DeadlineExceeded
from app.llm.client import load_settings
from app.llm.json_call import JsonCaller, OpenAIChat
from app.pipeline.explore_run import ExploreRunner
from app.pipeline.frontend import ScriptedFrontend, TerminalFrontend
from app.pipeline.proposal_run import Cancelled, ProposalRunner
from app.pipeline.script_run import ScriptRunner
from app.producer.pipeline import produce
from app.producer.render import RenderError, render_props
from app.proposal.understanding import score_dots
from app.schemas.generated.outline import Outline
from app.schemas.generated.product_profile import ProductProfile
from app.schemas.generated.script import Script
from app.script.theme import ThemeResult, derive_theme
from app.script.writer import WriterError

EXIT_CANCELLED, EXIT_BLOCKED, EXIT_TOKENS, EXIT_TIMEOUT, EXIT_USAGE, EXIT_SCRIPT = 1, 2, 3, 4, 5, 6
EXIT_RENDER = 7
STEPS = ("classify", "analyze", "synthesize", "verify", "delta", "concepts", "outline")
SCRIPT_STEPS = ("beat_map", "script", "fit", "scene", "edit_plan")
FROM_STEPS = ("explore", "script", "produce")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Explore a website and agree on a video outline")
    p.add_argument("--url", required=True)
    p.add_argument(
        "--storage-state", type=Path, help="Playwright storage state (logged-in session)"
    )
    p.add_argument("--job-dir", type=Path)
    p.add_argument("--max-pages", type=int, default=15)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--answers", type=Path, help="answers.json for --auto")
    p.add_argument(
        "--auto", action="store_true", help="non-interactive: answers come from --answers"
    )
    p.add_argument("--timeout", type=float, default=300, help="explorer time budget in seconds")
    p.add_argument("--max-tokens", type=int, default=400_000, help="token ceiling for this run")
    p.add_argument(
        "--allow-mutations", action="store_true", help="disable the request guard (not recommended)"
    )
    p.add_argument(
        "--scope", choices=["path", "domain"], default="path",
        help="path: a start URL with a path only crawls links under that path (default)",
    )  # fmt: skip
    p.add_argument(
        "--stop-after", choices=("outline", "script", "produce"), default="produce",
        help="last step to run: outline/script stop before the next step starts",
    )  # fmt: skip
    p.add_argument(
        "--from-step", choices=FROM_STEPS, default="explore",
        help="start at this step, reusing what an earlier run saved in --job-dir",
    )  # fmt: skip
    p.add_argument(
        "--enter-policy", choices=["strict", "relaxed"], default="strict",
        help="when Enter may be pressed after typing (see app/browser/enter_policy.py)",
    )  # fmt: skip
    return p.parse_args(argv)


def default_job_dir(url: str) -> Path:
    host = urlparse(url).hostname or "site"
    return Path("out") / re.sub(r"[^\w-]+", "-", host.removeprefix("www."))


def print_features(console: Console, runner: ExploreRunner) -> None:
    profile = runner.state.profile
    if not profile:
        return
    table = Table(title=f"{profile.product_name} ({runner.state.site_type})")
    for col in ("id", "Tính năng", "importance", "demo"):
        table.add_column(col)
    for f in profile.features:
        table.add_row(f.id, f.name, f"{f.importance:.2f}", score_dots(f))
    console.print(table)


def write_summary(job_dir: Path, runner: ExploreRunner, concept_id: str, started: float) -> Path:
    profile = runner.state.profile
    steps = runner.tracker.steps
    for name in (*STEPS, *SCRIPT_STEPS):
        steps.setdefault(name, {"input": 0, "output": 0, "calls": 0})
    summary = {
        "url": runner.url,
        "site_type": runner.state.site_type,
        "pages_seen": len(runner.state.pages),
        "features": [
            {
                "id": f.id,
                "name": f.name,
                "importance": f.importance,
                "demo_kind": f.demo_kind,
                "demo_score": f.demo_score,
                "verified": f.verified,
                "thumbnail": f.thumbnail,
            }
            for f in (profile.features if profile else [])
        ],
        "concept_id": concept_id,
        "outline": str(job_dir / "outline_approved.json"),
        "tokens": runner.tracker.to_dict(),
        "wall_seconds": round(time.monotonic() - started, 1),
    }
    path = job_dir / "summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def make_caller(args: argparse.Namespace, job_dir: Path) -> tuple[JsonCaller, UsageTracker]:
    settings = load_settings()
    usage_file = job_dir / "explore" / "usage.json"
    resuming = args.resume or args.from_step != "explore"
    tracker = (
        UsageTracker.from_dict(json.loads(usage_file.read_text(encoding="utf-8")), args.max_tokens)
        if resuming and usage_file.is_file()
        else UsageTracker(max_tokens=args.max_tokens)
    )
    caller = JsonCaller(
        OpenAIChat(settings),
        tracker=tracker,
        cache_enabled=settings.cache_enabled,
        cache_dir=settings.cache_dir,
    )
    return caller, tracker


def run_script_step(
    args: argparse.Namespace,
    console: Console,
    job_dir: Path,
    caller: JsonCaller,
    frontend: ScriptedFrontend | TerminalFrontend,
    profile: ProductProfile,
    outline: Outline,
) -> Script:
    """Theme, Script Writer, duration fit and script_review; returns the approved script."""

    def derive() -> ThemeResult:
        console.print("[cyan]\\[theme][/] Lấy màu thương hiệu từ website...")
        with BrowserSession(args.url, storage_state=args.storage_state) as session:
            return derive_theme(
                session, args.url, job_dir, screenshot=job_dir / "explore" / "pages" / "1.png"
            )

    runner = ScriptRunner(
        job_dir.name, job_dir, caller, frontend, profile, outline, args.url, theme_fn=derive
    )
    return runner.run()


def load_saved(job_dir: Path) -> tuple[ProductProfile, Outline]:
    profile_file, outline_file = (
        job_dir / "confirmed_profile.json",
        job_dir / "outline_approved.json",
    )
    missing = [f.name for f in (profile_file, outline_file) if not f.is_file()]
    if missing:
        raise FileNotFoundError(f"thiếu {', '.join(missing)} trong {job_dir}")
    return (
        ProductProfile.model_validate_json(profile_file.read_text(encoding="utf-8")),
        Outline.model_validate_json(outline_file.read_text(encoding="utf-8")),
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    for stream in (
        sys.stdout,
        sys.stderr,
    ):  # Vietnamese/arrows must not crash a redirected Windows console
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    console = Console()
    started = time.monotonic()
    job_dir: Path = args.job_dir or default_job_dir(args.url)
    fresh = args.from_step == "explore" and not args.resume
    if job_dir.exists() and any(job_dir.iterdir()) and fresh:
        console.print(
            f"[red]{job_dir} đã có dữ liệu. Dùng --resume để tiếp tục hoặc chọn --job-dir khác.[/]"
        )
        return EXIT_USAGE
    if args.auto and not args.answers:
        console.print("[red]--auto cần --answers answers.json[/]")
        return EXIT_USAGE
    job_dir.mkdir(parents=True, exist_ok=True)

    caller, tracker = make_caller(args, job_dir)
    frontend = ScriptedFrontend.from_file(args.answers) if args.auto else TerminalFrontend(console)
    runner: ExploreRunner | None = None
    concept_id = ""
    if args.from_step == "explore":
        runner = ExploreRunner(
            args.url,
            job_dir,
            caller,
            tracker,
            storage_state=args.storage_state,
            max_pages=args.max_pages,
            timeout_s=args.timeout,
            allow_mutations=args.allow_mutations,
            scope=args.scope,
            enter_policy=args.enter_policy,
            progress=lambda step, msg: console.print(f"[cyan]\\[{step}][/] {msg}"),
        )
        console.print(f"[bold]Khám phá {args.url}[/]  → {job_dir}")
        try:
            runner.run()
        except BlockedByChallenge as e:
            console.print(f"[red]Website chặn truy cập tự động ({e}). Dừng, không cố vượt qua.[/]")
            return EXIT_BLOCKED
        except BudgetExceeded as e:
            console.print(f"[red]{e}. Trạng thái đã lưu, chạy lại với --resume.[/]")
            return EXIT_TOKENS
        except DeadlineExceeded as e:
            console.print(f"[red]{e}. Trạng thái đã lưu, chạy lại với --resume.[/]")
            return EXIT_TIMEOUT
        print_features(console, runner)

        proposal = ProposalRunner(
            job_dir.name, job_dir, caller, frontend, explore_more=runner.explore_more
        )
        assert runner.state.profile is not None
        try:
            profile, notes = proposal.confirm_understanding(runner.state.profile)
            concept, concept_notes = proposal.choose_concept(profile, notes)
            outline = proposal.review_outline(profile, concept, concept_notes)
            concept_id = concept.id
        except Cancelled as e:
            console.print(f"[yellow]Đã hủy ở bước {e}.[/]")
            runner.save("cancelled")
            return EXIT_CANCELLED
        except BudgetExceeded as e:
            console.print(f"[red]{e}. Trạng thái đã lưu, chạy lại với --resume.[/]")
            runner.save("paused_token_ceiling")
            return EXIT_TOKENS
        runner.save("done")
        summary = write_summary(job_dir, runner, concept_id, started)
        console.print(f"[green]Đã chốt dàn ý v{outline.version}: {outline.title}[/]")
        console.print(f"Dàn ý: {job_dir / 'outline_approved.json'}\nTóm tắt: {summary}")
        if args.stop_after == "outline":
            return 0
    else:
        try:
            profile, outline = load_saved(job_dir)
        except FileNotFoundError as e:
            console.print(f"[red]{e}. Chạy bước explore trước.[/]")
            return EXIT_USAGE

    approved_file = job_dir / "script_approved.json"
    if args.from_step == "produce":
        if not approved_file.is_file():
            console.print(f"[red]Chưa có {approved_file.name}. Chạy bước script trước.[/]")
            return EXIT_USAGE
        script = Script.model_validate_json(approved_file.read_text(encoding="utf-8"))
    else:
        try:
            script = run_script_step(args, console, job_dir, caller, frontend, profile, outline)
        except Cancelled as e:
            console.print(f"[yellow]Đã hủy ở bước {e}.[/]")
            return EXIT_CANCELLED
        except BudgetExceeded as e:
            console.print(f"[red]{e}. Trạng thái đã lưu, chạy lại với --from-step script.[/]")
            return EXIT_TOKENS
        except WriterError as e:
            console.print(f"[red]Không viết được kịch bản hợp lệ: {e}[/]")
            return EXIT_SCRIPT
        (job_dir / "script_usage.json").write_text(
            json.dumps(tracker.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        console.print(f"[green]Đã duyệt kịch bản: {approved_file}[/]")
        console.print(f"Báo cáo kịch bản: {job_dir / 'script_report.json'}  ({script.headline})")
        if args.stop_after == "script":
            return 0

    return run_produce_step(args, console, job_dir, tracker, profile, script)


def run_produce_step(
    args: argparse.Namespace,
    console: Console,
    job_dir: Path,
    tracker: UsageTracker,
    profile: ProductProfile,
    script: Script,
) -> int:
    """Record every scene, fit the timeline, render the mp4 and write report.json."""
    script_report: dict = {}  # type: ignore[type-arg]
    report_file = job_dir / "script_report.json"
    if report_file.is_file():
        script_report = json.loads(report_file.read_text(encoding="utf-8"))
    extra = {
        "url": args.url,
        "headline": script.headline,
        "theme": script_report.get("theme"),
        "fit": script_report.get("fit"),
        "fit_generation": script_report.get("fit_generation"),
        "script_versions": script_report.get("versions"),
        "script_warnings": script_report.get("warnings", []),
    }
    try:
        with BrowserSession(args.url, storage_state=args.storage_state) as session:
            result = produce(
                script,
                url=args.url,
                job_dir=job_dir,
                session=session,
                render=render_props,
                profile=profile,
                progress=lambda msg: console.print(f"[cyan]{msg}[/]"),
                token_usage=tracker.to_dict(),
                extra_report=extra,
            )
    except RenderError as e:
        console.print(f"[red]{e}[/]")
        return EXIT_RENDER
    report = result.report
    table = Table(title=f"{script.headline}")
    for col in (
        "scene",
        "type",
        "cảnh quay",
        "speech",
        "usable",
        "final",
        "rate",
        "freeze",
        "idle",
    ):
        table.add_column(col)
    for o in result.scenes:
        usable = "—" if o.usable_ms is None else f"{o.usable_ms / 1000:.1f}s"
        idle = "—" if o.idle_max_ms is None else f"{o.idle_max_ms / 1000:.1f}s"
        table.add_row(
            o.id, o.type, o.kind, f"{o.speech_ms / 1000:.1f}s", usable,
            f"{o.final_ms / 1000:.1f}s", f"{o.playback_rate:g}", "có" if o.freeze else "", idle,
        )  # fmt: skip
    console.print(table)
    console.print(
        f"mục tiêu {report['target_ms'] / 1000:.0f}s · "
        f"ước tính {report['estimated_ms'] / 1000:.1f}s · thực tế {report['actual_ms'] / 1000:.1f}s"
    )
    console.print(
        f"[green]Video:[/] {result.video.resolve()}\nBáo cáo: {(job_dir / 'report.json').resolve()}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
