"""Acceptance report of a core-flow job: storyboard, numbers, chapter table, contact sheet.

Usage (from services/api):
  uv run python scripts/flow_report.py <job-dir> <out-dir> <name>
Writes <out-dir>/<name>.md, <name>-contact-sheet.png, <name>-flow_run.json and <name>/steps/*.jpg
(docs/core-flow/ for the real runs).
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # services/api, for `app`

from app.recorder import sync  # noqa: E402

SHARED_SITES = ("opensource-demo.orangehrmlive.com",)
SHEET_FRAMES = 16


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def contact_sheet(video: Path, out: Path, duration_ms: int, frames: int = SHEET_FRAMES) -> bool:
    """`frames` frames spread over the video, tiled 8 per row. False when ffmpeg cannot do it."""
    if not video.is_file() or duration_ms <= 0:
        return False
    rate = frames / (duration_ms / 1000)
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(video),
            "-vf", f"fps={rate:.5f},scale=216:-2,tile=8x{frames // 8}",
            "-frames:v", "1", str(out),
        ],
        capture_output=True, text=True,
    )  # fmt: skip
    return result.returncode == 0 and out.is_file()


def first_frame(video: Path, out: Path) -> bool:
    """The very first frame of the final video as a still (to check no sync pulse leaked in)."""
    if not video.is_file():
        return False
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-frames:v", "1", str(out)],
        capture_output=True, text=True,
    )  # fmt: skip
    return result.returncode == 0 and out.is_file()


def usage_rows(job: Path) -> list[tuple[str, int, int, int]]:
    """(step, calls, input tokens, output tokens) from the saved usage files, largest first."""
    steps: dict[str, dict[str, int]] = {}
    for name in ("script_usage.json", "explore/usage.json"):
        data = load(job / name)
        if data:
            for step, v in data.get("steps", {}).items():
                steps.setdefault(step, v)
    rows = [(s, v.get("calls", 0), v.get("input", 0), v.get("output", 0)) for s, v in steps.items()]
    return sorted((r for r in rows if r[1]), key=lambda r: -(r[2] + r[3]))


def chapter_rows(job: Path, run: dict[str, Any]) -> list[dict[str, Any]]:
    script = load(job / "script_approved.json") or {"scenes": []}
    report = load(job / "report.json") or {"scenes": []}
    outcome = {s["id"]: s for s in report.get("scenes", [])}
    by_chapter = {s.get("chapter_id"): s for s in script["scenes"] if s.get("chapter_id")}
    steps = {s["i"]: s for s in run["steps"]}
    rows = []
    for c in run["chapters"]:
        scene = by_chapter.get(c["id"], {})
        done = outcome.get(scene.get("id"), {})
        rows.append(
            {
                "id": c["id"], "title": c["title"], "steps": c["step_ids"],
                "notes": [steps[i]["note"] for i in c["step_ids"] if i in steps and steps[i]["note"]],  # noqa: E501
                "scene": scene.get("id", ""), "seconds": round(done.get("final_ms", 0) / 1000, 1),
                "recording": done.get("recording", ""), "voiceover": scene.get("voiceover", ""),
            }
        )  # fmt: skip
    return rows


def write_counts(job: Path, run: dict[str, Any]) -> dict[str, Any]:
    """Every request that wrote data: by the agent, by the film, and what the guard let through."""
    report = load(job / "report.json") or {}
    film = (report.get("flow") or {}).get("write_requests", [])
    agent = (run.get("report") or {}).get("write_requests", [])
    guard = report.get("request_guard") or {}
    allowed = (guard.get("allowed") or {}) if isinstance(guard, dict) else {}
    return {"agent": agent, "film": film, "guard_allowed": allowed, "total": len(agent) + len(film)}


def build(job: Path, out_dir: Path, name: str) -> dict[str, Any]:
    run_file = job / "flow" / "flow_approved.json"
    run = load(run_file) or load(job / "flow" / "flow_run.json")
    if run is None:
        raise SystemExit(f"no flow run in {job}")
    report = load(job / "report.json") or {}
    flow_info = report.get("flow") or {}
    out_dir.mkdir(parents=True, exist_ok=True)
    shots = out_dir / name / "steps"
    shots.mkdir(parents=True, exist_ok=True)
    for step in run["steps"]:
        src = job / step["screenshot"] if step.get("screenshot") else None
        if src is not None and src.is_file():
            shutil.copyfile(src, shots / src.name)
    (out_dir / f"{name}-flow_run.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    sheet_ok = contact_sheet(
        job / "video.mp4", out_dir / f"{name}-contact-sheet.png", int(report.get("actual_ms") or 0)
    )
    agent = run.get("report") or {}
    writes = write_counts(job, run)
    chapters = chapter_rows(job, run)
    url = str((load(job / "state.json") or {}).get("url", ""))
    shared = any(s in url for s in SHARED_SITES)
    video = job / "video.mp4"
    still_ok = first_frame(video, out_dir / f"{name}-first-frame.png")
    pulse_leak = sync.video_has_pulse(video) if video.is_file() else None
    numbers = {
        "status": run["status"], "steps": len(run["steps"]), "chapters": len(run["chapters"]),
        "agent_llm_calls": agent.get("llm_calls"), "agent_seconds": agent.get("seconds"),
        "agent_model": agent.get("model"), "agent_used_images": agent.get("used_images"),
        "agent_tokens": (agent.get("prompt_tokens") or 0) + (agent.get("completion_tokens") or 0),
        "invented_refs": agent.get("invented_refs"),
        "repeat_warnings": agent.get("repeat_warnings"),
        "replayed": flow_info.get("replayed"),
        "replay_failed_at": flow_info.get("replay_failed_at"),
        "skipped_steps": flow_info.get("skipped_steps", []),
        "write_requests": writes["total"], "video_ms": report.get("actual_ms"),
        "footage_ratio": report.get("footage_ratio"), "shared_demo_site": shared,
        "clip_source": flow_info.get("clip_source"),
        "llm_wait_cut_ms": flow_info.get("llm_wait_cut_ms"),
        "retry_segments_cut": flow_info.get("retry_segments_cut"),
        "rejected_segments_cut": flow_info.get("rejected_segments_cut"),
        "text_calls": agent.get("text_calls"), "vision_calls": agent.get("vision_calls"),
        "escalated_because": agent.get("escalated_because"),
        "pulse_in_final_video": pulse_leak, "first_frame_still": still_ok,
        "writes_ok": (writes["total"] == 0) if shared or run["submit_policy"] == "stop" else True,
    }  # fmt: skip
    lines = [
        f"# Nghiệm thu luồng: {name}",
        "",
        f"- Trạng thái luồng: **{run['status']}** · chính sách gửi: `{run['submit_policy']}`"
        + (f" · dừng ở nút «{run['stop_ref']}»" if run.get("stop_ref") else ""),
        f"- Agent: {numbers['agent_llm_calls']} lần gọi LLM, {numbers['agent_seconds']} s, "
        f"model `{numbers['agent_model']}`, "
        f"{'có nhìn ảnh' if numbers['agent_used_images'] else 'chỉ đọc chữ'}, "
        f"{numbers['agent_tokens']} token; ref bịa bị từ chối: {numbers['invented_refs']}; "
        f"cảnh báo lặp: {numbers['repeat_warnings']}",
        f"- Phát lại khi quay: {numbers['replayed']}/{len(run['steps']) - 1} bước"
        + (f", dừng ở bước {numbers['replay_failed_at']}" if numbers["replay_failed_at"] else "")
        + (f", bỏ qua bước {numbers['skipped_steps']}" if numbers["skipped_steps"] else ""),
        f"- **Request ghi dữ liệu: {writes['total']}** (agent {len(writes['agent'])}, quay "
        f"{len(writes['film'])})" + (" ✔" if numbers["writes_ok"] else " ✘ PHẢI LÀ 0"),
        f"- Video: {numbers['video_ms']} ms, tỉ lệ cảnh quay {numbers['footage_ratio']}",
        f"- Nguồn clip: `{numbers['clip_source']}` · cắt chờ LLM {numbers['llm_wait_cut_ms']} ms · "
        f"cắt {numbers['retry_segments_cut']} đoạn thử lại, "
        f"{numbers['rejected_segments_cut']} đoạn bị từ chối",
        f"- Gọi agent: {numbers['text_calls']} chữ, {numbers['vision_calls']} ảnh "
        f"(lý do thêm ảnh: {numbers['escalated_because']})",
        f"- Xung đồng bộ lọt vào video cuối: **{numbers['pulse_in_final_video']}** "
        f"(phải là False) · still khung đầu: `{name}-first-frame.png`",
        "",
        "## Bảng chương",
        "",
        "| Chương | Bước | Thời lượng | Quay | Lời đọc |",
        "|---|---|---|---|---|",
    ]
    for c in chapters:
        lines.append(
            f"| {c['title']} | {c['steps'][0]}–{c['steps'][-1]} | {c['seconds']} s | "
            f"{c['recording'] or '—'} | {c['voiceover'] or '—'} |"
        )
    lines += ["", "## Storyboard", ""]
    for c in run["chapters"]:
        lines += [f"### {c['title']}", ""]
        for i in c["step_ids"]:
            step = next(s for s in run["steps"] if s["i"] == i)
            image = (
                f"{name}/steps/{Path(step['screenshot']).name}" if step.get("screenshot") else ""
            )
            lines.append(
                f"{i}. {step['note'] or step['action']['do']}"
                + (f"  \n   ![]({image})" if image else "")
            )
        lines.append("")
    if run["warnings"] or flow_info.get("notes"):
        lines += ["## Cảnh báo", ""]
        lines += [f"- {w}" for w in [*run["warnings"], *flow_info.get("notes", [])]]
        lines.append("")
    rows = usage_rows(job)
    if rows:
        lines += [
            "## Lần gọi LLM của cả job",
            "",
            "| Bước | Lần gọi | Token vào | Token ra |",
            "|---|---|---|---|",
        ]
        lines += [f"| {s} | {c} | {i} | {o} |" for s, c, i, o in rows]
        lines.append("")
    if sheet_ok:
        lines += ["## Contact sheet (16 frame)", "", f"![]({name}-contact-sheet.png)", ""]
    lines += [
        "## Số liệu",
        "",
        "```json",
        json.dumps(numbers, ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    (out_dir / f"{name}.md").write_text("\n".join(lines), encoding="utf-8")
    return numbers


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    numbers = build(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
    print(json.dumps(numbers, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
