# ruff: noqa: E501
"""Tiered regression on the golden snapshots (tests/golden/{orangehrm,squoosh,todomvc}).

Usage (from services/api):
  uv run python scripts/regress.py --tier t0 [--paths app/producer/x.py apps/render/...]
  uv run python scripts/regress.py --tier t1 [--save] [--names todomvc]
  uv run python scripts/regress.py --tier t2 [--brief brief.json] [--names squoosh] [--save]

  t0  tests of the touched area (pytest -m area_*, tsc/vitest, codegen-check) + camera preview of
      the 3 snapshots (graphs and six stills, no render)      -> 0 LLM calls, no browser
  t1  render the 3 videos again from the snapshots (script and clips kept), Motion QA, table
      against docs/regress/last.json                          -> 0 LLM calls, no browser
  t2  rerun ONLY the script step + Copy Critic on the snapshot (the explore / flow / theme data
      is read from the snapshot, the LLM cache is off), critic scores against the last run
      --brief: a marketing brief file (schema marketing_brief); without it the run has no brief

Every tier ends with one line: time, LLM calls, tokens. t0 and t1 forbid LLM calls (they raise).
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from unittest import mock

API = Path(__file__).resolve().parents[1]
ROOT = API.parents[1]
sys.path.insert(0, str(API))  # for `app`

from app.core import brief as bf  # noqa: E402
from scripts import golden  # noqa: E402

WORK = API / "out" / "regress"
LAST = ROOT / "docs" / "regress" / "last.json"
AREA_PREFIX = "services/api/app/"
SENTINEL_CALLER: Any = object()  # "a planner is there": the replayed plans never use it

CRITERIA = ("hook_strength", "benefit_clarity", "proof_usage", "cta_strength", "flow")
# (key, label, threshold text) of the Motion QA numbers shown in the T1 table
QA_ROWS = (
    ("max_zoom_rate", "zoom/khung", "≤ 2,5% (frame 5%)"),
    ("max_pan_rate", "pan/khung", "≤ 1,5% (frame 3,5%)"),
    ("static_ms_max", "đứng yên (ms)", "≤ 400 (frame 2000)"),
    ("focus_text_clipped", "chữ bị cắt", "0"),
    ("focus_match_rate", "tiêu điểm khớp", "≥ 85%"),
    ("camera_moving_ratio", "camera chuyển động", "≤ 25%"),
    ("full_view_ratio", "toàn cảnh", "≥ 50%"),
    ("zoom_events_per_scene", "zoom/cảnh (max)", "≤ 2"),
    ("container_cut_frames", "khối bị cắt (frame)", "0"),
    ("crossfade_during_motion", "crossfade khi chuyển động", "0"),
    ("ghost_frames", "ảnh chồng (frame)", "0"),
    ("freeze_then_jump", "đứng rồi giật", "0"),
    ("flash_shots", "cảnh chớp", "0"),
    ("loading_frames_ms", "ảnh đang tải (ms)", "0"),
)
TEMPLATES = ("desktop_frame", "desktop_focus")
SHORT = {"desktop_frame": "frame", "desktop_focus": "focus"}


class LLMForbidden(RuntimeError):
    pass


@dataclass
class Meter:
    """LLM calls and tokens seen by the process (OpenAIChat.complete is the only way out)."""

    allow: bool
    calls: int = 0
    tokens: int = 0
    blocked: int = 0
    notes: list[str] = field(default_factory=list)


@contextmanager
def llm_meter(allow: bool) -> Iterator[Meter]:
    from app.llm.json_call import OpenAIChat

    meter = Meter(allow)
    real = OpenAIChat.complete

    def complete(self: Any, model: str, messages: list[dict[str, Any]]) -> Any:
        if not allow:
            meter.blocked += 1
            raise LLMForbidden("this tier makes no LLM call")
        meter.calls += 1
        done = real(self, model, messages)
        meter.tokens += done.prompt_tokens + done.completion_tokens
        return done

    with mock.patch.object(OpenAIChat, "complete", complete):
        yield meter


# --- areas --------------------------------------------------------------------------------------


def areas_of(paths: list[str]) -> tuple[list[str], dict[str, bool]]:
    """(python areas touched, which other checks the paths ask for)."""
    areas: list[str] = []
    other = {"ts": False, "schema": False}
    for raw in paths:
        p = raw.replace("\\", "/")
        if AREA_PREFIX in p:
            area = p.split(AREA_PREFIX, 1)[1].split("/", 1)[0]
        elif p.startswith("app/"):
            area = p.split("/")[1]
        else:
            area = ""
        if area and "." not in area and area not in areas:
            areas.append(area)
        other["ts"] |= p.startswith("apps/render") or "apps/render/" in p
        other["schema"] |= "packages/script-schema" in p
    return areas, other


def changed_paths() -> list[str]:
    done = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return [ln[3:].strip().strip('"') for ln in done.stdout.splitlines() if len(ln) > 3]


# --- the workspace of one snapshot -----------------------------------------------------------------


def rebase(obj: Any, old: str, new: str) -> Any:
    """Move every path string that starts with `old` to `new` (render_props holds absolute paths)."""
    if isinstance(obj, str):
        return new + obj[len(old) :] if obj.startswith(old) else obj
    if isinstance(obj, list):
        return [rebase(x, old, new) for x in obj]
    if isinstance(obj, dict):
        return {k: rebase(v, old, new) for k, v in obj.items()}
    return obj


def workspace(name: str, work: Path = WORK, media: bool = True) -> Path:
    """A fresh job dir for a snapshot: golden json + (golden-media), nothing else."""
    ws = work / name
    shutil.rmtree(ws, ignore_errors=True)
    shutil.copytree(golden.GOLDEN / name, ws)
    if media:
        if not golden.restore_media(name):
            raise FileNotFoundError(f"golden-media/{name} missing and out/cam-{name} is gone too")
        shutil.copytree(golden.MEDIA / name, ws, dirs_exist_ok=True)
        props = ws / "produce" / "render_props.json"
        old_dir = Path(json.loads((ws / "report.json").read_text(encoding="utf-8"))["video"]).parent
        if props.is_file():
            data = rebase(json.loads(props.read_text(encoding="utf-8")), str(old_dir), str(ws))
            props.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return ws


def load_last() -> dict[str, Any]:
    return json.loads(LAST.read_text(encoding="utf-8")) if LAST.is_file() else {}


def save_last(data: dict[str, Any]) -> None:
    LAST.parent.mkdir(parents=True, exist_ok=True)
    LAST.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


# --- T1: produce again from the snapshot -----------------------------------------------------------


class _Guard:
    write_log: list[Any] = []  # noqa: RUF012

    def report(self) -> dict[str, Any]:
        return {"replay": "snapshot"}


class NullSession:
    """Stands in for the browser: anything but the guard report fails loudly."""

    guard = _Guard()

    def __getattr__(self, name: str) -> Any:
        raise RuntimeError(f"T1 must not use the browser (session.{name})")


def saved_plans(name: str, script: Any) -> list[list[dict[str, Any]] | None]:
    """The focus planner's plans of the snapshot, in scene order (the order plan_focus is called)."""
    plans = []
    for scene in script.scenes:
        file = golden.GOLDEN / name / "produce" / "focus" / f"{scene.root.id}.json"
        if file.is_file():
            plans.append(json.loads(file.read_text(encoding="utf-8")).get("plan"))
    return plans


