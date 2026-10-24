"""One round of editing: free text or explicit ops -> a new script, touching only what was asked."""

from dataclasses import dataclass, field, replace
from typing import Any

from app.llm.json_call import JsonCaller, LLMCallError
from app.schemas.generated.edit_plan import Clarification
from app.schemas.generated.outline import Outline
from app.schemas.generated.script import Script
from app.script.apply import apply_ops
from app.script.edit_planner import plan_edit
from app.script.scene_writer import write_scene
from app.script.writer import WriterContext, WriterError

DURATIONS = (30, 45, 60)


@dataclass
class EditOutcome:
    script: Script
    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)  # "request — reason (gợi ý: …)"
    clarification: Clarification | None = None
    global_ops: list[dict[str, Any]] = field(default_factory=list)  # set_global: write it all again

    @property
    def full_regen(self) -> bool:
        return bool(self.global_ops)

    @property
    def changed(self) -> bool:
        return bool(self.changes)


def apply_global(
    ctx: WriterContext, global_ops: list[dict[str, Any]]
) -> tuple[WriterContext, list[str]]:
    """Brief changes of set_global -> a new writer context (outline updated, notes added)."""
    data = ctx.outline.model_dump()
    notes = list(ctx.notes)
    warnings: list[str] = []
    for op in global_ops:
        field_, value = op["field"], op["value"]
        if field_ == "goal":
            data["goal"] = str(value)
        elif field_ == "duration":
            try:
                seconds = int(float(str(value).split()[0]))
            except (ValueError, IndexError):
                seconds = -1
            if seconds in DURATIONS:
                data["duration_s"] = seconds
            else:
                warnings.append(f"thời lượng «{value}» không hợp lệ (30/45/60), giữ nguyên")
        elif field_ == "features":
            ids = value if isinstance(value, list) else [v.strip() for v in str(value).split(",")]
            known = {f.id for f in ctx.profile.features}
            ok = [i for i in ids if i in known]
            if len(ok) < len(ids):
                warnings.append(f"bỏ qua tính năng không có trong sản phẩm: {set(ids) - known}")
            if ok:
                data["feature_ids"] = ok
        elif field_ == "cta" and data["beats"]:
            data["beats"][-1]["text"] = str(value)
        else:  # tone, audience: no field in the outline, passed to the writer as a note
            notes.append(f"{field_}: {value}")
    return replace(ctx, outline=Outline.model_validate(data), notes=notes), warnings


def apply_edit(
    caller: JsonCaller,
    script: Script,
    ctx: WriterContext,
    *,
    instruction: str | None = None,
    ops: list[Any] | None = None,
    targets: list[dict[str, Any]] | None = None,
    version: int = 1,
) -> EditOutcome:
    """Plan (unless `ops` are given), apply deterministic ops, run the Scene Writer tasks."""
    outcome = EditOutcome(script)
    plan_ops: list[Any] = list(ops or [])
    if not plan_ops:
        if not instruction or not instruction.strip():
            outcome.errors.append("chưa có yêu cầu sửa")
            return outcome
        try:
            plan, problems = plan_edit(
                caller, script, ctx, instruction, version=version, targets=targets
            )
        except LLMCallError as e:
            outcome.errors.append(f"chưa hiểu được yêu cầu ({e})")
            return outcome
        outcome.rejected = [
            f"{r.request} — {r.reason}" + (f" (gợi ý: {r.suggestion})" if r.suggestion else "")
            for r in plan.rejected
        ]
        if plan.status == "needs_clarification" and plan.clarification:
            outcome.clarification = plan.clarification
            return outcome
        outcome.warnings += [f"bỏ qua thao tác không hợp lệ: {p}" for p in problems]
        plan_ops = list(plan.ops)

    applied = apply_ops(script, plan_ops, ctx)
    outcome.changes += applied.changes
    outcome.warnings += applied.warnings
    outcome.errors += applied.errors
    outcome.global_ops = applied.global_ops
    current = applied.script

    for task in applied.llm_tasks:
        try:
            if task["kind"] == "rewrite":
                done = write_scene(
                    caller,
                    ctx,
                    current,
                    task="rewrite",
                    instruction=task["instruction"],
                    fields=task["fields"],
                    scene_id=task["scene_id"],
                )
                data = current.model_dump()
                at = next(i for i, s in enumerate(data["scenes"]) if s["id"] == task["scene_id"])
                data["scenes"][at] = done.scene.root.model_dump()
            else:
                done = write_scene(
                    caller,
                    ctx,
                    current,
                    task="insert",
                    instruction=task["instruction"],
                    scene_type=task["scene_type"],
                    after_scene_id=task["after_scene_id"],
                )
                data = current.model_dump()
                after = task["after_scene_id"]
                at = 0
                if after is not None:
                    at = next(i for i, s in enumerate(data["scenes"]) if s["id"] == after) + 1
                data["scenes"].insert(at, done.scene.root.model_dump())
            current = Script.model_validate(data)
            outcome.warnings += done.warnings
        except (WriterError, LLMCallError, StopIteration) as e:
            what = task.get("scene_id") or task.get("after_scene_id") or "đầu video"
            outcome.errors.append(f"không viết được scene ({what}): {e}")
            outcome.changes = [c for c in outcome.changes if not _is_task_change(c, task)]
    outcome.script = current
    return outcome


def _is_task_change(change: str, task: dict[str, Any]) -> bool:
    if task["kind"] == "rewrite":
        return change.startswith("Viết lại") and change.endswith(task["scene_id"])
    return change.startswith("Thêm scene") and task["instruction"] in change
