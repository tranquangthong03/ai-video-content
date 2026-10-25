"""Benchmark of the Flow Agent with DeepSeek only (docs/core-flow/llm-benchmark.md).

The agent runs without filming. Three flows, two configurations, `--reps` runs each, LLM cache off:
  text    DeepSeek text only (LLM_FLOW_AGENT_MODEL = deepseek-chat, no screenshots)
  vision  DeepSeek with the viewport screenshot (DEEPSEEK_VISION_MODEL, deepseek-flash)
Flows: fixture (a leave form with a drawn dropdown, a calendar and validation, local site),
orangehrm (apply for 2 days of leave; stop before Apply; the shared demo site, nothing is written),
todomvc (a task list: add 3, tick 1, filter Active; submit allowed, data stays in the browser).

Usage (from services/api):
  uv run python scripts/bench_flow_agent.py run <fixture|orangehrm|todomvc> [--reps 3]
  uv run python scripts/bench_flow_agent.py report
Results go to out/bench/<flow>.json; the report to docs/core-flow/llm-benchmark.md.
"""

import argparse
import functools
import http.server
import json
import re
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # services/api, for `app`

from app.browser.session import BrowserSession  # noqa: E402
from app.core.usage import UsageTracker  # noqa: E402
from app.flows.agent import FlowAgent  # noqa: E402
from app.llm.client import load_settings  # noqa: E402
from app.llm.router import get_client  # noqa: E402
from app.schemas.generated.core_flow import CoreFlow  # noqa: E402
from app.schemas.generated.flow_run import FlowRun  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out" / "bench"
DOCS = ROOT.parents[1] / "docs" / "core-flow"
SITE_DIR = ROOT / "tests" / "fixtures" / "site"
CONFIGS = {
    "text": {"LLM_FLOW_AGENT_MODEL": "deepseek-chat", "LLM_FLOW_AGENT_VISION": "false"},
    "vision": {"LLM_FLOW_AGENT_VISION": "true"},
}
ORANGE = "https://opensource-demo.orangehrmlive.com/web/index.php/dashboard/index"


@dataclass
class Target:
    flow: dict[str, Any]
    policy: str
    login: tuple[str, str] | None = None


def flow_dict(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"source": "proposed", "confidence": 0.8, "related_feature_ids": []}
    return {**base, **kw}


def targets(site: str) -> dict[str, Target]:
    return {
        "fixture": Target(
            flow_dict(
                id="fixture",
                title="Xin nghỉ phép",
                persona="Nhân viên",
                goal="Xin nghỉ 2 ngày",
                start_url=site + "/flow_home.html",
                needs_submit=True,
                expected_steps=[
                    "Mở mục Leave",
                    "Chọn loại nghỉ",
                    "Chọn lý do",
                    "Chọn ngày bắt đầu",
                    "Chọn ngày kết thúc",
                    "Ghi chú",
                    "Dừng trước nút Apply",
                ],
                success_signal="Form đã điền đủ, sẵn sàng bấm Apply",
                value="Xin nghỉ trong một phút.",
            ),
            "stop",
        ),
        "orangehrm": Target(
            flow_dict(
                id="orangehrm",
                title="Nhân viên xin nghỉ phép 2 ngày",
                persona="Nhân viên",
                goal="Xin nghỉ phép 2 ngày",
                start_url=ORANGE,
                needs_submit=True,
                expected_steps=[
                    "Mở menu Leave",
                    "Chọn Apply",
                    "Chọn loại nghỉ",
                    "Chọn ngày bắt đầu và kết thúc",
                    "Ghi lý do",
                    "Dừng trước nút Apply",
                ],
                success_signal="Form xin nghỉ đã điền đủ, sẵn sàng bấm Apply",
                value="Xin nghỉ không cần giấy tờ.",
            ),
            "stop",
            ("Admin", "admin123"),
        ),
        "todomvc": Target(
            flow_dict(
                id="todomvc",
                title="Lên danh sách việc trong ngày",
                persona="Người đi làm",
                goal="Thêm 3 việc, đánh dấu xong 1 việc rồi lọc việc còn lại (Active)",
                start_url="https://todomvc.com/examples/react/dist/",
                needs_submit=False,
                expected_steps=[
                    "Thêm việc thứ nhất",
                    "Thêm việc thứ hai",
                    "Thêm việc thứ ba",
                    "Đánh dấu xong một việc",
                    "Bấm bộ lọc Active",
                ],
                success_signal="Danh sách chỉ còn các việc chưa xong",
                value="Việc trong ngày gọn gàng.",
            ),
            "allow",
        ),
    }