def replay_produce(
    name: str,
    ws: Path,
    render: Callable[..., Any] | None = None,
    qa: bool = True,
    template: str = "desktop_frame",
) -> dict[str, Any]:
    """producer.produce() on the snapshot: saved script, live clip and focus plans; no LLM, no browser."""
    from app.core.flow_ctx import FlowCtx
    from app.pipeline import runner
    from app.producer import pipeline as prod
    from app.producer.focus_plan import PlanResult
    from app.producer.render import render_props
    from app.proposal.flow_outline import flow_profile
    from app.schemas.generated.script import Script

    profile, _outline = runner.load_saved(ws)
    flow = FlowCtx.load(ws)
    if flow is not None:
        profile = flow_profile(profile, flow)
    script = Script.model_validate_json((ws / "script_approved.json").read_text(encoding="utf-8"))
    script = Script.model_validate({**script.model_dump(), "template": template})
    report = json.loads((ws / "report.json").read_text(encoding="utf-8"))
    script_report = json.loads((ws / "script_report.json").read_text(encoding="utf-8"))
    queue = saved_plans(name, script)
    for stale in [
        *(ws / "produce").glob("*.mp4"),
        *(ws / "produce").glob("*.png"),
        ws / "video.mp4",
    ]:
        stale.unlink(missing_ok=True)

    def replayed(_caller: Any, **_kw: Any) -> PlanResult:
        plan = queue.pop(0) if queue else None
        return PlanResult(plan, [] if plan else ["replay: no saved plan"], 1)

    patches = [mock.patch.object(prod, "plan_focus", replayed)]
    if not qa:
        patches.append(mock.patch.object(prod, "measure_motion", lambda *_a, **_k: None))
    for p in patches:
        p.start()
    try:
        result = prod.produce(
            script,
            url=report["url"],
            job_dir=ws,
            session=NullSession(),  # type: ignore[arg-type]
            render=render or render_props,
            profile=profile,
            extra_report=runner.produce_extras(report["url"], script, script_report),
            focus_caller=SENTINEL_CALLER,
        )
    finally:
        for p in reversed(patches):
            p.stop()
    return result.report


