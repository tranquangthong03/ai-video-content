"""JobRunner: one background thread that runs at most one job at a time; the rest wait in a queue.

A job's data lives in its job dir (out/jobs/<id>/): job.json (what to run), state.json (progress),
pending.json / responses/ (the question being asked and its answer), plus everything the pipeline
writes. Only the queue is kept in memory, so a restarted server finds every job on disk.
"""

import json
import threading
import traceback
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.credentials import cleanup_job_secrets, sweep_old_jobs
from app.pipeline.file_frontend import POLL_S, FileFrontend
from app.pipeline.proposal_run import Cancelled
from app.pipeline.runner import JobConfig, JobResult, run_job
from app.pipeline.state import JobState, read_state, update_state, write_state

JOB_FILE = "job.json"
Pipeline = Callable[[JobConfig, FileFrontend], JobResult]
RESTART_ERROR = "Máy chủ đã khởi động lại"


def default_pipeline(cfg: JobConfig, frontend: FileFrontend) -> JobResult:
    return run_job(cfg, frontend)


class JobRunner:
    def __init__(
        self,
        root: Path,
        pipeline: Pipeline = default_pipeline,
        *,
        start: bool = True,
        poll_s: float = POLL_S,
    ) -> None:
        self.root = root
        self.poll_s = poll_s
        self.pipeline = pipeline
        self.queue: deque[str] = deque()
        self.current: str | None = None
        self.cancels: dict[str, threading.Event] = {}
        self.cond = threading.Condition()
        self.stopping = False
        self.root.mkdir(parents=True, exist_ok=True)
        sweep_old_jobs(self.root)  # secrets of jobs untouched for a day
        self.recover()
        self.thread = threading.Thread(target=self._loop, name="job-runner", daemon=True)
        if start:
            self.thread.start()

    # --- registry ------------------------------------------------------------------------------

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def create(
        self,
        job_id: str,
        url: str,
        *,
        has_auth: bool,
        requires_login: bool = False,
        login_url: str | None = None,
    ) -> Path:
        directory = self.job_dir(job_id)
        directory.mkdir(parents=True, exist_ok=False)
        spec = {
            "url": url,
            "storage_state": "storage_state.json" if has_auth else None,
            "requires_login": requires_login,
            "login_url": login_url,
        }
        (directory / JOB_FILE).write_text(json.dumps(spec), encoding="utf-8")
        write_state(directory, JobState(job_id=job_id, url=url, status="queued"))
        return directory

    def jobs(self) -> list[JobState]:
        found = [s for d in self.root.iterdir() if d.is_dir() and (s := read_state(d)) is not None]
        return sorted(found, key=lambda s: s.created_at, reverse=True)

    def recover(self) -> None:
        """After a restart whatever was running or waiting failed; queued jobs go on."""
        for state in sorted(self.jobs(), key=lambda s: s.created_at):
            directory = self.job_dir(state.job_id)
            if state.status in ("running", "waiting"):
                (directory / "pending.json").unlink(missing_ok=True)
                update_state(directory, status="failed", error=RESTART_ERROR)
            elif state.status == "queued":
                self.queue.append(state.job_id)

    # --- queue ---------------------------------------------------------------------------------

    def submit(self, job_id: str, *, resume: bool = False, from_step: str = "explore") -> None:
        """Queue a job; `resume` reuses saved work, from_step picks where it starts."""
        directory = self.job_dir(job_id)
        spec = json.loads((directory / JOB_FILE).read_text(encoding="utf-8"))
        spec.update(resume=resume, from_step=from_step)
        (directory / JOB_FILE).write_text(json.dumps(spec), encoding="utf-8")
        with self.cond:
            update_state(directory, status="queued", error=None)
            self.cancels[job_id] = threading.Event()
            self.queue.append(job_id)
            self.cond.notify()

    def position(self, job_id: str) -> int | None:
        """1 = next to run; None when the job is not waiting in the queue."""
        with self.cond:
            return self.queue.index(job_id) + 1 if job_id in self.queue else None

    def cancel(self, job_id: str) -> bool:
        with self.cond:
            if job_id in self.queue:
                self.queue.remove(job_id)
                update_state(self.job_dir(job_id), status="cancelled", error=None)
                return True
            event = self.cancels.get(job_id)
            if event is not None and self.current == job_id:
                event.set()
                return True
        return False

    def stop(self) -> None:
        with self.cond:
            self.stopping = True
            for event in self.cancels.values():
                event.set()
            self.cond.notify_all()

    # --- the worker ----------------------------------------------------------------------------

    def _loop(self) -> None:
        while True:
            with self.cond:
                while not self.queue and not self.stopping:
                    self.cond.wait()
                if self.stopping:
                    return
                job_id = self.queue.popleft()
                self.current = job_id
                cancel = self.cancels.setdefault(job_id, threading.Event())
            try:
                self._run(job_id, cancel)
            finally:
                with self.cond:
                    self.current = None

    def _run(self, job_id: str, cancel: threading.Event) -> None:
        directory = self.job_dir(job_id)
        try:
            spec: dict[str, Any] = json.loads((directory / JOB_FILE).read_text(encoding="utf-8"))
            auth = spec.get("storage_state")
            cfg = JobConfig(
                url=spec["url"],
                job_dir=directory,
                storage_state=directory / auth if auth and (directory / auth).is_file() else None,
                resume=bool(spec.get("resume")),
                from_step=spec.get("from_step", "explore"),
                requires_login=bool(spec.get("requires_login")),
                login_url=spec.get("login_url"),
                should_stop=cancel.is_set,
            )
            update_state(directory, status="running", error=None)
            result = self.pipeline(cfg, FileFrontend(directory, cancel, self.poll_s))
            if cancel.is_set() and result.status == "failed":
                update_state(directory, status="cancelled", error=None)
        except Cancelled:
            update_state(directory, status="cancelled", error=None)
        except Exception as e:  # a crash must end the job, never the worker
            (directory / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
            update_state(
                directory, status="failed", error=f"Lỗi không mong đợi: {type(e).__name__}: {e}"
            )
        finally:
            state = read_state(directory)
            if state is not None and state.status in ("done", "cancelled"):
                cleanup_job_secrets(directory)  # a failed job keeps them for "Chạy tiếp" (24 h)