def reached(name: str, run: FlowRun) -> bool:
    """The goal was really reached, not only claimed: what the final steps must show."""
    dos = [s.action.do for s in run.steps]
    if name == "todomvc":
        # three tasks typed, one ticked (a `check`, or a click on its box), then the Active filter
        last_type = max((i for i, d in enumerate(dos) if d == "type"), default=-1)
        ticked = any(
            s.action.do == "check" or (s.action.do == "click" and s.target_text != "Active")
            for s in run.steps[last_type + 1 :]
        )
        filtered = any(s.target_text == "Active" for s in run.steps)
        return run.status == "reached_goal" and dos.count("type") >= 3 and ticked and filtered
    pointed = run.stop_ref is not None and run.stop_ref.strip().lower().startswith("apply")
    return run.status == "stopped_before_submit" and pointed


def serve_site() -> str:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE_DIR))
    handler.log_message = lambda *a, **k: None  # type: ignore[method-assign]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}"


def sign_in(user: str, password: str, state: Path) -> bool:
    from playwright.sync_api import sync_playwright

    from app.browser.login import perform_login

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context()
        page = context.new_page()
        page.goto(
            "https://opensource-demo.orangehrmlive.com/web/index.php/auth/login",
            wait_until="domcontentloaded",
        )
        ok = perform_login(page, user, password).ok
        context.storage_state(path=str(state))
        browser.close()
    return ok


def one_run(name: str, target: Target, config: str, rep: int, state: Path | None) -> dict[str, Any]:
    job = OUT / name / f"{config}-{rep}"
    job.mkdir(parents=True, exist_ok=True)
    settings = load_settings({"LLM_CACHE": "0"})
    caller = get_client(
        "flow_agent", settings=settings, env=CONFIGS[config], tracker=UsageTracker()
    )
    flow = CoreFlow.model_validate(target.flow)
    started = time.monotonic()
    error = None
    with BrowserSession(
        flow.start_url, storage_state=state, expect_session=state is not None
    ) as session:
        agent = FlowAgent(
            session, caller, flow, job, submit_policy=target.policy,
            authenticated=state is not None, use_cache=False,
            viewport={"width": 1440, "height": 900},
        )  # fmt: skip
        try:
            run = agent.run()
        except Exception as e:  # a crash is a result too
            error = f"{type(e).__name__}: {e}"[:300]
            run = None
    seconds = round(time.monotonic() - started, 1)
    if run is None:
        return {"flow": name, "config": config, "rep": rep, "success": False, "status": "crashed",
                "error": error, "seconds": seconds}  # fmt: skip
    r = run.report
    return {
        "flow": name, "config": config, "rep": rep, "success": reached(name, run),
        "status": run.status, "stop_ref": run.stop_ref,
        "actions": len([s for s in run.steps if s.action.do != "goto"]),
        "repeat_warnings": r.repeat_warnings if r else 0, "invented_refs": r.invented_refs if r else 0,
        "llm_calls": r.llm_calls if r else run.llm_calls, "seconds": seconds,
        "tokens": ((r.prompt_tokens + r.completion_tokens) if r else 0),
        "model": r.model if r else None, "used_images": r.used_images if r else False,
        "warnings": run.warnings, "notes": [s.note for s in run.steps],
    }  # fmt: skip


def run_target(name: str, reps: int) -> None:
    site = serve_site()
    target = targets(site)[name]
    state: Path | None = None
    if target.login:
        state = OUT / name / "storage_state.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        if not sign_in(*target.login, state):
            raise SystemExit("sign-in failed")
    results: list[dict[str, Any]] = []
    file = OUT / f"{name}.json"
    for rep in range(1, reps + 1):
        for config in CONFIGS:  # alternate, so a slow hour hits both the same
            result = one_run(name, target, config, rep, state)
            results.append(result)
            file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            print(name, config, rep, result["status"], "OK" if result["success"] else "no",
                  result.get("seconds"), flush=True)  # fmt: skip
    if state is not None:
        state.unlink(missing_ok=True)  # the sign-in is not kept


# --- report ---------------------------------------------------------------------------------------

