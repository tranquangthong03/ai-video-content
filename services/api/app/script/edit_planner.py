"""Edit Planner: a free-text edit request -> EditOps. The LLM only plans; apply.py executes."""

import json
from typing import Any

from app.core.demo_steps import summarize_steps
from app.llm.json_call import JsonCaller
from app.llm.prompts import render
from app.schemas.generated.edit_plan import EditPlan
from app.schemas.generated.layouts import LAYOUTS_BY_TYPE
from app.schemas.generated.script import Script
from app.script.validate import validate_edit_op
from app.script.writer import WriterContext


def script_for_planner(script: Script) -> str:
    """The script without visual details: the planner needs ids, types and words."""
    data = script.model_dump(exclude={"theme": {"font", "logo_asset", "voice_id", "language"}})
    for scene in data["scenes"]:
        visual = scene.pop("visual")
        scene["visual"] = visual["mode"]
        scene.pop("duration_ms", None)
    return json.dumps(data, ensure_ascii=False, indent=1)


def profile_for_planner(ctx: WriterContext) -> str:
    return json.dumps(
        {
            "product_name": ctx.profile.product_name,
            "features": [
                {
                    "id": f.id,
                    "name": f.name,
                    "demo_kind": f.demo_kind,
                    "demo_steps": summarize_steps(f),
                }
                for f in ctx.profile.features
            ],
        },
        ensure_ascii=False,
        indent=1,
    )


def plan_edit(
    caller: JsonCaller,
    script: Script,
    ctx: WriterContext,
    instruction: str,
    *,
    version: int,
    targets: list[dict[str, Any]] | None = None,
) -> tuple[EditPlan, list[str]]:
    """The plan, and the problems validate_edit_op finds in its ops (unknown scene, bad layout)."""
    prompt = render(
        "edit_planner",
        version=version,
        script_json=script_for_planner(script),
        product_profile_json=profile_for_planner(ctx),
        targets_json=json.dumps(targets or [], ensure_ascii=False),
        instruction=instruction,
        layouts_by_type=json.dumps({k: list(v) for k, v in LAYOUTS_BY_TYPE.items()}),
    )
    plan = caller.call("edit_plan", prompt, EditPlan)
    problems = [p for op in plan.ops for p in validate_edit_op(op, script)]
    return plan, problems
