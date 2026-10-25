"""Focus table and numbers of a produced job (docs/visual-v3).

Usage (from services/api):
  uv run python scripts/focus_report.py <job-dir> <name> [--review review.json]

Writes docs/visual-v3/<name>-focus.md (table: time | voice-over | actual focus | source | verdict)
and docs/visual-v3/metrics-<name>.json. Verdicts: "auto" = the item's own words are said in the
stretch (fuzzy, accents ignored); a review file {"<row>": "khop"|"khong khop", ...} overrides it
after someone looked at the contact sheet.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # services/api, for `app`
sys.path.insert(0, str(Path(__file__).resolve().parent))

from visual_metrics import metrics as visual_metrics  # noqa: E402

from app.core.textmatch import text_matches  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
RENDER = ROOT / "apps" / "render"
SIDE_REGIONS = {"nav", "aside", "footer"}
SIDE_KINDS = {"sidebar", "nav", "footer"}


def tsx(script: str, props_file: Path) -> dict:  # type: ignore[type-arg]
    out = subprocess.run(
        ["pnpm", "exec", "tsx", f"scripts/{script}", str(props_file.resolve())],
        cwd=RENDER, capture_output=True, text=True, check=True, shell=sys.platform == "win32",
    )  # fmt: skip
    return json.loads(out.stdout.strip().splitlines()[-1])  # type: ignore[no-any-return]


def speech_in(phrases: list[dict], a: float, b: float) -> str:  # type: ignore[type-arg]
    return " ".join(p["text"] for p in phrases if p["from_ms"] < b and p["to_ms"] > a)


def is_side(e: dict) -> bool:  # type: ignore[type-arg]
    return e.get("region") in SIDE_REGIONS or e.get("item_kind") in SIDE_KINDS


def rows_of(job: Path) -> list[dict]:  # type: ignore[type-arg]
    props = json.loads((job / "produce" / "render_props.json").read_text(encoding="utf-8"))
    rows: list[dict] = []  # type: ignore[type-arg]
    start_ms = 0.0
    for scene in props["script"]["scenes"]:
        sid = scene["id"]
        file = job / "produce" / "focus" / f"{sid}.json"
        if file.is_file():
            data = json.loads(file.read_text(encoding="utf-8"))
            rate = props["assets"][sid].get("playback_rate") or 1.0
            lead = data["lead_ms"]
            track = data["track"]
            for i, e in enumerate(track):
                a = e["t_ms"] - lead
                b = (track[i + 1]["t_ms"] - lead) if i + 1 < len(track) else a + e["hold_ms"]
                speech = speech_in(data["phrases"], a, b)
                text = e.get("text") or ""
                typing = e.get("reason") == "đang gõ"
                auto = (
                    "mở đầu"
                    if e["framing"] == "establish"
                    else "khớp"
                    if (text and text_matches(text, speech)) or typing
                    else "cần xem"
                )
                rows.append(
                    {
                        "scene": sid, "type": scene["type"],
                        "from_s": round((start_ms + a / rate) / 1000, 1),
                        "to_s": round((start_ms + b / rate) / 1000, 1),
                        "len_ms": b - a, "speech": speech, "text": text,
                        "item_kind": e.get("item_kind"), "region": e.get("region"),
                        "framing": e["framing"], "source": e["source"],
                        "reason": e.get("reason") or "", "auto": auto,
                    }
                )  # fmt: skip
        start_ms += scene["duration_ms"]
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("name")
    parser.add_argument("--review", type=Path)
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    job: Path = args.job
    review = json.loads(args.review.read_text(encoding="utf-8")) if args.review else {}
    rows = rows_of(job)
    for n, r in enumerate(rows, start=1):
        r["n"] = n
        r["verdict"] = review.get(str(n), r["auto"])

    scored = [r for r in rows if r["framing"] != "establish"]
    total = sum(r["len_ms"] for r in scored) or 1
    side_ms = sum(
        r["len_ms"]
        for r in scored
        if (r["region"] in SIDE_REGIONS or r["item_kind"] in SIDE_KINDS)
        and not text_matches(r["text"], r["speech"])
    )
    match_ms = sum(r["len_ms"] for r in scored if r["verdict"] in ("khớp", "khop"))
    props_file = job / "produce" / "render_props.json"
    out = {
        "focus_rows": len(rows),
        "focus_ms_scored": round(total),
        "side_focus_unmentioned_pct": round(100 * side_ms / total, 1),
        "match_pct": round(100 * match_ms / total, 1),
        "match_pct_is_reviewed": bool(review),
        "sources": {
            s: sum(1 for r in rows if r["source"] == s) for s in ("plan", "rule", "fallback")
        },
        "focus_camera": tsx("focus-metrics.ts", props_file),
        "visual": visual_metrics(job),
        "planner": {
            sid: json.loads(f.read_text(encoding="utf-8"))["summary"]
            for f in sorted((job / "produce" / "focus").glob("*.json"))
            for sid in [f.stem]
        },
    }
    docs = ROOT / "docs" / "visual-v3"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / f"metrics-{args.name}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        f"# {args.name}: tiêu điểm theo lời đọc",
        "",
        "| # | Cảnh | Thời gian | Cụm lời đọc | Tiêu điểm thực tế (text item) | Nguồn | Khớp |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        focus = f"«{r['text'][:50]}»" if r["text"] else "(toàn trang)"
        where = f" {r['item_kind'] or ''}/{r['region'] or ''}".rstrip("/ ") if r["text"] else ""
        lines.append(
            f"| {r['n']} | {r['scene']} | {r['from_s']}–{r['to_s']} s | {r['speech'][:80] or '—'} "
            f"| {focus}{where} · {r['framing']} | {r['source']} | {r['verdict']} |"
        )
    (docs / f"{args.name}-focus.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {k: v for k, v in out.items() if k not in ("visual", "planner")}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
