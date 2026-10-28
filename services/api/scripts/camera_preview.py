# ruff: noqa: E501
"""Camera preview of a produced job WITHOUT rendering the video (for quick tuning).

Usage (from services/api):
  uv run python scripts/camera_preview.py <render_props.json> <out.png>
The camera path comes from the renderer's own camera code (apps/render/scripts/camera-path.ts),
so what is drawn is what the render will do. The picture holds the zoom and pan speed per frame
(against their limits) and six stills of the scene clips, cropped to the camera view, with the
focus box in red.

desktop_frame: the third graph is the zoom level over time (1.0 = the whole page), and the six
stills are the WHOLE clip frame with the zoom block (red) and the part the camera shows (green):
the zoom moments come first, then moments on the full view.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # services/api, for `app`

from PIL import Image, ImageDraw  # noqa: E402

from app.producer.motion_qa import TEMPLATE_LIMITS, camera_path  # noqa: E402

RENDER = Path(__file__).resolve().parents[3] / "apps" / "render"
STILLS = 6
THUMB = (260, 325)
W, PLOT_H = 1560, 330
PLOT_ROWS = 2


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


def levels(path: dict[str, Any]) -> list[float]:
    """Zoom level (1.0 = the full view) of every frame of the recorded scenes."""
    return [scene["full_w"] / w for scene in path["scenes"] for _x, _y, w in scene["views"]]


def level_plot(d: ImageDraw.ImageDraw, series: list[float], y0: int) -> None:
    pad, height = 40, PLOT_H // 2 - 20
    n = max(len(series), 1)
    d.rectangle((pad, y0, W - pad, y0 + height), outline="#3a4256")
    d.text((pad + 4, y0 + 2), "zoom level (1.0 = whole page, 1.7 = the shot level)", fill="#9aa4b8")
    for i, v in enumerate(series):
        x = pad + (W - 2 * pad) * i / n
        bar = height * min(1.0, (v - 1.0) / 1.0)
        d.line((x, y0 + height, x, y0 + height - bar), fill="#4fd1c5")


def still_whole(
    clip: Path, t_ms: float, view: list[float], box: dict[str, float] | None
) -> Image.Image:
    """The whole clip frame, the camera's window in green, the zoom block in red."""
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
    k = THUMB[0] / img.width
    small = img.resize((THUMB[0], round(img.height * k)))
    d = ImageDraw.Draw(small)
    x, y, w = view
    h = w * 9 / 16
    d.rectangle((x * k, y * k, (x + w) * k, (y + h) * k), outline="#4fd1c5", width=3)
    if box:
        d.rectangle(
            (box["x"] * k, box["y"] * k, (box["x"] + box["w"]) * k, (box["y"] + box["h"]) * k),
            outline="#ff3b3b", width=2,
        )  # fmt: skip
    out.unlink(missing_ok=True)
    return small


def draw_whole_stills(
    img: Image.Image,
    d: ImageDraw.ImageDraw,
    props: dict[str, Any],
    path: dict[str, Any],
    top: int,
    thumb_h: int,
) -> None:
    """desktop_frame: six frames - the zoom moments first, then moments on the full view."""
    picks: list[tuple[dict[str, Any], int, dict[str, float] | None]] = []
    for scene in path["scenes"]:
        a = props["assets"][scene["id"]]
        for z in a.get("zoom_shots") or []:
            t = (z["in_end_ms"] + z["out_start_ms"]) / 2
            i = max(
                0,
                min(
                    scene["frames"] - 1,
                    round((t - scene["start_ms"]) / 1000 * path["fps"] / scene["rate"]),
                ),
            )
            picks.append((scene, i, z["box"]))
    for scene in path["scenes"]:
        if len(picks) >= STILLS:
            break
        mid = scene["frames"] // 2
        if scene["views"][mid][2] >= scene["full_w"] * 0.98:
            picks.append((scene, mid, None))
    for n, (scene, i, box) in enumerate(picks[:STILLS]):
        t = scene["start_ms"] + i / path["fps"] * 1000 * scene["rate"]
        x = 20 + n * (THUMB[0] + 8)
        img.paste(still_whole(Path(scene["clip"]), t, scene["views"][i], box), (x, top + 20))
        label = "zoom" if box else "full view"
        d.text(
            (x, top + 24 + thumb_h + 22), f"{scene['id']} {t / 1000:.1f}s {label}", fill="#9aa4b8"
        )


def main() -> None:
    props_file, out_png = Path(sys.argv[1]), Path(sys.argv[2])
    props = json.loads(props_file.read_text(encoding="utf-8"))
    path = camera_path(props_file)
    template = props["script"].get("template", "desktop_frame")
    limits = TEMPLATE_LIMITS.get(template, TEMPLATE_LIMITS["desktop_focus"])
    still_camera = template == "desktop_frame"
    thumb_h = (
        round(THUMB[0] * path["frame"]["h"] / path["frame"]["w"]) if still_camera else THUMB[1]
    )
    zoom, pan = speeds(path)
    rows = PLOT_ROWS + (1 if still_camera else 0)
    plots_h = PLOT_H * rows // PLOT_ROWS
    img = Image.new("RGB", (W, plots_h + 2 * THUMB[1] + 80), "#101520")
    d = ImageDraw.Draw(img)
    plot(d, zoom, limits["zoom"], 0.20, 10, "zoom speed")
    plot(d, pan, limits["pan"], 0.12, 10 + PLOT_H // 2, "pan speed")
    if still_camera:
        level_plot(d, levels(path), 10 + PLOT_H)
    if still_camera:
        draw_whole_stills(img, d, props, path, plots_h, thumb_h)
        img.save(out_png)
        print(
            json.dumps(
                {
                    "png": str(out_png.resolve()),
                    "frames": len(zoom),
                    "max_zoom_level": round(max(levels(path), default=1), 3),
                    "max_zoom": round(max(zoom, default=0), 4),
                    "max_pan": round(max(pan, default=0), 4),
                }
            )
        )
        return
    PLOT_TOP = PLOT_H

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
            still(Path(scene["clip"]), t, scene["views"][i], path["frame"], focus),
            (x, PLOT_TOP + 20),
        )
        d.text((x, PLOT_TOP + THUMB[1] + 26), f"{scene['id']} {t / 1000:.1f}s", fill="#9aa4b8")
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
