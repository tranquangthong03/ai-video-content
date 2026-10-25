"""Scene table and numbers of an OrangeHRM acceptance job.

Usage (from services/api): uv run python scripts/orangehrm_report.py <job-dir> <out.md>

Per scene: real clip or a photo, the page the scene was made for, the pages the clip really showed
(the url of every frame_inventory snapshot), whether it sat on the sign-in page, "no_target" notes.
"""

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # services/api, for `app`

from app.browser.auth_detect import is_login_path  # noqa: E402


def path_of(url: str) -> str:
    return urlparse(url).path.rstrip("/") or "/"


def main(job: Path, out: Path) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    script = json.loads((job / "script_approved.json").read_text(encoding="utf-8"))
    report = json.loads((job / "report.json").read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in report["scenes"]}
    warnings = report.get("warnings", [])
    rows = []
    for scene in script["scenes"]:
        sid = scene["id"]
        outcome = by_id.get(sid, {})
        actions = scene["visual"].get("actions", [])
        expected = next(
            (a["url"] for a in reversed(actions) if a.get("url")), scene["visual"].get("page")
        )
        file = job / "produce" / "inventory" / f"{sid}.json"
        seen: list[str] = []
        login_snaps = 0
        total = 0
        if file.is_file():
            snaps = json.loads(file.read_text(encoding="utf-8"))["inventory"]
            total = len(snaps)
            login_snaps = sum(1 for s in snaps if s.get("login_page"))
            for s in snaps:
                if s.get("url") and path_of(s["url"]) not in seen:
                    seen.append(path_of(s["url"]))
        real = outcome.get("recording") == "recording"
        shows_expected = bool(expected) and path_of(expected) in seen
        rows.append(
            {
                "id": sid, "type": scene["type"], "feature": scene.get("feature") or "",
                "recording": outcome.get("recording"), "real_clip": real,
                "expected": path_of(expected) if expected else "", "seen": seen,
                "shows_expected": shows_expected, "login_snaps": f"{login_snaps}/{total}",
                "on_login_page": any(is_login_path(p) for p in seen),
                "no_target": sum(1 for w in warnings if w.startswith("no_target") and sid in w),
                "kinds": [a["do"] for a in actions],
            }
        )  # fmt: skip
    demo = [r for r in rows if r["type"] == "feature_demo"]
    summary = {
        "scenes": len(rows),
        "real_clips": sum(r["real_clip"] for r in rows),
        "no_target_scenes": sum(1 for r in rows if r["no_target"]),
        "scenes_on_login_page": sum(r["on_login_page"] for r in rows),
        "demo_scenes": len(demo),
        "demo_showing_their_page": sum(r["shows_expected"] for r in demo if r["real_clip"]),
        "guard": report.get("request_guard"),
        "login_phase_explore": json.loads(
            (job / "explore" / "report.json").read_text(encoding="utf-8")
        )
        .get("request_guard", {})
        .get("login_phase"),
        "sensitive_skipped": json.loads(
            (job / "explore" / "report.json").read_text(encoding="utf-8")
        ).get("sensitive_skipped"),
        "pages_seen_by_explore": json.loads(
            (job / "explore" / "report.json").read_text(encoding="utf-8")
        ).get("pages_seen"),
    }
    lines = [
        "| Scene | Loại | Feature | Quay | Trang đích | Trang clip thực sự hiển thị "
        "| Đúng trang | Frame login | no_target |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['type']} | {r['feature']} | {r['recording']} | `{r['expected']}` | "
            f"{', '.join('`' + p + '`' for p in r['seen']) or '—'} | "
            f"{'có' if r['shows_expected'] else ('—' if not r['real_clip'] else 'KHÔNG')} | "
            f"{r['login_snaps']} | {r['no_target'] or ''} |"
        )
    out.write_text(
        "\n".join(lines)
        + "\n\n```json\n"
        + json.dumps(summary, ensure_ascii=False, indent=2)
        + "\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
