"""Camera preview of a produced job WITHOUT rendering the video (for quick tuning).

Usage (from services/api):
  uv run python scripts/camera_preview.py <render_props.json> <out.png>
The camera path comes from the renderer's own camera code (apps/render/scripts/camera-path.ts),
so what is drawn is what the render will do. The picture holds the zoom and pan speed per frame
(against their limits) and six stills of the scene clips, cropped to the camera view, with the
focus box in red.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # services/api, for `app`

from PIL import Image, ImageDraw  # noqa: E402

from app.producer.motion_qa import MAX_PAN_RATE, MAX_ZOOM_RATE  # noqa: E402

RENDER = Path(__file__).resolve().parents[3] / "apps" / "render"
STILLS = 6
THUMB = (260, 325)
W, PLOT_H = 1560, 330


def camera_path(props_file: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["pnpm", "exec", "tsx", "scripts/camera-path.ts", str(props_file.resolve())],
        cwd=RENDER, capture_output=True, text=True, shell=sys.platform == "win32",
    )  # fmt: skip
    if proc.returncode != 0:
        raise SystemExit(f"camera-path failed: {proc.stderr[-400:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def speeds(path: dict[str, Any]) -> tuple[list[float], list[float]]:
    """Zoom speed and pan speed (shares per frame) over the whole video, scene after scene."""
    zoom: list[float] = []
    pan: list[float] = []
    for scene in path["scenes"]:
        prev = None
        for x, y, w in scene["views"]:
            h = w * path["frame"]["h"] / path["frame"]["w"]
            if prev is None:
                zoom.append(0.0)
                pan.append(0.0)
            else:
                px, py, pw = prev
                zoom.append(abs(pw / w - 1.0))
                cx, cy = x + w / 2, y + h / 2
                pcx, pcy = px + pw / 2, py + pw * path["frame"]["h"] / path["frame"]["w"] / 2
                pan.append(((cx - pcx) ** 2 + (cy - pcy) ** 2) ** 0.5 / w)
            prev = (x, y, w)
    return zoom, pan


def plot(
    d: ImageDraw.ImageDraw, series: list[float], limit: float, top: float, y0: int, label: str
) -> None:
    pad = 40
    n = max(len(series), 1)
    d.rectangle((pad, y0, W - pad, y0 + PLOT_H // 2 - 20), outline="#3a4256")
    d.text((pad + 4, y0 + 2), f"{label}  (limit {limit * 100:.1f}%/frame)", fill="#9aa4b8")
    height = PLOT_H // 2 - 20
    ly = y0 + height - height * min(1.0, limit / top)
    d.line((pad, ly, W - pad, ly), fill="#e8b84a")
    for i, v in enumerate(series):
        x = pad + (W - 2 * pad) * i / n
        bar = height * min(1.0, v / top)
        d.line((x, y0 + height, x, y0 + height - bar), fill="#e5484d" if v > limit else "#4fd1c5")


def still(
    clip: Path,
    t_ms: float,
    view: list[float],
    frame: dict[str, int],
    focus: dict[str, float] | None,
) -> Image.Image:
    out = Path(sys.argv[2]).with_suffix(".tmp.png")
    for seek in (["-ss", f"{t_ms / 1000:.3f}"], ["-sseof", "-0.2"]):  # past the end: the last frame
        out.unlink(missing_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", *seek, "-i", str(clip), "-frames:v", "1", str(out)],
            check=True,
        )
        if out.is_file():
            break
    img = Image.open(out).convert("RGB")
    x, y, w = view
    h = w * frame["h"] / frame["w"]
    crop = img.crop((round(x), round(y), round(x + w), round(y + h))).resize(THUMB)
    if focus:
        k = THUMB[0] / w
        ImageDraw.Draw(crop).rectangle(
            (
                (focus["x"] - x) * k,
                (focus["y"] - y) * k,
                (focus["x"] + focus["w"] - x) * k,
                (focus["y"] + focus["h"] - y) * k,
            ),
            outline="#ff3b3b", width=3,
        )  # fmt: skip
    out.unlink(missing_ok=True)
    return crop


def main() -> None:
    props_file, out_png = Path(sys.argv[1]), Path(sys.argv[2])
    props = json.loads(props_file.read_text(encoding="utf-8"))
    path = camera_path(props_file)
    zoom, pan = speeds(path)
    img = Image.new("RGB", (W, PLOT_H + THUMB[1] + 60), "#101520")
    d = ImageDraw.Draw(img)
    plot(d, zoom, MAX_ZOOM_RATE, 0.20, 10, "zoom speed")
    plot(d, pan, MAX_PAN_RATE, 0.12, 10 + PLOT_H // 2, "pan speed")

    # six stills spread over the recorded scenes (the middle of an equal share of the frames)
    frames = [(s, i) for s in path["scenes"] for i in range(s["frames"])]
    picks = [frames[int((n + 0.5) * len(frames) / STILLS)] for n in range(STILLS)] if frames else []
    for n, (scene, i) in enumerate(picks):
        a = props["assets"][scene["id"]]
        t = scene["start_ms"] + i / path["fps"] * 1000 * scene["rate"]
        track = [e for e in a.get("focus_track", []) if e["t_ms"] <= t]
        focus = track[-1]["bbox"] if track else None
        x = 20 + n * (THUMB[0] + 8)
        img.paste(
            still(Path(scene["clip"]), t, scene["views"][i], path["frame"], focus), (x, PLOT_H + 20)
        )
        d.text((x, PLOT_H + THUMB[1] + 26), f"{scene['id']} {t / 1000:.1f}s", fill="#9aa4b8")
    img.save(out_png)
    print(
        json.dumps(
            {
                "png": str(out_png.resolve()),
                "frames": len(zoom),
                "max_zoom": round(max(zoom, default=0), 4),
                "max_pan": round(max(pan, default=0), 4),
            }
        )
    )


if __name__ == "__main__":
    main()
