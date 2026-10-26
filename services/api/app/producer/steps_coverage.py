"""How much of the flow's work is really on screen in the final clip (steps_in_clip)."""

from collections.abc import Iterable
from typing import Any

from app.schemas.generated.flow_run import FlowRun


def operation_steps(run: FlowRun) -> list[int]:
    """Numbers of the steps that do something on the page (the opening goto is not one)."""
    return [s.i for s in run.steps if s.action.do != "goto"]


def steps_in_clip(run: FlowRun, filmed: Iterable[int]) -> dict[str, Any]:
    """Share of the operation steps that appear in the clip. `filmed` = numbers of the steps whose
    mark survived the cuts (a live clip's marks, or a replay's marks that were ok)."""
    wanted = operation_steps(run)
    seen = set(filmed)
    present = [i for i in wanted if i in seen]
    return {
        "steps_in_clip": round(len(present) / len(wanted), 3) if wanted else 1.0,
        "operation_steps": len(wanted),
        "operation_steps_in_clip": len(present),
        "missing_steps": [i for i in wanted if i not in seen],
    }
