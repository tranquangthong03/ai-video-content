"""Visual-quality numbers of a produced job (docs/visual-v2).

Usage: uv run python scripts/visual_metrics.py <job-dir>...

Reads report.json and produce/render_props.json of each job dir and prints one JSON object per job:
  camera_cover_share   share of footage time (establishing shot excluded) at cover zoom or above
  duplicate_signatures scenes whose recorded signature repeats an earlier scene
  side_page_scenes     scenes whose visual goes to a side page (login, signup, ...)
  text_on_black_s      seconds of scenes that are only text on a plain background
  hold_avg_ms          mean time kept on the result of an action
  max_action_speedup   highest playback rate among action scenes
  duration_ratio       actual / target
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # services/api, for `app`

from app.core.subpages import is_subpage  # noqa: E402
from app.script.signature import recorded_signature  # noqa: E402

RENDER = Path(__file__).resolve().parents[3] / "apps" / "render"


def camera(props_file: Path) -> dict:  # type: ignore[type-arg]
    out = subprocess.run(
        ["pnpm", "exec", "tsx", "scripts/camera-metrics.ts", str(props_file.resolve())],
        cwd=RENDER, capture_output=True, text=True, check=True, shell=sys.platform == "win32",
    )  # fmt: skip
    return json.loads(out.stdout.strip().splitlines()[-1])  # type: ignore[no-any-return]


def metrics(job: Path) -> dict:  # type: ignore[type-arg]
    report = json.loads((job / "report.json").read_text(encoding="utf-8"))
    props_file = job / "produce" / "render_props.json"
    props = json.loads(props_file.read_text(encoding="utf-8"))
    assets = props["assets"]
    scenes = {s["id"]: s for s in props["script"]["scenes"]}
    cam = camera(props_file)

    seen: dict[str, str] = {}
    duplicates: list[str] = []
    side: list[str] = []
    for sid, scene in scenes.items():
        visual = scene["visual"]
        urls = [a.get("url") for a in visual["actions"] + visual["setup"]] + [visual.get("page")]
        if any(is_subpage(u) for u in urls if u):
            side.append(sid)
        a = assets.get(sid, {})
        sig = recorded_signature(
            visual, a.get("focus_log", []), (a.get("clip_width", 1440), a.get("clip_height", 900))
        )
        if sig is not None:
            if sig in seen:
                duplicates.append(f"{sid}~{seen[sig]}")
            seen.setdefault(sig, sid)

    out_scenes = report["scenes"]
    black = (
        sum(o["final_ms"] for o in out_scenes if o["recording"] == "template") / 1000
    )  # drawn text with nothing behind it
    actions = [o for o in out_scenes if o["kind"] == "thao tác"]
    return {
        "job": job.name,
        "headline": report.get("headline"),
        "target_s": report["target_ms"] / 1000,
        "actual_s": report["actual_ms"] / 1000,
        "duration_ratio": round(report["actual_ms"] / report["target_ms"], 3),
        "scenes": [
            {k: o[k] for k in ("id", "type", "kind", "speech_ms", "final_ms", "playback_rate")}
            | {
                "trimmed_ms": o.get("trimmed_ms"),
                "actions": o.get("actions"),
                "hold_ms": o.get("hold_avg_ms"),
                "idle_max_ms": o["idle_max_ms"],
            }  # fmt: skip
            for o in out_scenes
        ],
        "camera_cover_share": cam["cover_share"],
        "camera_mean_zoom": cam["mean_zoom"],
        "duplicate_signatures": duplicates,
        "side_page_scenes": side,
        "text_on_black_s": round(black, 1),
        "hold_avg_ms": report.get("hold_avg_ms"),
        "max_action_speedup": max((o["playback_rate"] for o in actions), default=1.0),
        "max_speedup_any": report.get("speedup_used"),
        "trimmed_ms": report.get("trimmed_ms"),
        "footage_ratio": report.get("footage_ratio"),
        "idle_ok": report.get("idle_ok"),
        "ffprobe": report.get("ffprobe"),
        "warnings": report.get("warnings", []),
        "dropped_scenes": report.get("dropped_scenes", []),
    }


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        print(json.dumps(metrics(Path(arg)), ensure_ascii=False, indent=2))
