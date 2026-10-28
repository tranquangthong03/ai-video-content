# ruff: noqa: E501
"""Calibration of the Copy Critic against a person's own scores.

Usage (from services/api):
  uv run python scripts/critic_calibration.py gen       # writes docs/critic-calibration.md
  uv run python scripts/critic_calibration.py compare   # reads the scores filled in, prints the gap

`gen` lays out the three golden scripts (hook, voice-over of every scene, CTA) as a person reads
them, with an empty table per script. The critic's own scores are NOT shown there, so they do not
steer the reader. `compare` takes the filled tables and the critic's final scores kept with the
snapshots (tests/golden/<name>/script_report.json) and prints, per criterion and overall, how far
apart they are (and which way: positive = the critic is more generous). It changes no threshold.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

API = Path(__file__).resolve().parents[1]
ROOT = API.parents[1]
GOLDEN = API / "tests" / "golden"
DOC = ROOT / "docs" / "critic-calibration.md"
NAMES = ("orangehrm", "squoosh", "todomvc")
CRITERIA = (
    ("hook_strength", "12 từ đầu có khiến người xem dừng lướt không?"),
    ("benefit_clarity", "mỗi chương nói rõ họ ĐƯỢC GÌ, không chỉ kể thao tác?"),
    ("proof_usage", "dùng số liệu / câu trích / ưu đãi thật một cách tự nhiên? (để trống nếu không có gì để dùng)"),
    ("cta_strength", "hành động cụ thể + lý do làm ngay + dễ nhớ?"),
    ("flow", "mạch kể liền: nỗi đau → hành trình → kết quả, nhịp ngắn gọn?"),
)  # fmt: skip
TITLES = {
    "orangehrm": "OrangeHRM — thêm nhân viên mới",
    "squoosh": "Squoosh — nén và so sánh ảnh",
    "todomvc": "TodoMVC — lên danh sách việc",
}


def read(name: str, file: str) -> dict[str, Any]:
    return json.loads((GOLDEN / name / file).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def script_text(name: str) -> str:
    script = read(name, "script_approved.json")
    scenes = script["scenes"]
    lines = [f"**Headline:** {script.get('headline', '')}", ""]
    for i, option in enumerate(script.get("hook_options") or [], 1):
        on = (
            f" — chữ trên màn hình: «{option['on_screen_text']}»"
            if option.get("on_screen_text")
            else ""
        )
        lines.append(f"- Phương án hook {i} ({option.get('kind', '')}): {option['voiceover']}{on}")
    lines.append("")
    for n, s in enumerate(scenes, 1):
        label = {"hook": "HOOK", "cta": "CTA"}.get(s["type"], f"Chương {n - 1}")
        lines.append(f"{n}. **{label}** — {s['voiceover']}")
        extra = []
        if s.get("on_screen_text"):
            extra.append(f"chữ trên màn hình: «{s['on_screen_text']}»")
        if s.get("stat"):
            extra.append(f"số nổi: {s['stat']['value']} {s['stat']['label']}")
        if extra:
            lines.append(f"   _({'; '.join(extra)})_")
    return "\n".join(lines)


def gen() -> None:
    out = [
        "# Hiệu chỉnh Copy Critic",
        "",
        "Đọc từng kịch bản dưới đây như một người xem, rồi điền điểm của bạn (0–10, 10 là xuất sắc; "
        "≥ 7 nghĩa là có thể đăng) vào cột «Điểm của bạn». Điểm của critic KHÔNG hiện ở đây. "
        "Điền xong chạy: `cd services/api && uv run python scripts/critic_calibration.py compare`.",
        "",
        "Lượt này chỉ tạo file này; chưa đổi ngưỡng nào của critic.",
    ]
    for name in NAMES:
        out += ["", f"## {TITLES[name]} (`{name}`)", "", script_text(name), ""]
        out += ["| Tiêu chí | Câu hỏi | Điểm của bạn |", "|---|---|---|"]
        out += [f"| {key} | {question} | |" for key, question in CRITERIA]
    DOC.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("đã tạo", DOC)


def filled_scores(text: str) -> dict[str, dict[str, int]]:
    """{snapshot: {criterion: score}} from the tables of the document (blank cells are left out)."""
    result: dict[str, dict[str, int]] = {}
    current = ""
    for line in text.splitlines():
        head = re.match(r"^## .*\(`(\w+)`\)", line)
        if head:
            current = head.group(1)
            result[current] = {}
            continue
        row = re.match(r"^\|\s*(\w+)\s*\|.*\|\s*(\d{1,2}(?:[.,]\d)?)\s*\|\s*$", line)
        if current and row and row.group(1) in dict(CRITERIA):
            result[current][row.group(1)] = float(row.group(2).replace(",", "."))  # type: ignore[assignment]
    return result


def critic_scores(name: str) -> dict[str, float | None]:
    final = (read(name, "script_report.json").get("critic") or {}).get("final") or {}
    return {k: v.get("score") for k, v in (final.get("scores") or {}).items()}


def compare() -> int:
    mine = filled_scores(DOC.read_text(encoding="utf-8"))
    if not any(mine.values()):
        print("Chưa có điểm nào được điền trong", DOC)
        return 1
    gaps: list[float] = []
    print(f"{'kịch bản':<11}{'tiêu chí':<17}{'bạn':>5}{'critic':>8}{'lệch (critic − bạn)':>22}")
    for name in NAMES:
        theirs = critic_scores(name)
        for key, _q in CRITERIA:
            if key not in mine.get(name, {}) or theirs.get(key) is None:
                continue
            gap = float(theirs[key]) - mine[name][key]  # type: ignore[arg-type]
            gaps.append(gap)
            print(f"{name:<11}{key:<17}{mine[name][key]:>5.0f}{theirs[key]:>8}{gap:>+22.1f}")
    if gaps:
        print(
            f"\n{len(gaps)} cặp điểm | lệch tuyệt đối trung bình {sum(abs(g) for g in gaps) / len(gaps):.2f}"
            f" | lệch trung bình {sum(gaps) / len(gaps):+.2f} (dương: critic dễ tính hơn bạn)"
            f" | lệch ≥ 2 điểm: {sum(1 for g in gaps if abs(g) >= 2)}"
        )
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["gen", "compare"])
    args = p.parse_args()
    if args.action == "gen":
        gen()
        return 0
    return compare()


if __name__ == "__main__":
    sys.exit(main())
