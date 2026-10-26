"""CLI: understand a website and agree on a video outline (the terminal frontend of run_job).

uv run python -m app.pipeline.explore_cli --url <url> [--storage-state auth.json]
    [--job-dir out/<name>] [--max-pages 15] [--resume] [--answers answers.json --auto]
    [--timeout 300] [--max-tokens 400000]
"""

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from rich.console import Console
from rich.table import Table

from app.pipeline.explore_run import ExploreRunner
from app.pipeline.frontend import ScriptedFrontend, TerminalFrontend
from app.pipeline.runner import (
    EXIT_USAGE,
    FROM_STEPS,
    JobConfig,
    run_job,
)
from app.producer.pipeline import ProduceResult
from app.proposal.understanding import score_dots
from app.schemas.generated.script import Script


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
    p.add_argument(
        "--requires-login", action="store_true",
        help="the main features are behind a sign-in: ask for it right away",
    )  # fmt: skip
    p.add_argument(
        "--film", choices=["auto", "live", "replay"], default="auto",
        help="how a core flow is filmed: during the agent run (live), replayed, or auto",
    )  # fmt: skip
    p.add_argument(
        "--classic", action="store_true",
        help="the old route: pick separate features instead of one core flow",
    )  # fmt: skip
    p.add_argument("--login-url", help="where to sign in (otherwise the login link is searched)")
    p.add_argument(
        "--capture", metavar="WxH", help="recording size, e.g. 1280x800 (default 1440x900)"
    )
    return p.parse_args(argv)


def parse_capture(text: str | None) -> tuple[int, int] | None:
    if not text:
        return None
    match = re.fullmatch(r"(\d{3,4})x(\d{3,4})", text.strip().lower())
    if match is None:
        raise SystemExit(f"--capture must look like 1280x800, got {text!r}")
    return int(match.group(1)), int(match.group(2))


def default_job_dir(url: str) -> Path:
    host = urlparse(url).hostname or "site"
    return Path("out") / re.sub(r"[^\w-]+", "-", host.removeprefix("www."))


class ConsoleReporter:
    """Prints what the pipeline reports (log lines, feature table, scene table) to the terminal."""

    def __init__(self, console: Console) -> None:
        self.console = console

    def say(self, markup: str) -> None:
        self.console.print(markup)

    def features(self, runner: ExploreRunner) -> None:
        profile = runner.state.profile
        if not profile:
            return
        table = Table(title=f"{profile.product_name} ({runner.state.site_type})")
        for col in ("id", "Tính năng", "importance", "demo"):
            table.add_column(col)
        for f in profile.features:
            table.add_row(f.id, f.name, f"{f.importance:.2f}", score_dots(f))
        self.console.print(table)

    def produced(self, script: Script, result: ProduceResult, job_dir: Path) -> None:
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
        self.console.print(table)
        self.console.print(
            f"mục tiêu {report['target_ms'] / 1000:.0f}s · "
            f"ước tính {report['estimated_ms'] / 1000:.1f}s · "
            f"thực tế {report['actual_ms'] / 1000:.1f}s"
        )
        self.console.print(
            f"[green]Video:[/] {result.video.resolve()}\n"
            f"Báo cáo: {(job_dir / 'report.json').resolve()}"
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

    cfg = JobConfig(
        url=args.url,
        job_dir=job_dir,
        storage_state=args.storage_state,
        max_pages=args.max_pages,
        resume=args.resume,
        timeout=args.timeout,
        max_tokens=args.max_tokens,
        allow_mutations=args.allow_mutations,
        scope=args.scope,
        enter_policy=args.enter_policy,
        stop_after=args.stop_after,
        from_step=args.from_step,
        capture=parse_capture(args.capture),
        requires_login=args.requires_login,
        core_flow=not args.classic,
        flow_film=args.film,
        login_url=args.login_url,
    )
    frontend = ScriptedFrontend.from_file(args.answers) if args.auto else TerminalFrontend(console)
    return run_job(cfg, frontend, ConsoleReporter(console)).exit_code


if __name__ == "__main__":
    sys.exit(main())
