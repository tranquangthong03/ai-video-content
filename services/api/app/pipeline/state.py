"""job-dir/state.json: what a frontend needs to show about a job, kept next to the job's data.

state.json is written atomically (temp file + rename) so a reader never sees half a file. The
pipeline (runner.run_job) updates it as it goes; the web API only reads it and changes `status`
for queueing and cancelling.
"""

import json
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

Status = Literal["queued", "running", "waiting", "done", "failed", "cancelled"]
STATE_FILE = "state.json"
STEP_LABELS = {
    "explore": "Khám phá",
    "confirm": "Xác nhận",
    "concept": "Chọn hướng",
    "outline": "Dàn ý",
    "script": "Kịch bản",
    "produce": "Sản xuất",
    "done": "Video",
}
STEP_ORDER = tuple(STEP_LABELS)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class JobState:
    job_id: str
    url: str
    status: Status = "queued"
    step: str = "explore"
    progress_text: str = ""
    progress_pct: int = 0
    latest_screenshot: str | None = None  # relative to the job dir
    error: str | None = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# readers and writers share one process; Windows cannot replace a file another thread is reading
IO_LOCK = threading.RLock()


def read_state(job_dir: Path) -> JobState | None:
    file = job_dir / STATE_FILE
    try:
        with IO_LOCK:
            data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    known = {k: v for k, v in data.items() if k in JobState.__dataclass_fields__}
    return JobState(**known)


def write_state(job_dir: Path, state: JobState) -> None:
    state.updated_at = now_iso()
    job_dir.mkdir(parents=True, exist_ok=True)
    tmp = job_dir / f"{STATE_FILE}.tmp"
    with IO_LOCK:
        tmp.write_text(json.dumps(state.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, job_dir / STATE_FILE)


def update_state(job_dir: Path, **changes: Any) -> JobState | None:
    """Read-modify-write; a missing state.json is left missing (the job was never registered)."""
    with IO_LOCK:
        state = read_state(job_dir)
        if state is None:
            return None
        for key, value in changes.items():
            setattr(state, key, value)
        state.updated_at = now_iso()
        tmp = job_dir / f"{STATE_FILE}.tmp"
        tmp.write_text(json.dumps(state.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, job_dir / STATE_FILE)
        return state


def latest_png(folder: Path) -> Path | None:
    """The newest .png in a folder (the page the explorer just photographed)."""
    try:
        files = [p for p in folder.glob("*.png") if p.is_file()]
    except OSError:
        return None
    return max(files, key=lambda p: p.stat().st_mtime, default=None)


RECORD_RE = re.compile(r"scene (\d+)/(\d+)")