def qa_numbers(report: dict[str, Any]) -> dict[str, Any]:
    qa = report.get("motion_qa") or {}
    m = qa.get("metrics", qa)
    out = {k: m.get(k) for k, _l, _t in QA_ROWS}
    out["passed"] = qa.get("passed")
    out["template"] = m.get("template")
    out["footage_ratio"] = report.get("footage_ratio")
    out["video_s"] = round((report.get("actual_ms") or 0) / 1000, 1)
    return out


def fmt(key: str, v: Any) -> str:
    if v is None:
        return "-"
    if key in (
        "max_zoom_rate", "max_pan_rate", "focus_match_rate", "camera_moving_ratio", "full_view_ratio"
    ):  # fmt: skip
        return f"{v * 100:.1f}%"
    return str(v)


def print_table(title: str, cols: list[str], rows: list[list[str]]) -> None:
    widths = [max(len(str(r[i])) for r in [cols, *rows]) for i in range(len(cols))]
    print(f"\n{title}")
    for r in [cols, *rows]:
        print("  " + "  ".join(str(c).ljust(w) for c, w in zip(r, widths, strict=True)))


def stills(ws: Path, out: Path, tag: str) -> list[str]:
    """Two stills of the video: the middle of its first zoom (else of its 40 %) and a full-view moment."""
    import subprocess

    from app.producer.motion_qa import camera_path

    video = ws / "video.mp4"
    try:
        path = camera_path(ws / "produce" / "render_props.json")
    except RuntimeError:
        return []
    zoomed: list[int] = []
    full: list[int] = []
    for scene in path["scenes"]:
        for i, (_x, _y, w) in enumerate(scene["views"]):
            (full if w >= scene["full_w"] * 0.98 else zoomed).append(scene["from"] + i)
    fps = path["fps"]
    total = max((sc["from"] + sc["frames"] for sc in path["scenes"]), default=0)
    pick = [
        zoomed[len(zoomed) // 2] if zoomed else int(total * 0.4),
        full[len(full) // 3] if full else int(total * 0.6),
    ]
    found = []
    for n, frame in enumerate(pick):
        file = out / f"{tag}-still{'AB'[n]}.png"
        done = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{frame / fps:.3f}", "-i", str(video),
             "-frames:v", "1", str(file)],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        if done.returncode == 0 and file.is_file():
            found.append(file.name)
    return found


def run_t1(
    names: list[str],
    *,
    save: bool = False,
    render: Callable[..., Any] | None = None,
    qa: bool = True,
    work: Path = WORK,
    sheets: Path | None = None,
    template: str = "desktop_frame",
    qa_only: bool = False,
) -> tuple[dict[str, Any], Meter, bool]:
    key = f"t1_{SHORT[template]}"
    saved = load_last()
    # the run is compared with the last run of the same template; desktop_frame also with desktop_focus
    last = saved.get(key) or (saved.get("t1", {}) if template == "desktop_focus" else {})
    other = saved.get("t1_focus", {}) if template == "desktop_frame" else {}
    now: dict[str, Any] = {}
    ok = True
    with llm_meter(False) as meter:
        for name in names:
            t = time.monotonic()
            try:
                if qa_only:  # measure the videos of the last run again (no render)
                    from app.producer.motion_qa import run_qa

                    ws = work / name
                    report = {"motion_qa": run_qa(ws)}
                else:
                    ws = workspace(name, work)
                    report = replay_produce(name, ws, render, qa, template)
                now[name] = {**qa_numbers(report), "seconds": round(time.monotonic() - t, 1)}
                if sheets is not None:
                    from scripts import flow_report

                    sheets.mkdir(parents=True, exist_ok=True)
                    flow_report.contact_sheet(
                        ws / "video.mp4", sheets / f"{name}-{SHORT[template]}-sheet.png",
                        int(report.get("actual_ms") or 0), 16,
                    )  # fmt: skip
                    now[name]["stills"] = stills(ws, sheets, f"{name}-{SHORT[template]}")
                now[name]["video"] = str(ws / "video.mp4")
            except Exception as e:  # noqa: BLE001 - a failing snapshot must not hide the others
                ok = False
                now[name] = {"error": f"{type(e).__name__}: {e}"[:300]}
    rows = []
    for qa_key, label, limit in QA_ROWS:
        row = [label, limit]
        for name in names:
            cur, old = now[name].get(qa_key), last.get(name, {}).get(qa_key)
            cell = fmt(qa_key, cur) + ("" if old is None else f" (trước {fmt(qa_key, old)})")
            if other.get(name, {}).get(qa_key) is not None:
                cell += f" [focus {fmt(qa_key, other[name][qa_key])}]"
            row.append(cell)
        rows.append(row)
    rows.append(["Motion QA đạt", "", *[str(now[n].get("passed")) for n in names]])
    print_table(f"T1 ({template}) – Motion QA từ snapshot", ["chỉ số", "ngưỡng", *names], rows)
    for name in names:
        if "error" in now[name]:
            print(f"  LỖI {name}: {now[name]['error']}")
    if save and ok:
        data = load_last()
        data[key] = {
            **data.get(key, {}),
            **{n: {k: v for k, v in d.items() if k != "stills"} for n, d in now.items()},
        }
        save_last(data)
        print(f"\nĐã lưu mốc: {LAST}")
    return now, meter, ok


# --- T2: script + critic -----------------------------------------------------------------------------


def critic_scores(report: dict[str, Any]) -> dict[str, Any]:
    final = (report.get("critic") or {}).get("final") or {}
    return {k: v.get("score") for k, v in (final.get("scores") or {}).items()}


def spoken(scene: dict[str, Any]) -> str:
    """A scene's voice-over, with the on-screen text in brackets."""
    text = scene.get("voiceover") or ""
    return f"{text} [{scene['on_screen_text']}]" if scene.get("on_screen_text") else text


def run_t2(
    names: list[str], brief: Path | None, *, save: bool = False
) -> tuple[dict[str, Any], Meter, bool]:
    from app.core.flow_ctx import FlowCtx
    from app.core.usage import UsageTracker
    from app.llm.client import load_settings
    from app.llm.json_call import JsonCaller, OpenAIChat
    from app.llm.router import get_client
    from app.pipeline import runner
    from app.pipeline.frontend import ScriptedFrontend
    from app.pipeline.script_run import ScriptRunner
    from app.proposal.flow_outline import flow_profile

    last = load_last().get("t2", {})
    now: dict[str, Any] = {}
    ok = True
    with llm_meter(True) as meter:
        for name in names:
            t = time.monotonic()
            try:
                ws = workspace(name, media=False)
                before = critic_scores(json.loads((ws / "script_report.json").read_text("utf-8")))
                for stale in (ws / "script_approved.json", ws / "script_report.json"):
                    stale.unlink()
                shutil.rmtree(ws / "scripts", ignore_errors=True)
                profile, outline = runner.load_saved(ws)
                flow = FlowCtx.load(ws)
                if flow is not None:
                    profile = flow_profile(profile, flow)
                # the brief the run works from: the file's, or none (the old behaviour: skipped)
                given = bf.read_brief_file(brief) if brief else None
                bf.save_brief(ws, bf.clean_brief(given) if given else None)
                url = json.loads((ws / "report.json").read_text("utf-8"))["url"]
                settings = replace(load_settings(), cache_enabled=False)  # the cache is off here
                tracker = UsageTracker(max_tokens=400_000)
                caller = JsonCaller(OpenAIChat(settings), tracker=tracker, cache_enabled=False)

                def no_browser() -> Any:
                    raise RuntimeError(
                        "T2 must not open the browser (theme.json is in the snapshot)"
                    )

                ScriptRunner(
                    name, ws, caller,
                    ScriptedFrontend.from_file(API / "tests" / "fixtures" / "answers" / "auto_default.json"),
                    profile, outline, url,
                    theme_fn=no_browser,
                    flow=flow,
                    critic=get_client("copy_critic", tracker=tracker),
                ).run()  # fmt: skip
                after = critic_scores(json.loads((ws / "script_report.json").read_text("utf-8")))
                made = json.loads((ws / "script_approved.json").read_text("utf-8"))["scenes"]
                now[name] = {
                    "critic": after,
                    "before_snapshot": before,
                    "seconds": round(time.monotonic() - t, 1),
                    "hook": spoken(made[0]),
                    "cta": spoken(made[-1]),
                    "brief": bool(brief),
                }
            except Exception as e:  # noqa: BLE001
                ok = False
                now[name] = {"error": f"{type(e).__name__}: {e}"[:300]}
    rows = []
    for c in CRITERIA:
        row = [c]
        for name in names:
            cur = now[name].get("critic", {}).get(c)
            ref = (last.get(name) or {}).get("critic", {}).get(c)
            if ref is None:
                ref = now[name].get("before_snapshot", {}).get(c)
            row.append(
                f"{cur if cur is not None else '-'} (trước {ref if ref is not None else '-'})"
            )
        rows.append(row)
    print_table("T2 – Điểm Copy Critic", ["tiêu chí", *names], rows)
    for name in names:
        if "error" in now[name]:
            print(f"  LỖI {name}: {now[name]['error']}")
        else:
            print(f"  {name} ({'có brief' if now[name]['brief'] else 'không brief'})")
            print(f"    hook: {now[name]['hook']}")
            print(f"    cta : {now[name]['cta']}")
    if save and ok:
        data = load_last()
        data["t2"] = {**data.get("t2", {}), **{n: {"critic": v["critic"]} for n, v in now.items()}}
        save_last(data)
        print(f"\nĐã lưu mốc: {LAST}")
    return now, meter, ok


# --- T0: tests of the touched area + camera preview ----------------------------------------------------


def camera_previews(names: list[str]) -> list[tuple[str, bool, float]]:
    done = []
    for name in names:
        t = time.monotonic()
        ws = workspace(name)
        out = ws / "preview.png"
        run = subprocess.run(
            [sys.executable, str(API / "scripts" / "camera_preview.py"),
             str(ws / "produce" / "render_props.json"), str(out)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )  # fmt: skip
        done.append((name, run.returncode == 0 and out.is_file(), round(time.monotonic() - t, 1)))
        if run.returncode != 0:
            print(f"  camera_preview {name}: {(run.stderr or run.stdout)[-300:]}")
    return done


def run_cmd(cmd: list[str], cwd: Path) -> tuple[bool, str]:
    done = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    lines = [ln for ln in (done.stdout + done.stderr).splitlines() if ln.strip()]
    failed = [ln for ln in lines if ln.startswith(("FAILED", "ERROR"))][:8]
    summary = next((ln for ln in reversed(lines) if " passed" in ln or " failed" in ln), "")
    return done.returncode == 0, "\n    ".join([summary or (lines[-1] if lines else ""), *failed])


GIT_BASH = ("C:/Program Files/Git/bin/bash.exe", "C:/Program Files/Git/usr/bin/bash.exe")


def git_bash() -> str:
    """Git's bash (on Windows a bare `bash` may be WSL's, which cannot run the script)."""
    found = next((c for c in GIT_BASH if Path(c).is_file()), None)
    return found or shutil.which("bash") or "bash"


def run_t0(names: list[str], paths: list[str]) -> tuple[Meter, bool]:
    areas, other = areas_of(paths or changed_paths())
    ok = True
    rows = []
    with llm_meter(False) as meter:
        if areas:
            expr = " or ".join(f"area_{a}" for a in areas)
            good, text = run_cmd(
                [sys.executable, "-m", "pytest", "-q", "-n", "auto", "-p", "no:cacheprovider",
                 "-m", f"({expr}) and not e2e"],
                API,
            )  # fmt: skip
            rows.append([f"pytest -m {expr}", "ok" if good else "LỖI", text])
            ok &= good
        else:
            rows.append(["pytest", "bỏ qua", "không có đường dẫn Python nào bị sửa"])
        if other["ts"]:
            render = ROOT / "apps" / "render"
            for label, cmd in (("tsc", ["pnpm", "exec", "tsc", "--noEmit"]),
                               ("vitest", ["pnpm", "exec", "vitest", "run"])):  # fmt: skip
                good, text = run_cmd([shutil.which("pnpm") or cmd[0], *cmd[1:]], render)
                rows.append([label, "ok" if good else "LỖI", text])
                ok &= good
        if other["schema"]:
            good, text = run_cmd([git_bash(), "packages/script-schema/codegen.sh", "--check"], ROOT)
            rows.append(["codegen-check", "ok" if good else "LỖI", text])
            ok &= good
        for name, good, secs in camera_previews(names):
            rows.append(
                [
                    f"camera_preview {name}",
                    "ok" if good else "LỖI",
                    f"{secs}s -> out/regress/{name}/preview.png",
                ]
            )
            ok &= good
    print_table("T0", ["bước", "kết quả", "chi tiết"], rows)
    return meter, ok


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--tier", choices=["t0", "t1", "t2"], required=True)
    p.add_argument("--names", nargs="+", choices=golden.NAMES, default=list(golden.NAMES))
    p.add_argument("--paths", nargs="*", default=[], help="touched files (default: git status)")
    p.add_argument("--save", action="store_true", help="write the result to docs/regress/last.json")
    p.add_argument("--brief", type=Path, help="t2: marketing brief JSON (schema marketing_brief)")
    p.add_argument("--sheets", type=Path, help="t1: folder for one contact sheet per video")
    p.add_argument("--template", choices=TEMPLATES, default="desktop_frame", help="t1: template")
    p.add_argument(
        "--qa-only", action="store_true", help="t1: measure the last videos again, no render"
    )
    args = p.parse_args()
    started = time.monotonic()
    if args.tier == "t0":
        meter, ok = run_t0(args.names, args.paths)
    elif args.tier == "t1":
        _now, meter, ok = run_t1(
            args.names,
            save=args.save,
            sheets=args.sheets,
            template=args.template,
            qa_only=args.qa_only,
        )
    else:
        _now, meter, ok = run_t2(args.names, args.brief, save=args.save)
    print(
        f"\nTỔNG {args.tier}: {'đạt' if ok else 'LỖI'} | thời gian {time.monotonic() - started:.0f}s"
        f" | gọi LLM {meter.calls} | token {meter.tokens} | LLM bị chặn {meter.blocked}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
