"""run_job: the whole URL -> video pipeline, shared by the terminal CLI and the web API.

explore -> confirm_understanding -> choose_concept -> outline_review -> script -> produce.
Every step reads and writes the job dir as before (caches make a rerun resume where it stopped).
Whoever drives it supplies a Frontend (answers to InteractionRequests) and a Reporter (what to
show); progress is also written to job-dir/state.json so a web UI can poll it.
"""

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from app.browser.auth_detect import LoginRequired
from app.browser.login_find import find_login_url
from app.browser.session import BrowserSession
from app.core.credentials import CredentialStore, cleanup_job_secrets
from app.core.usage import BudgetExceeded, UsageTracker
from app.explorer.mapper import BlockedByChallenge
from app.explorer.report import DeadlineExceeded
from app.llm.client import load_settings
from app.llm.json_call import JsonCaller, OpenAIChat
from app.pipeline.explore_run import ExploreRunner
from app.pipeline.frontend import Frontend
from app.pipeline.proposal_run import Cancelled, ProposalRunner
from app.pipeline.script_run import ScriptRunner
from app.pipeline.state import (
    RECORD_RE,
    JobState,
    latest_png,
    read_state,
    update_state,
    write_state,
)
from app.producer.pipeline import ProduceResult, produce
from app.producer.render import RenderError, render_props
from app.schemas.generated.outline import Outline
from app.schemas.generated.product_profile import ProductProfile
from app.schemas.generated.script import Script
from app.script.theme import ThemeResult, derive_theme
from app.script.writer import WriterError
from app.session.credential_login import make_credential_login
from app.session.gate import EXPIRED, LoginGate, LoginOutcome, SessionCheck
from app.session.keepalive import keepalive_enabled, keepalive_interval, refresh_session

EXIT_OK = 0
EXIT_CANCELLED, EXIT_BLOCKED, EXIT_TOKENS, EXIT_TIMEOUT, EXIT_USAGE, EXIT_SCRIPT = 1, 2, 3, 4, 5, 6
EXIT_RENDER = 7
MAX_SIGN_INS = 3  # sign-ins asked during one step before the job gives up
EXIT_LOGIN = 8  # the site asks for a sign-in (the web UI asks the user; the CLI stops)
STEPS = ("classify", "analyze", "synthesize", "verify", "delta", "concepts", "outline")
SCRIPT_STEPS = ("beat_map", "script", "fit", "scene", "edit_plan")
FROM_STEPS = ("explore", "script", "produce")
# rough progress (%) at the start of each phase of the explorer, for the progress bar
EXPLORE_PCT = {
    "crawl": 4, "classify": 6, "map": 12, "analyze": 28, "synthesize": 36, "verify": 44,
    "stateful": 52,
}  # fmt: skip


@dataclass
class JobConfig:
    url: str
    job_dir: Path
    storage_state: Path | None = None
    max_pages: int = 15
    resume: bool = False
    timeout: float = 300
    max_tokens: int = 400_000
    allow_mutations: bool = False
    scope: Literal["path", "domain"] = "path"
    enter_policy: Literal["strict", "relaxed"] = "strict"
    stop_after: Literal["outline", "script", "produce"] = "produce"
    from_step: Literal["explore", "script", "produce"] = "explore"
    # polled while a step reports progress: True makes the job stop with Cancelled (web: Hủy)
    should_stop: Callable[[], bool] | None = None
    capture: tuple[int, int] | None = None  # recording size (width, height); None = 1440x900
    requires_login: bool = False  # the user says the main features are behind a sign-in
    login_url: str | None = None  # where to sign in, when the user knows
    app_home_url: str | None = None  # the app's main page after the sign-in (not the landing)


@dataclass
class JobResult:
    exit_code: int
    status: Literal["done", "failed", "cancelled"]
    error: str | None = None


class Reporter(Protocol):
    """What a frontend shows besides the questions: log lines, feature and scene tables."""

    def say(self, markup: str) -> None: ...

    def features(self, runner: ExploreRunner) -> None: ...

    def produced(self, script: Script, result: ProduceResult, job_dir: Path) -> None: ...


class QuietReporter:
    def say(self, markup: str) -> None:
        pass

    def features(self, runner: ExploreRunner) -> None:
        pass

    def produced(self, script: Script, result: ProduceResult, job_dir: Path) -> None:
        pass


