"""Focus Planner: one text-only LLM call per recorded scene says which item to look at, when.

The model gets the voice-over in phrases (clip time), what was done, and what was on screen
(frame_inventory without coordinates). Its plan is checked by code: every item_id must be in the
inventory near that moment. One repair round with the errors; still wrong -> no plan, and the
rules in focus_rules.py decide alone.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from app.llm.json_call import JsonCaller, LLMCallError
from app.llm.prompts import render
from app.producer.focus_rules import find_item
from app.schemas.generated.focus_plan import FocusPlan

MAX_SNAPSHOTS = 14  # keep the prompt small: identical neighbours are dropped, then thinned
MAX_REPAIRS = 1
TOLERANCE_MS = 400  # a plan may run this far past the clip's end


def phrases_from_captions(
    captions: list[dict[str, Any]], rate: float = 1.0
) -> list[dict[str, Any]]:
    """Caption groups (scene time) -> phrases in clip time (clip time = scene time * rate)."""
    return [
        {
            "from_ms": round(c["start_ms"] * rate),
            "to_ms": round(c["end_ms"] * rate),
            "text": c["text"],
        }
        for c in captions
    ]


def compact_inventory(inventory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the model sees: id, kind, region, text, is_new; snapshots adding nothing are dropped."""
    out: list[dict[str, Any]] = []
    last: list[tuple[str, bool]] | None = None
    for snap in inventory:
        key = [(i["id"], i["is_new"]) for i in snap["items"]]
        if key == last:
            continue
        last = key
        out.append(
            {
                "t_ms": snap["t_ms"],
                "items": [
                    {k: i[k] for k in ("id", "kind", "region", "text", "is_new")}
                    for i in snap["items"]
                ],
            }
        )
    if len(out) > MAX_SNAPSHOTS:
        step = len(out) / MAX_SNAPSHOTS
        out = [out[int(n * step)] for n in range(MAX_SNAPSHOTS)]
    return out


def validate_plan(
    plan: FocusPlan, inventory: list[dict[str, Any]], duration_ms: float
) -> list[str]:
    """Problems a model can fix (English, sent back to it); empty when the plan is usable."""
    entries = plan.plan
    if not entries:
        return ["plan is empty"]
    errors: list[str] = []
    previous_end = 0
    for n, p in enumerate(entries):
        if p.to_ms <= p.from_ms:
            errors.append(f"plan[{n}]: to_ms must be greater than from_ms")
        if p.from_ms < previous_end - 50:
            errors.append(f"plan[{n}]: intervals overlap or are out of order")
        if p.to_ms > duration_ms + TOLERANCE_MS:
            errors.append(
                f"plan[{n}]: to_ms {p.to_ms} is past the clip's end ({round(duration_ms)})"
            )
        if p.item_id is not None and p.framing == "establish":
            errors.append(f"plan[{n}]: establish must have item_id null")
        if p.item_id is not None and p.to_ms > p.from_ms:
            mid = (p.from_ms + p.to_ms) / 2
            if find_item(inventory, p.item_id, mid) is None:
                errors.append(
                    f"plan[{n}]: item_id {p.item_id!r} is not in frame_inventory near {round(mid)}"
                )
        previous_end = max(previous_end, p.to_ms)
    return errors


@dataclass
class PlanResult:
    plan: list[dict[str, Any]] | None
    errors: list[str] = field(default_factory=list)  # problems of the last attempt
    attempts: int = 0


def plan_focus(
    caller: JsonCaller,
    *,
    scene_kind: str,
    feature_name: str,
    key_point: str,
    phrases: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    duration_ms: float,
) -> PlanResult:
    """One call, one repair round; PlanResult.plan is None when the model's plan cannot be used."""
    if not inventory:
        return PlanResult(None, ["no frame_inventory"])
    slim_actions = [
        {k: a.get(k) for k in ("t_ms", "end_ms", "do", "target_text", "item_id")} for a in actions
    ]
    prompt = render(
        "focus_planner",
        phrases_json=json.dumps(phrases, ensure_ascii=False),
        actions_json=json.dumps(slim_actions, ensure_ascii=False),
        inventory_json=json.dumps(compact_inventory(inventory), ensure_ascii=False),
        scene_kind=scene_kind,
        feature_name=feature_name or "(không có)",
        key_point=key_point,
    )
    prompt += f"\nĐộ dài clip: {round(duration_ms)}ms.\n"
    errors: list[str] = []
    for attempt in range(1, MAX_REPAIRS + 2):
        try:
            result = caller.call("focus_plan", prompt, FocusPlan)
        except LLMCallError as e:
            return PlanResult(None, [str(e)], attempt)
        errors = validate_plan(result, inventory, duration_ms)
        if not errors:
            return PlanResult([p.model_dump() for p in result.plan], [], attempt)
        prompt += "\nLỗi của kết quả trước, hãy sửa và trả về lại json: " + "; ".join(errors) + "\n"
    return PlanResult(None, errors, MAX_REPAIRS + 1)
