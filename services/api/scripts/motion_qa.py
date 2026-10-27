"""Motion QA of a finished job: numbers, verdicts and a chart of zoom / pan over time.

Usage (from services/api):
  uv run python scripts/motion_qa.py <job-dir> <out-dir> <name> <tag>
  (for example: out/m1-todomvc docs/cam todomvc before)
Writes <out-dir>/<name>-<tag>.json and <out-dir>/<name>-<tag>.png: zoom and pan speed per frame
against their limits (red = over the limit, grey ticks = cuts).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # services/api, for `app`

from PIL import Image, ImageDraw  # noqa: E402

from app.producer.motion_qa import (  # noqa: E402
    MAX_PAN_RATE,
    MAX_ZOOM_RATE,
    FrameMotion,
    run_qa,
    video_motion,
)

W, H, PAD = 1400, 520, 46


def chart(motions: list[FrameMotion], out: Path, title: str) -> None:
    """Two panels: zoom speed (top) and pan speed (bottom), per frame, with the limits drawn."""
    img = Image.new("RGB", (W, H), "#101520")
    d = ImageDraw.Draw(img)
    end = max((m.t_ms for m in motions), default=1) or 1
    d.text((PAD, 8), title, fill="#e6e9f0")
    panels = (
        ("zoom/frame", "zoom_rate", MAX_ZOOM_RATE, 0.20),
        ("pan/frame", "pan_rate", MAX_PAN_RATE, 0.12),
    )
    ph = (H - 3 * PAD) // 2
    for n, (label, attr, limit, top) in enumerate(panels):
        y0 = PAD + n * (ph + PAD)
        d.rectangle((PAD, y0, W - PAD, y0 + ph), outline="#3a4256")
        d.text(
            (PAD + 4, y0 + 2),
            f"{label} (limit {limit * 100:.1f}%, scale to {top * 100:.0f}%)",
            fill="#9aa4b8",
        )
        ly = y0 + ph - ph * min(1.0, limit / top)
        d.line((PAD, ly, W - PAD, ly), fill="#e8b84a")
        for m in motions:
            x = PAD + (W - 2 * PAD) * m.t_ms / end
            if m.cut:
                d.line((x, y0, x, y0 + 8), fill="#7d879c")
                continue
            v = getattr(m, attr)
            bar = ph * min(1.0, v / top)
            d.line((x, y0 + ph, x, y0 + ph - bar), fill="#e5484d" if v > limit else "#4fd1c5")
    for s in range(0, int(end / 1000) + 1, 5):
        x = PAD + (W - 2 * PAD) * s * 1000 / end
        d.text((x - 6, H - PAD + 6), f"{s}s", fill="#9aa4b8")
    img.save(out)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    job, out_dir, name, tag = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    out_dir.mkdir(parents=True, exist_ok=True)
    qa = run_qa(job)
    motions = video_motion(job / "video.mp4")
    report = {
        "video": str((job / "video.mp4").resolve()),
        "passed": qa["passed"],
        "verdict": qa["verdict"],
        "metrics": qa["metrics"],
        "series": [
            {
                "t_ms": m.t_ms,
                "zoom": round(m.zoom_rate, 4),
                "pan": round(m.pan_rate, 4),
                "cut": m.cut,
            }
            for m in motions
        ],
    }
    (out_dir / f"{name}-{tag}.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8"
    )
    chart(motions, out_dir / f"{name}-{tag}.png", f"{name} - {tag}")
    keys = ("max_zoom_rate", "max_pan_rate", "freeze_then_jump", "flash_shots", "loading_frames_ms",
            "static_ms_max", "focus_text_clipped", "focus_match_rate")  # fmt: skip
    print(
        json.dumps(
            {k: qa["metrics"].get(k) for k in keys} | {"passed": qa["passed"]}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
