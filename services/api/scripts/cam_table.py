"""Markdown table of the Motion QA numbers saved by scripts/motion_qa.py.

Usage (from services/api): uv run python scripts/cam_table.py <docs/cam dir> <tag> [<tag> ...]
Prints one table per tag (rows = numbers, columns = sites).
"""

import json
import sys
from pathlib import Path

ROWS = (
    ("max_zoom_rate", "Zoom tối đa mỗi khung", "≤ 2,5%", lambda v: f"{v * 100:.1f}%"),
    ("max_pan_rate", "Kéo khung tối đa mỗi khung", "≤ 1,5%", lambda v: f"{v * 100:.1f}%"),
    ("freeze_then_jump", "Đứng yên rồi giật", "0", str),
    ("flash_shots", "Cảnh chớp (< 0,8 s)", "0", str),
    ("loading_frames_ms", "Ảnh/canvas đang tải (ms)", "0", str),
    ("static_ms_max", "Đứng yên tuyệt đối dài nhất (ms)", "≤ 400", str),
    ("focus_text_clipped", "Khung chữ tiêu điểm bị cắt", "0", str),
    ("focus_match_rate", "Tiêu điểm khớp lời/thao tác", "≥ 85%", lambda v: f"{v * 100:.0f}%"),
)


def table(directory: Path, tag: str) -> str:
    files = sorted(directory.glob(f"*-{tag}.json"))
    data = {f.name.removesuffix(f"-{tag}.json"): json.loads(f.read_text("utf-8")) for f in files}
    names = list(data)
    lines = [f"| Chỉ số | Ngưỡng | {' | '.join(names)} |", f"|---|---|{'---|' * len(names)}"]
    for key, label, limit, show in ROWS:
        cells = []
        for n in names:
            value = data[n]["metrics"].get(key)
            ok = data[n]["verdict"].get(key)
            text = "—" if value is None else show(value)
            cells.append(text if ok in (None, True) else f"**{text}** ✗")
        lines.append(f"| {label} | {limit} | {' | '.join(cells)} |")
    lines.append(
        f"| Đạt cả bộ | | {' | '.join('có' if data[n]['passed'] else 'không' for n in names)} |"
    )
    return "\n".join(lines)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    for tag in sys.argv[2:]:
        print(f"### {tag}\n\n{table(Path(sys.argv[1]), tag)}\n")
