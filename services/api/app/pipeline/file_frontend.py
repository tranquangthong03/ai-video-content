"""FileFrontend: a Frontend that talks through files, for the web API.

ask() writes job-dir/pending.json (the InteractionRequest), sets the job to "waiting" and BLOCKS the
calling thread until job-dir/responses/<interaction_id>.json appears (the API writes it after
checking the answer). Only suitable while one job runs at a time; running several jobs in parallel
would need resuming per step instead of blocking a thread (LangGraph, later).
"""

import json
import os
import threading
import time
from pathlib import Path

from app.pipeline.proposal_run import Cancelled
from app.pipeline.state import IO_LOCK, update_state
from app.schemas.generated.interaction import InteractionRequest
from app.schemas.generated.user_response import UserResponse

PENDING = "pending.json"
RESPONSES = "responses"
POLL_S = 0.5


def write_json_atomic(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with IO_LOCK:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)


class FileFrontend:
    def __init__(self, job_dir: Path, cancel: threading.Event, poll_s: float = POLL_S) -> None:
        self.dir = job_dir
        self.cancel = cancel
        self.poll_s = poll_s

    def info(self, text: str) -> None:  # log lines are not shown in the web UI
        pass

    def ask(self, request: InteractionRequest) -> UserResponse:
        answer = self.dir / RESPONSES / f"{request.interaction_id}.json"
        pending = self.dir / PENDING
        write_json_atomic(pending, request.model_dump(mode="json", exclude_none=True))
        update_state(self.dir, status="waiting")
        try:
            while not answer.is_file():
                if self.cancel.is_set():  # checked twice a second: Hủy takes effect at once
                    raise Cancelled("hủy bởi người dùng")
                time.sleep(self.poll_s)
            return UserResponse.model_validate_json(answer.read_text(encoding="utf-8"))
        finally:
            with IO_LOCK:
                pending.unlink(missing_ok=True)
            update_state(self.dir, status="running")
