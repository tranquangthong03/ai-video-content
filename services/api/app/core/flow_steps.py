"""Which steps of a Flow Agent run count as part of the flow (storyboard, outline, value)."""

from typing import Any


def counts(step: Any) -> bool:
    """False for a step whose page stayed empty (blank) or did not change (no_effect)."""
    return not (getattr(step, "blank", False) or getattr(step, "no_effect", False))
