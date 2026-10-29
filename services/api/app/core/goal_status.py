"""Did the run reach the user's goal? Decided by code from the actions asked for and the real steps.

reached                a required action was really done (valid step, page changed)
stopped_before_submit  everything before is done, the commit button is highlighted (policy)
not_reached            the rest. The model's own "I finished" never decides this.
"""

from typing import Any

from app.core.commit_verbs import commit_group, fold
from app.core.flow_steps import counts

DOING = ("click", "navigate", "dblclick")
POINTING = ("hover", "highlight")


def required_groups(flow: Any) -> list[str]:
    return [commit_group(a) or fold(a) for a in flow.required_actions]


def final_button(run: Any) -> Any | None:
    """The step that highlights the commit button the run stopped at."""
    if run.status != "stopped_before_submit":
        return None
    return next((s for s in reversed(run.steps) if s.action.do in POINTING), None)


def goal_status(flow: Any, run: Any) -> str:
    stop = final_button(run)
    stop_group = commit_group(stop.target_text or "") if stop is not None else None
    first_bad = next((i for i, s in enumerate(run.steps) if not counts(s)), None)
    if stop is not None:  # steps before the closing pointing must all be valid
        before = [s for s in run.steps if s.action.do not in POINTING]
        if any(not counts(s) for s in before):
            return "not_reached"
    required = required_groups(flow)
    if not required:  # no action named by the user: the flow's own end decides, code-checked
        if stop is not None and stop_group is not None:
            return "stopped_before_submit"
        if run.status == "reached_goal" and first_bad is None:
            return "reached"
        return "not_reached"
    done = {
        commit_group(s.target_text or "") or fold(s.target_text or "")
        for s in run.steps
        if counts(s) and s.action.do in DOING and s.target_text
    }
    missing = [g for g in required if g not in done]
    if not missing:
        return "reached"
    if stop is not None and stop_group is not None and set(missing) <= {stop_group}:
        return "stopped_before_submit"
    return "not_reached"
