"""Run report (report.json) and the overall time budget of the explorer."""

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class DeadlineExceeded(RuntimeError):
    pass


@dataclass
class Deadline:
    seconds: float = 300.0
    started: float = field(default_factory=time.monotonic)

    def remaining(self) -> float:
        return self.seconds - (time.monotonic() - self.started)

    def expired(self) -> bool:
        return self.remaining() <= 0

    def check(self, step: str = "") -> None:
        if self.expired():
            raise DeadlineExceeded(
                f"explorer time budget ({self.seconds:.0f}s) exhausted at {step}"
            )


@dataclass
class Report:
    """Collected facts about one explorer run; written to report.json."""

    url: str
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.data = {
            "url": self.url,
            "site_type": None,
            "pages_seen": [],
            "pages_skipped": [],
            "blockers": [],
            "timings_s": {},
            "tokens": {},
            "clicks": [],
            "clicks_blocked": [],
            "request_guard": {},
            "out_of_scope": [],
            "grouped_pages": {},
            "anchor_sections": 0,
            "locate": {"strategies": {}, "failures": []},
            "step_errors": [],
            "auto_upload": [],
            "enter": {"pressed": 0, "blocked": []},
            "warnings": [],
            "status": "running",
            **self.data,
        }

    @contextmanager
    def timed(self, step: str):  # type: ignore[no-untyped-def]
        start = time.monotonic()
        try:
            yield
        finally:
            timings = self.data["timings_s"]
            timings[step] = round(timings.get(step, 0) + time.monotonic() - start, 2)

    def warn(self, message: str) -> None:
        self.data["warnings"].append(message)

    def block(self, phase: str, name: str, reason: str, detail: str = "", **extra: Any) -> None:
        """A refused click; reason is blacklist, leaves_site, out_of_scope, not_found or other."""
        self.data["clicks_blocked"].append(
            {"phase": phase, "name": name, "reason": reason, "detail": detail, **extra}
        )

    def record_locate(self, where: str, strategy: str | None, tried: list[str]) -> None:
        """Which locate strategy found an element (or why none did)."""
        locate = self.data["locate"]
        if strategy:
            locate["strategies"][strategy] = locate["strategies"].get(strategy, 0) + 1
        elif len(locate["failures"]) < 30:
            locate["failures"].append({"where": where, "tried": tried})

    def step_error(
        self, feature: str, step: int, kind: str, tried: list[str], screenshot: str | None
    ) -> None:
        self.data["step_errors"].append(
            {
                "feature": feature,
                "step": step,
                "kind": kind,
                "tried": tried,
                "screenshot": screenshot,
            }
        )

    def skip(self, url: str, reason: str) -> None:
        self.data["pages_skipped"].append({"url": url, "reason": reason})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