def make_caller(cfg: JobConfig) -> tuple[JsonCaller, UsageTracker]:
    settings = load_settings()
    usage_file = cfg.job_dir / "explore" / "usage.json"
    resuming = cfg.resume or cfg.from_step != "explore"
    tracker = (
        UsageTracker.from_dict(json.loads(usage_file.read_text(encoding="utf-8")), cfg.max_tokens)
        if resuming and usage_file.is_file()
        else UsageTracker(max_tokens=cfg.max_tokens)
    )
    caller = JsonCaller(
        OpenAIChat(settings),
        tracker=tracker,
        cache_enabled=settings.cache_enabled,
        cache_dir=settings.cache_dir,
    )
    return caller, tracker


def remember_session(
    job_dir: Path, app_home_url: str | None = None, login_url: str | None = None
) -> None:
    """Write the new session into job.json, so a resumed job (web: "Chạy tiếp") keeps using it."""
    spec_file = job_dir / "job.json"
    if not spec_file.is_file():
        return
    spec = json.loads(spec_file.read_text(encoding="utf-8"))
    spec["storage_state"] = "storage_state.json"
    spec["requires_login"] = False
    spec["app_home_url"] = app_home_url or spec.get("app_home_url")
    spec["login_url"] = login_url or spec.get("login_url")
    spec_file.write_text(json.dumps(spec), encoding="utf-8")


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


class Progress:
    """Writes job-dir/state.json as the pipeline moves (a no-op for ranges nobody registered)."""

    def __init__(self, cfg: JobConfig) -> None:
        self.dir = cfg.job_dir
        self.should_stop = cfg.should_stop
        if read_state(self.dir) is None:
            write_state(self.dir, JobState(job_id=self.dir.name, url=cfg.url))
        self.last_png: str | None = None

    def check_stop(self) -> None:
        if self.should_stop is not None and self.should_stop():
            raise Cancelled("hủy bởi người dùng")

    def set(self, step: str, text: str, pct: int | None = None, **extra: object) -> None:
        self.check_stop()
        changes: dict[str, object] = {"step": step, "progress_text": text, **extra}
        if pct is not None:
            changes["progress_pct"] = pct
        update_state(self.dir, **changes)

    def screenshot(self, folder: Path) -> None:
        png = latest_png(folder)
        if png is not None:
            rel = png.relative_to(self.dir).as_posix()
            if rel != self.last_png:
                self.last_png = rel
                update_state(self.dir, latest_screenshot=rel)

    def explore(self, step: str, msg: str) -> None:
        text = msg
        if step == "map":
            seen = re.match(r"Đã xem (\d+)/(\d+)", msg)
            if seen:
                text = f"Đang phân tích trang {seen.group(1)}/{seen.group(2)}"
        self.set("explore", text, EXPLORE_PCT.get(step))
        self.screenshot(self.dir / "explore" / "pages")

    def produce(self, msg: str) -> None:
        scene = RECORD_RE.search(msg)
        if scene:
            i, n = int(scene.group(1)), int(scene.group(2))
            self.set("produce", f"Đang quay cảnh {i}/{n}", 80 + round(14 * (i - 1) / n))
        elif "render" in msg:
            self.set("produce", "Đang render video", 96)


def _fail(rep: Reporter, code: int, status: Literal["failed", "cancelled"], text: str) -> JobResult:
    rep.say(text)
    return JobResult(code, status, re.sub(r"\[/?[^\]]*\]", "", text))


def run_job(cfg: JobConfig, frontend: Frontend, rep: Reporter | None = None) -> JobResult:
    """Run the pipeline from cfg.from_step to cfg.stop_after. Never raises for expected stops."""
    rep = rep or QuietReporter()
    job_dir = cfg.job_dir
    job_dir.mkdir(parents=True, exist_ok=True)
    progress = Progress(cfg)
    update_state(job_dir, status="running", error=None)
    try:
        result = _run(cfg, frontend, rep, progress)
    except Cancelled:  # raised by a progress callback or a blocked question
        result = JobResult(EXIT_CANCELLED, "cancelled")
    final = {"done": "done", "failed": "failed", "cancelled": "cancelled"}[result.status]
    if final in ("done", "cancelled"):  # a failed job keeps its session: "Chạy tiếp" needs it
        cleanup_job_secrets(job_dir)
    changes: dict[str, object] = {"status": final, "error": result.error}
    if final == "done":
        changes.update(step="done", progress_pct=100, progress_text="Hoàn tất")
    update_state(job_dir, **changes)
    return result


