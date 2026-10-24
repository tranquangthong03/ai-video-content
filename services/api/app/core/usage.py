"""Token accounting per pipeline step, with a hard ceiling."""

import threading
from dataclasses import dataclass, field


class BudgetExceeded(RuntimeError):
    """Raised before an LLM call when the token ceiling has been reached."""


@dataclass
class UsageTracker:
    max_tokens: int | None = None
    steps: dict[str, dict[str, int]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def add(self, step: str, prompt_tokens: int, completion_tokens: int) -> None:
        with self._lock:
            entry = self.steps.setdefault(step, {"input": 0, "output": 0, "calls": 0})
            entry["input"] += prompt_tokens
            entry["output"] += completion_tokens
            entry["calls"] += 1

    @property
    def total(self) -> int:
        return sum(s["input"] + s["output"] for s in self.steps.values())

    def check(self) -> None:
        if self.max_tokens is not None and self.total >= self.max_tokens:
            raise BudgetExceeded(f"token ceiling reached: {self.total} >= {self.max_tokens}")

    def to_dict(self) -> dict[str, object]:
        return {"max_tokens": self.max_tokens, "total": self.total, "steps": self.steps}

    @classmethod
    def from_dict(cls, data: dict[str, object], max_tokens: int | None = None) -> "UsageTracker":
        steps = data.get("steps", {})
        return cls(max_tokens=max_tokens, steps=dict(steps) if isinstance(steps, dict) else {})
