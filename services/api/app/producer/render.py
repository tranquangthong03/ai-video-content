"""Call the Remotion project (apps/render) for one job; assets are local files (no storage)."""

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RENDER_DIR = Path(__file__).resolve().parents[4] / "apps" / "render"


@dataclass
class RenderOutcome:
    file: Path
    duration_ms: int
    render_ms: int


class RenderError(RuntimeError):
    pass


def probe(video: Path) -> dict[str, Any]:
    """ffprobe summary of the first video stream plus the container duration."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,pix_fmt,r_frame_rate",
            "-show_entries", "format=duration", "-of", "json", str(video),
        ],
        capture_output=True,
        text=True,
        check=True,
    )  # fmt: skip
    data = json.loads(out.stdout)
    stream = data["streams"][0]
    return {**stream, "duration_ms": round(float(data["format"]["duration"]) * 1000)}


RENDER_ATTEMPTS = 2  # a render can time out on a busy machine (frames wait for their clips)


def render_props(props: dict[str, Any], out_file: Path, work_dir: Path) -> RenderOutcome:
    """Render `props` (InputProps as a dict) to out_file with apps/render/scripts/render-job.ts."""
    work_dir.mkdir(parents=True, exist_ok=True)
    props_file = work_dir / "render_props.json"
    props_file.write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")
    pnpm = shutil.which("pnpm") or "pnpm"
    for attempt in range(RENDER_ATTEMPTS):
        done = subprocess.run(
            [pnpm, "exec", "tsx", "scripts/render-job.ts", str(props_file), str(out_file)],
            cwd=RENDER_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        result = next((ln for ln in done.stdout.splitlines() if ln.startswith("RESULT ")), None)
        if done.returncode == 0 and result is not None:
            break
        if attempt == RENDER_ATTEMPTS - 1:
            tail = (done.stderr or done.stdout)[-600:]
            raise RenderError(f"render failed (exit {done.returncode}): {tail}")
    assert result is not None
    data = json.loads(result.removeprefix("RESULT "))
    return RenderOutcome(Path(data["file"]), int(data["duration_ms"]), int(data["render_ms"]))
