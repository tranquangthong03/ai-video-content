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

from app.core.usage import BudgetExceeded, UsageTracker
from app.explorer.mapper import BlockedByChallenge
from app.explorer.report import DeadlineExceeded
from app.llm.client import load_settings
from app.llm.json_call import JsonCaller, OpenAIChat
from app.pipeline.explore_run import ExploreRunner
from app.pipeline.frontend import ScriptedFrontend, TerminalFrontend
from app.pipeline.proposal_run import Cancelled, ProposalRunner
from app.proposal.understanding import score_dots

EXIT_CANCELLED, EXIT_BLOCKED, EXIT_TOKENS, EXIT_TIMEOUT, EXIT_USAGE = 1, 2, 3, 4, 5
STEPS = ("classify", "analyze", "synthesize", "verify", "delta", "concepts", "outline")


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
    for name in STEPS:
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
    if job_dir.exists() and any(job_dir.iterdir()) and not args.resume:
        console.print(
            f"[red]{job_dir} đã có dữ liệu. Dùng --resume để tiếp tục hoặc chọn --job-dir khác.[/]"
        )
        return EXIT_USAGE
    if args.auto and not args.answers:
        console.print("[red]--auto cần --answers answers.json[/]")
        return EXIT_USAGE
    job_dir.mkdir(parents=True, exist_ok=True)

    settings = load_settings()
    usage_file = job_dir / "explore" / "usage.json"
    tracker = (
        UsageTracker.from_dict(json.loads(usage_file.read_text(encoding="utf-8")), args.max_tokens)
        if args.resume and usage_file.is_file()
        else UsageTracker(max_tokens=args.max_tokens)
    )
    caller = JsonCaller(
        OpenAIChat(settings),
        tracker=tracker,
        cache_enabled=settings.cache_enabled,
        cache_dir=settings.cache_dir,
    )
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

    frontend = ScriptedFrontend.from_file(args.answers) if args.auto else TerminalFrontend(console)
    proposal = ProposalRunner(
        job_dir.name, job_dir, caller, frontend, explore_more=runner.explore_more
    )
    assert runner.state.profile is not None
    try:
        profile, notes = proposal.confirm_understanding(runner.state.profile)
        concept, concept_notes = proposal.choose_concept(profile, notes)
        outline = proposal.review_outline(profile, concept, concept_notes)
    except Cancelled as e:
        console.print(f"[yellow]Đã hủy ở bước {e}.[/]")
        runner.save("cancelled")
        return EXIT_CANCELLED
    except BudgetExceeded as e:
        console.print(f"[red]{e}. Trạng thái đã lưu, chạy lại với --resume.[/]")
        runner.save("paused_token_ceiling")
        return EXIT_TOKENS

    runner.save("done")
    summary = write_summary(job_dir, runner, concept.id, started)
    console.print(f"[green]Đã chốt dàn ý v{outline.version}: {outline.title}[/]")
    console.print(f"Dàn ý: {job_dir / 'outline_approved.json'}\nTóm tắt: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