def _run(cfg: JobConfig, frontend: Frontend, rep: Reporter, progress: Progress) -> JobResult:
    started = time.monotonic()
    job_dir = cfg.job_dir
    caller, tracker = make_caller(cfg)
    runner: ExploreRunner | None = None
    concept_id = ""
    store = CredentialStore(job_dir)
    gate = LoginGate(
        job_dir.name,
        job_dir,
        frontend,
        credential_login=make_credential_login(job_dir, cfg.url),
        has_credentials=store.path.is_file,
    )

    def sign_in(need: LoginRequired) -> LoginOutcome:
        """Ask the user to sign in; from then on every step uses the new session."""
        update_state(job_dir, progress_text="Chờ bạn đăng nhập")
        if not need.login_url and cfg.login_url:
            need.login_url = cfg.login_url  # the sign-in page learnt earlier
        outcome = gate.ask(need)
        cfg.storage_state = outcome.storage_state
        if need.reason not in EXPIRED:  # a new sign-in tells where the app starts
            cfg.app_home_url = outcome.url
        cfg.login_url = outcome.login_url or cfg.login_url
        remember_session(job_dir, cfg.app_home_url, cfg.login_url)
        return outcome

    def ensure_session() -> None:
        """Before recording: is the session still good? (the review may have taken a while)"""
        home = cfg.app_home_url or cfg.url
        if cfg.storage_state is None and cfg.app_home_url is None:
            return  # a public site: no session to keep
        check = (
            gate.probe(cfg.storage_state, home)
            if cfg.storage_state is not None and cfg.storage_state.is_file()
            else SessionCheck(False, home)
        )
        gate.record("verify_before_produce", ok=check.ok, opened=home, ended_at=check.url)
        if not check.ok:
            sign_in(LoginRequired(cfg.login_url or "", "session_expired_review", target_url=home))

    if keepalive_enabled() and hasattr(frontend, "keepalive"):
        frontend.keepalive_s = keepalive_interval()  # type: ignore[attr-defined]

        def keep_session_alive() -> None:
            if cfg.storage_state is not None and cfg.storage_state.is_file():
                ok = refresh_session(cfg.storage_state, cfg.app_home_url or cfg.url)
                gate.record("keepalive", ok=ok)

        frontend.keepalive = keep_session_alive  # type: ignore[attr-defined]

    if cfg.from_step == "explore" and cfg.requires_login and cfg.storage_state is None:
        # the user knows the main features are behind a sign-in: find where, ask right away
        login_url = cfg.login_url or find_login_url(cfg.url)
        cfg.url = sign_in(LoginRequired(login_url or "", "requested", target_url=cfg.url)).url
        cfg.scope = (
            "domain"  # the app (e.g. /web/index.php/<module>/...) is wider than its first page
        )
    if cfg.from_step == "explore":
        runner = ExploreRunner(
            cfg.url,
            job_dir,
            caller,
            tracker,
            storage_state=cfg.storage_state,
            max_pages=cfg.max_pages,
            timeout_s=cfg.timeout,
            allow_mutations=cfg.allow_mutations,
            scope=cfg.scope,
            enter_policy=cfg.enter_policy,
            progress=lambda step, msg: (
                rep.say(f"[cyan]\\[{step}][/] {msg}"),
                progress.explore(step, msg),
            )[0],
        )
        rep.say(f"[bold]Khám phá {cfg.url}[/]  → {job_dir}")
        progress.set("explore", "Đang khám phá website", 2)
        try:
            for _ in range(MAX_SIGN_INS + 1):
                try:
                    runner.run()
                    break
                except LoginRequired as e:
                    outcome = sign_in(e)
                    expired = e.reason in EXPIRED
                    cfg.url = cfg.url if expired else outcome.url
                    runner.use_session(outcome.storage_state, cfg.url)
            else:
                raise RuntimeError("quá nhiều lần yêu cầu đăng nhập")
        except LoginRequired as e:
            return _fail(
                rep,
                EXIT_LOGIN,
                "failed",
                f"[red]Trang cần đăng nhập ({e.reason}): {e.login_url}[/]",
            )
        except BlockedByChallenge as e:
            return _fail(
                rep, EXIT_BLOCKED, "failed",
                f"[red]Website chặn truy cập tự động ({e}). Dừng, không cố vượt qua.[/]",
            )  # fmt: skip
        except BudgetExceeded as e:
            return _fail(
                rep,
                EXIT_TOKENS,
                "failed",
                f"[red]{e}. Trạng thái đã lưu, chạy lại với --resume.[/]",
            )
        except DeadlineExceeded as e:
            return _fail(
                rep,
                EXIT_TIMEOUT,
                "failed",
                f"[red]{e}. Trạng thái đã lưu, chạy lại với --resume.[/]",
            )
        rep.features(runner)

        def explore_more(urls: list[str], description: str | None) -> ProductProfile:
            assert runner is not None
            for _ in range(MAX_SIGN_INS):
                try:
                    return runner.explore_more(urls, description)
                except LoginRequired as e:
                    runner.use_session(sign_in(e).storage_state)
            return runner.explore_more(urls, description)

        proposal = ProposalRunner(
            job_dir.name, job_dir, caller, frontend, explore_more=explore_more
        )
        assert runner.state.profile is not None
        try:
            progress.set("confirm", "Xác nhận hiểu biết về sản phẩm", 46)
            profile, notes = proposal.confirm_understanding(runner.state.profile)
            progress.set("select", "Chọn tính năng để review", 47)
            profile, selected = proposal.select_features(profile)
            progress.set("concept", "Chọn hướng video", 48)
            concept, concept_notes = proposal.choose_concept(profile, notes)
            progress.set("outline", "Duyệt dàn ý", 50)
            outline = proposal.review_outline(profile, concept, concept_notes)
            concept_id = concept.id
        except Cancelled as e:
            runner.save("cancelled")
            return _fail(rep, EXIT_CANCELLED, "cancelled", f"[yellow]Đã hủy ở bước {e}.[/]")
        except BudgetExceeded as e:
            runner.save("paused_token_ceiling")
            return _fail(
                rep,
                EXIT_TOKENS,
                "failed",
                f"[red]{e}. Trạng thái đã lưu, chạy lại với --resume.[/]",
            )
        runner.save("done")
        summary = write_summary(job_dir, runner, concept_id, started)
        rep.say(f"[green]Đã chốt dàn ý v{outline.version}: {outline.title}[/]")
        rep.say(f"Dàn ý: {job_dir / 'outline_approved.json'}\nTóm tắt: {summary}")
        if cfg.stop_after == "outline":
            return JobResult(EXIT_OK, "done")
    else:
        try:
            profile, outline = load_saved(job_dir)
        except FileNotFoundError as e:
            return _fail(rep, EXIT_USAGE, "failed", f"[red]{e}. Chạy bước explore trước.[/]")

    approved_file = job_dir / "script_approved.json"
    if cfg.from_step == "produce":
        if not approved_file.is_file():
            return _fail(
                rep, EXIT_USAGE, "failed",
                f"[red]Chưa có {approved_file.name}. Chạy bước script trước.[/]",
            )  # fmt: skip
        script = Script.model_validate_json(approved_file.read_text(encoding="utf-8"))
    else:
        progress.set("script", "Đang viết kịch bản", 56)
        try:
            script = run_script_step(cfg, rep, caller, frontend, profile, outline)
        except Cancelled as e:
            return _fail(rep, EXIT_CANCELLED, "cancelled", f"[yellow]Đã hủy ở bước {e}.[/]")
        except BudgetExceeded as e:
            return _fail(
                rep, EXIT_TOKENS, "failed",
                f"[red]{e}. Trạng thái đã lưu, chạy lại với --from-step script.[/]",
            )  # fmt: skip
        except WriterError as e:
            return _fail(
                rep, EXIT_SCRIPT, "failed", f"[red]Không viết được kịch bản hợp lệ: {e}[/]"
            )
        (job_dir / "script_usage.json").write_text(
            json.dumps(tracker.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        rep.say(f"[green]Đã duyệt kịch bản: {approved_file}[/]")
        rep.say(f"Báo cáo kịch bản: {job_dir / 'script_report.json'}  ({script.headline})")
        if cfg.stop_after == "script":
            return JobResult(EXIT_OK, "done")

    return run_produce_step(
        cfg, rep, progress, tracker, profile, script, caller,
        lambda e: sign_in(e).storage_state, ensure_session,
    )  # fmt: skip


def run_script_step(
    cfg: JobConfig,
    rep: Reporter,
    caller: JsonCaller,
    frontend: Frontend,
    profile: ProductProfile,
    outline: Outline,
) -> Script:
    """Theme, Script Writer, duration fit and script_review; returns the approved script."""

    def derive() -> ThemeResult:
        rep.say("[cyan]\\[theme][/] Lấy màu thương hiệu từ website...")
        with BrowserSession(cfg.url, storage_state=cfg.storage_state) as session:
            return derive_theme(
                session,
                cfg.url,
                cfg.job_dir,
                screenshot=cfg.job_dir / "explore" / "pages" / "1.png",
            )

    runner = ScriptRunner(
        cfg.job_dir.name,
        cfg.job_dir,
        caller,
        frontend,
        profile,
        outline,
        cfg.url,
        theme_fn=derive,
        capture=cfg.capture,
    )
    return runner.run()


def run_produce_step(
    cfg: JobConfig,
    rep: Reporter,
    progress: Progress,
    tracker: UsageTracker,
    profile: ProductProfile,
    script: Script,
    caller: JsonCaller | None = None,
    on_login: Callable[[LoginRequired], Path] | None = None,
    ensure_session: Callable[[], None] | None = None,
) -> JobResult:
    """Record every scene, fit the timeline, render the mp4 and write report.json."""
    job_dir = cfg.job_dir
    script_report: dict = {}  # type: ignore[type-arg]
    report_file = job_dir / "script_report.json"
    if report_file.is_file():
        script_report = json.loads(report_file.read_text(encoding="utf-8"))
    extra = {
        "url": cfg.url,
        "headline": script.headline,
        "theme": script_report.get("theme"),
        "fit": script_report.get("fit"),
        "fit_generation": script_report.get("fit_generation"),
        "script_versions": script_report.get("versions"),
        "script_warnings": script_report.get("warnings", []),
        "content_budget_s": script_report.get("content_budget_s"),
        "content_budget_formula": script_report.get("content_budget_formula"),
        "recommended_duration_s": script_report.get("recommended_duration_s"),
        "footage_ratio_estimated": script_report.get("footage_ratio"),
    }
    login_report = job_dir / "login_report.json"
    if login_report.is_file():  # which hosts the sign-in posted to (no bodies, no secrets)
        extra["login_phase"] = json.loads(login_report.read_text(encoding="utf-8"))
    for w in script_report.get("warnings", []):
        rep.say(f"[yellow]Lưu ý trước khi quay: {w}[/]")
    progress.set("produce", "Chuẩn bị quay", 80)

    def say(msg: str) -> None:
        rep.say(f"[cyan]{msg}[/]")
        progress.produce(msg)

    if ensure_session is not None:
        ensure_session()  # may ask for a new sign-in: the browser below then uses the new session
    try:
        with BrowserSession(
            cfg.url,
            storage_state=cfg.storage_state,
            expect_session=cfg.app_home_url is not None,
        ) as session:
            result = produce(
                script,
                url=cfg.url,
                job_dir=job_dir,
                session=session,
                render=render_props,
                profile=profile,
                progress=say,
                token_usage=tracker.to_dict(),
                extra_report=extra,
                focus_caller=caller,
                on_login=on_login,
            )
    except LoginRequired as e:
        where = f" (scene {e.scene_id})" if e.scene_id else ""
        return _fail(
            rep,
            EXIT_LOGIN,
            "failed",
            "[red]Không quay được các tính năng sau đăng nhập: phiên đăng nhập không còn hiệu lực"
            f"{where}. Video không được xuất. Hãy thử «Mở cửa sổ đăng nhập» hoặc dùng file "
            "phiên đăng nhập mới (auth.json), rồi bấm «Chạy tiếp».[/]",
        )
    except RenderError as e:
        return _fail(rep, EXIT_RENDER, "failed", f"[red]{e}[/]")
    rep.produced(script, result, job_dir)
    return JobResult(EXIT_OK, "done")
