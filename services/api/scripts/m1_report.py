"""M1 acceptance report of one finished job: what the viewer gets, in numbers.

Usage (from services/api):
  uv run python scripts/m1_report.py <job-dir> <old-job-dir> <out-dir> <name>
Writes <out-dir>/<name>.md, <name>-contact-sheet.png (16 frames) and <name>-hook.png (still of the
hook). <old-job-dir> is the R4 job of the same flow, for the before/after of the voice-over.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # services/api, for `app`
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow_report  # noqa: E402

from app.script.proof import numbers_in  # noqa: E402


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def still(video: Path, out: Path, at_s: float) -> bool:
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{at_s:.2f}", "-i", str(video), "-frames:v", "1", str(out)],
        capture_output=True,
    )  # fmt: skip
    return result.returncode == 0 and out.is_file()


def cell(text: object) -> str:
    return str(text if text is not None else "—").replace("|", "\\|").replace("\n", " ")


def scores_row(view: dict[str, Any] | None) -> str:
    if not view:
        return "—"
    return ", ".join(f"{k}={v['score']}" for k, v in view["scores"].items())


def numbers_with_sources(
    script: dict[str, Any], report: dict[str, Any], ctx: dict[str, Any]
) -> list[str]:
    """Every number the video says or shows, and where it comes from."""
    bank = (report.get("proof_bank") or {}).get("numbers", [])
    by_value = {n["value"]: n for n in bank}
    given: dict[str, str] = {}
    flow_texts = [ctx.get(k, "") for k in ("title", "goal", "success_signal", "value")]
    for c in ctx.get("chapters", []):
        flow_texts += [c.get("title", ""), c.get("value_line") or "", *c.get("notes", [])]
    for text in flow_texts + [script.get("title", "")]:
        for value, *_ in numbers_in(text or ""):
            given.setdefault(value, "mô tả luồng đã duyệt")
    given[str(script.get("target_duration_s"))] = "thời lượng video"
    given[str(len(ctx.get("chapters", [])))] = "số chương của luồng"
    rows = []
    texts: list[tuple[str, str]] = [("headline", script["headline"])]
    for s in script["scenes"]:
        texts += [
            (f"{s['id']} lời đọc", s["voiceover"]),
            (f"{s['id']} chữ", s.get("on_screen_text") or ""),
        ]
        if s.get("stat"):
            texts.append((f"{s['id']} stat", f"{s['stat']['value']} {s['stat']['label']}"))
    for where, text in texts:
        for value, _unit, a, b in numbers_in(text):
            written = text[a:b]
            if value in by_value:
                src = by_value[value]
                source = f"proof bank — {src['source']}: «{src['context']}»"
            elif value in given:
                source = given[value]
            else:
                source = "KHÔNG CÓ NGUỒN"
            rows.append(f"| {where} | {cell(written)} | {cell(source)} |")
    return rows


def build(job: Path, old: Path, out_dir: Path, name: str) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    script = load(job / "script_approved.json")
    old_script = load(old / "script_approved.json")
    report = load(job / "report.json") or {}
    sreport = load(job / "script_report.json") or {}
    ctx = load(job / "flow_context.json") or {}
    video = job / "video.mp4"
    duration = int(report.get("actual_ms") or 0)
    sheet_ok = flow_report.contact_sheet(video, out_dir / f"{name}-contact-sheet.png", duration)
    hook_ok = still(video, out_dir / f"{name}-hook.png", 1.0)

    lines = [f"# M1 — {name}", ""]
    lines += [f"- Video: `{video.resolve()}`", f"- Job: `{job.resolve()}`"]
    lines += [
        f"- Thời lượng thực: {duration / 1000:.1f}s (mục tiêu {report.get('target_ms', 0) / 1000:.0f}s)"
    ]
    lines += [
        f"- Contact sheet 16 khung: `{name}-contact-sheet.png`"
        + ("" if sheet_ok else " (KHÔNG tạo được)")
    ]
    lines += [f"- Still của hook: `{name}-hook.png`" + ("" if hook_ok else " (KHÔNG tạo được)"), ""]

    lines += [
        "## Lời đọc cũ (R4) và mới (M1) từng cảnh",
        "",
        "| # | Loại | Cũ | Mới |",
        "|---|---|---|---|",
    ]
    olds = (old_script or {}).get("scenes", [])
    for i, s in enumerate(script["scenes"]):
        before = olds[i]["voiceover"] if i < len(olds) else None
        lines.append(f"| {s['id']} | {s['type']} | {cell(before)} | {cell(s['voiceover'])} |")
    lines += [
        "",
        f"Headline cũ: {cell((old_script or {}).get('headline'))}  ",
        f"Headline mới: {cell(script['headline'])}",
        "",
    ]

    lines += ["## Hook", ""]
    opts = script.get("hook_options") or []
    hook = next(s for s in script["scenes"] if s["type"] == "hook")
    for n, o in enumerate(opts, start=1):
        mark = " ← **được chọn**" if o["voiceover"] == hook["voiceover"] else ""
        lines.append(
            f"{n}. `{o['kind']}`: «{o['voiceover']}» (chữ: {cell(o.get('on_screen_text'))}){mark}"
        )
    critic = sreport.get("critic") or {}
    if critic.get("hook"):
        lines.append(f"\nĐiểm hook_strength của 2 phương án: {critic['hook']['hook_strength']}")
    lines += ["", f"Khung kể chuyện: `{script.get('framework')}`", ""]

    lines += ["## Điểm Copy Critic trước / sau", ""]
    if critic.get("before"):
        lines += [f"- Trước: {scores_row(critic['before'])}"]
        lines += [
            f"- Sau viết lại: {scores_row(critic.get('after'))}"
            + (" (giữ bản viết lại)" if critic.get("kept_rewrite") else " (không dùng)")
        ]
        lines += [
            f"- Đã viết lại các cảnh: {critic.get('rewritten') or 'không'}",
            f"- Nhận xét: {cell((critic.get('final') or {}).get('summary'))}",
        ]
        for note in critic.get("notes", []):
            lines.append(f"- Ghi chú: {note}")
    else:
        lines += [f"Không có điểm critic: {cell(critic.get('error'))}"]
    lines += [""]

    lines += ["## Scorecard", "", "| Tiêu chí | Giá trị | Cần | Kết quả |", "|---|---|---|---|"]
    card = report.get("scorecard") or {"lines": []}
    for x in card["lines"]:
        lines.append(
            f"| {cell(x['label'])} | {cell(x['value'])} | {cell(x['target'])} | {x['status']} |"
        )
    if card.get("lines"):
        lines += ["", f"Đạt {card['passed']}/{card['total']} (không đạt: {card['failed']})"]
    lines += [
        "",
        "## Con số trong video và nguồn",
        "",
        "| Ở đâu | Con số | Nguồn |",
        "|---|---|---|",
    ]
    rows = numbers_with_sources(script, sreport, ctx)
    lines += rows or ["| — | (video không dùng con số nào) | — |"]
    lines += ["", "## Số liệu dựng phim", ""]
    for key in (
        "footage_ratio",
        "dead_frames_ms",
        "dead_frames_cut_ms",
        "max_static_shot_s",
        "punch_ins",
        "text_cards",
    ):
        lines.append(f"- {key}: {cell(report.get(key))}")
    flow = report.get("flow") or {}
    lines += [
        f"- hero: {cell(flow.get('hero'))}",
        f"- steps_in_clip: {cell(flow.get('steps_in_clip'))}",
        f"- write_requests: {cell(flow.get('write_requests'))}",
        "",
    ]
    path = out_dir / f"{name}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    job_dir, old_dir, out, label = (
        Path(sys.argv[1]),
        Path(sys.argv[2]),
        Path(sys.argv[3]),
        sys.argv[4],
    )
    print(build(job_dir, old_dir, out, label))
