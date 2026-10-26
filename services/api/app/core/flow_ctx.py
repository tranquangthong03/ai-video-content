"""What the script step needs to know about the approved flow (plain data, saved as JSON so a
resumed job can write the script without rerunning the agent)."""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.generated.flow_run import FlowRun

FLOW_CTX_FILE = "flow_context.json"


def live_inventory(job_dir: Path, run: FlowRun) -> list[dict[str, Any]]:
    """Frame inventory logged while the agent ran (empty when the flow was not filmed live)."""
    if run.live is None:
        return []
    try:
        logs = json.loads((job_dir / run.live.logs).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return list(logs.get("inventory", []))


class ChapterCtx(BaseModel):
    id: str
    title: str
    notes: list[str] = Field(default_factory=list)  # the agent's one-line note per step
    steps: int = 0
    value_line: str | None = None  # what the persona gets from this stretch (from the storyboard)


class FlowCtx(BaseModel):
    flow_id: str
    title: str
    persona: str
    goal: str
    success_signal: str
    value: str
    needs_submit: bool = False
    status: str = "reached_goal"
    submit_policy: str = "stop"
    hero_texts: list[str] = Field(default_factory=list)  # prominent texts of the best frame
    chapters: list[ChapterCtx]
    # what each scene shows: a Visual dict per chapter id, plus the opening and closing scenes
    visuals: dict[str, dict[str, Any]] = Field(default_factory=dict)
    hook_visual: dict[str, Any] = Field(default_factory=dict)
    cta_visual: dict[str, Any] = Field(default_factory=dict)

    def prompt_json(self) -> str:
        """The part the script writer reads (visuals are filled in by code, not by the model)."""
        data = self.model_dump(exclude={"visuals", "hook_visual", "cta_visual"})
        return json.dumps(data, ensure_ascii=False, indent=1)

    def save(self, job_dir: Path) -> None:
        (job_dir / FLOW_CTX_FILE).write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, job_dir: Path) -> "FlowCtx | None":
        file = job_dir / FLOW_CTX_FILE
        return cls.model_validate_json(file.read_text(encoding="utf-8")) if file.is_file() else None