FAILURE = re.compile(r"^(?P<do>[a-z_]+) «(?P<name>[^»]*)»: (?P<why>.*)$")


def mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 1) if values else 0.0


def stuck_steps(rows: list[dict[str, Any]]) -> list[tuple[str, int, str]]:
    """(step, how many runs, a typical cause) for the failure lines agents produced most."""
    seen: dict[str, set[str]] = {}
    cause: dict[str, str] = {}
    for r in rows:
        for w in r.get("warnings", []):
            m = FAILURE.match(w)
            key = f"{m['do']} «{m['name']}»" if m else re.sub(r"\d+", "N", w)[:70]
            seen.setdefault(key, set()).add(f"{r['flow']}/{r['config']}/{r['rep']}")
            cause.setdefault(key, (m["why"] if m else w)[:140])
    ranked = sorted(seen.items(), key=lambda kv: -len(kv[1]))
    return [(k, len(v), cause[k]) for k, v in ranked[:8]]


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in rows if r["success"]]
    return {
        "runs": len(rows), "success": len(ok),
        "actions": mean([r["actions"] for r in rows if "actions" in r]),
        "repeat": sum(r.get("repeat_warnings", 0) for r in rows),
        "invented": sum(r.get("invented_refs", 0) for r in rows),
        "seconds": mean([r["seconds"] for r in rows]),
        "tokens": round(mean([r.get("tokens", 0) for r in rows])),
        "calls": mean([r.get("llm_calls", 0) for r in rows if "llm_calls" in r]),
    }  # fmt: skip


def report(src: Path | None = None, name: str = "llm-benchmark.md") -> None:
    rows: list[dict[str, Any]] = []
    for file in sorted((src or OUT).glob("*.json")):
        rows += json.loads(file.read_text(encoding="utf-8"))
    flows = sorted({r["flow"] for r in rows})
    lines = [
        "# Benchmark Flow Agent (chỉ DeepSeek)",
        "",
        "Agent chạy không quay video; cache LLM tắt; mỗi ô là số lần đạt / số lần chạy. «Đạt» = luồng thật sự tới đích "
        "(`stopped_before_submit` đúng nút Apply, hoặc todomvc: ≥ 3 lần gõ, 1 lần tích, bấm Active), không chỉ agent tự báo.",
        "",
        "| Luồng | Cấu hình | Đạt | Hành động TB | Gọi LLM TB | Cảnh báo lặp | Ref bịa | Giây TB | Token TB |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for flow in [*flows, "tổng"]:
        for config in CONFIGS:
            sel = [
                r for r in rows if r["config"] == config and (flow == "tổng" or r["flow"] == flow)
            ]
            if not sel:
                continue
            s = summary(sel)
            lines.append(
                f"| {flow} | {config} | {s['success']}/{s['runs']} | {s['actions']} | {s['calls']} | "
                f"{s['repeat']} | {s['invented']} | {s['seconds']} | {s['tokens']} |"
            )
    lines += ["", "## Các bước agent hay kẹt nhất", ""]
    for config in CONFIGS:
        stuck = stuck_steps([r for r in rows if r["config"] == config])
        lines += [f"**{config}**", ""]
        lines += [f"- {k} — {n} lần chạy — {why}" for k, n, why in stuck] or ["- (không có)"]
        lines.append("")
    outcomes = Counter((r["flow"], r["config"], r["status"]) for r in rows)
    lines += [
        "## Trạng thái cuối",
        "",
        "| Luồng | Cấu hình | Trạng thái | Số lần |",
        "|---|---|---|---|",
    ]
    lines += [f"| {f} | {c} | {s} | {n} |" for (f, c, s), n in sorted(outcomes.items())]
    notes = (
        DOCS / "llm-benchmark-notes.md"
    )  # the comments, written by hand after reading the numbers
    final = name == "llm-benchmark.md" and notes.is_file()  # the earlier round has no comments
    lines += ["", notes.read_text(encoding="utf-8") if final else "", ""]
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / name).write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["run", "report"])
    p.add_argument("target", nargs="?", choices=["fixture", "orangehrm", "todomvc"])
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--dir", type=Path, help="report: read the results of this folder")
    p.add_argument("--name", default="llm-benchmark.md", help="report: file in docs/core-flow")
    args = p.parse_args()
    if args.command == "report":
        report(args.dir, args.name)
    else:
        run_target(args.target, args.reps)


if __name__ == "__main__":
    main()
