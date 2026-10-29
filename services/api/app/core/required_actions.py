"""What the user asked a flow to DO, kept as the goal (pure functions, vi + en).

The actions a user names in their own description ("thêm vào giỏ", "add to cart", "save the
form") are the goal of the flow: a model must not swap them for an easier flow. The LLM proposes
`required_actions`; code keeps only those whose verb really is in the description, adds the
commit verbs found in it, and makes sure the flow's steps mention each one.
"""

from typing import Any

from app.core.commit_verbs import COMMIT_RE, commit_verb, fold

MAX_REQUIRED = 4


def detect(description: str) -> list[str]:
    """Commit phrases of the description, in its own words order of appearance (folded)."""
    text = fold(description)
    found: list[tuple[int, str]] = []
    for m in COMMIT_RE.finditer(text):
        found.append((m.start(), m.group(1)))
    seen: list[str] = []
    for _, phrase in sorted(found):
        if phrase not in seen:
            seen.append(phrase)
    return seen


def validate(candidates: list[str], description: str) -> list[str]:
    """Model-proposed actions whose verb (a commit verb, else the first word) is in the text."""
    text = fold(description)
    kept: list[str] = []
    for raw in candidates:
        action = raw.strip()
        if not action:
            continue
        verb = commit_verb(action) or (fold(action).split() or [""])[0]
        if verb and verb in text and action not in kept:
            kept.append(action)
    return kept


def covered(action: str, texts: list[str]) -> bool:
    """Do the flow's texts (goal, steps, title) mention the action?"""
    wanted = commit_verb(action) or fold(action)
    return any(wanted in fold(t) for t in texts)


def required_for(description: str, proposed: list[str]) -> list[str]:
    out = validate(proposed, description)
    for phrase in detect(description):
        if not any(commit_verb(a) == phrase for a in out):
            out.append(phrase)
    return out[:MAX_REQUIRED]


def enforce(flow: Any, description: str, max_steps: int = 12) -> list[str]:
    """Set flow.required_actions and make the flow say them: a missing one becomes a last step
    and the goal falls back to the user's words. Returns notes for the card."""
    flow.required_actions = required_for(description, list(flow.required_actions))
    texts = [flow.title, flow.goal, flow.success_signal, *flow.expected_steps]
    notes: list[str] = []
    for action in flow.required_actions:
        if covered(action, texts):
            continue
        if len(flow.expected_steps) < max_steps:
            flow.expected_steps.append(f"Thực hiện: {action}")
        flow.goal = f"{flow.goal.rstrip('. ')}. Yêu cầu của bạn: {description.strip()[:160]}"
        notes.append(f"giữ đúng hành động bạn yêu cầu: {action}")
        texts = [flow.title, flow.goal, *flow.expected_steps]
    return notes
