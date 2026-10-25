"""Scene Writer: rewrite or create exactly one scene, keeping the rest of the script untouched.

Only the scene to write, its two neighbours (as summaries), the brief and a short product summary
are sent. For a rewrite, code keeps every field that was not asked for; the visual of a feature_demo
is always filled by code from the profile (see visuals.py).
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.core.demo_steps import summarize_steps
from app.llm.json_call import JsonCaller
from app.llm.prompts import render
from app.schemas.generated.scene import Scene
from app.schemas.generated.script import Script
from app.script import catalog as cat
from app.script.autotrim import trim_scene
from app.script.writer import (
    MAX_REPAIRS,
    DraftScene,
    WriterContext,
    WriterError,
    check_scene,
    scene_dict,
)

SceneField = Literal["voiceover", "on_screen_text", "visual"]


class SceneWriterOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scene: DraftScene
    notes: str | None = None


@dataclass
class SceneResult:
    scene: Scene
    warnings: list[str] = field(default_factory=list)
    attempts: int = 1


def product_summary(ctx: WriterContext) -> str:
    p = ctx.profile
    lines = [f"{p.product_name}: {p.one_liner}", "Tính năng (id | tên | demo_kind | thấy gì):"]
    for f in p.features:
        shows = summarize_steps(f) or (f.description[:80] if f.description else "")
        lines.append(f"- {f.id} | {f.name} | {f.demo_kind or 'chưa kiểm chứng'} | {shows}")
    return "\n".join(lines)


def draft_of(scene: Scene, show_setup: bool = False) -> DraftScene:
    """The writable part of an existing scene (what the LLM sees and edits)."""
    s = scene.root
    return DraftScene(
        id=s.id,
        type=s.type,
        layout=s.layout,
        feature=getattr(s, "feature", None),
        before_text=getattr(s, "before_text", None),
        after_text=getattr(s, "after_text", None),
        voiceover=s.voiceover,
        on_screen_text=s.on_screen_text,
        key_point=s.key_point,
        icon=s.icon,
        show_setup=s.visual.show_setup if s.type == "feature_demo" else None,
    )


def summarize_scene(scene: Scene | None) -> str:
    if scene is None:
        return "không có"
    s = scene.root
    return f"{s.id} ({s.type}): «{s.voiceover}» | ý chính: {s.key_point or '—'}"


def _prompt(
    ctx: WriterContext,
    script: Script,
    task: str,
    instruction: str,
    fields: list[str],
    scene_type: str,
    current: DraftScene | None,
    prev: Scene | None,
    nxt: Scene | None,
) -> str:
    return render(
        "scene_writer",
        task_type=task,
        instruction=instruction,
        fields=", ".join(fields) or "—",
        scene_type=scene_type,
        current_scene_json_or_null=current.model_dump_json(indent=1) if current else "null",
        prev_scene_summary_or_none=summarize_scene(prev),
        next_scene_summary_or_none=summarize_scene(nxt),
        goal=script.goal,
        duration_s=script.target_duration_s,
        headline=script.headline,
        product_profile_summary=product_summary(ctx),
        scene_catalog_json=cat.scene_catalog_json(),
        allowed_icons=", ".join(cat.ICONS),
    )


def _merge_rewrite(current: DraftScene, written: DraftScene, fields: list[str]) -> DraftScene:
    """Keep id, type and everything not asked for; take only the requested fields from the LLM."""
    merged = current.model_copy()
    if "voiceover" in fields:
        merged.voiceover = written.voiceover
    if "on_screen_text" in fields:
        merged.on_screen_text = written.on_screen_text
    if "visual" in fields and current.type == "feature_demo":
        merged.feature = written.feature or current.feature
        merged.show_setup = written.show_setup
    return merged


def write_scene(
    caller: JsonCaller,
    ctx: WriterContext,
    script: Script,
    *,
    task: Literal["rewrite", "insert"],
    instruction: str,
    fields: list[str] | None = None,
    scene_id: str | None = None,
    scene_type: str | None = None,
    after_scene_id: str | None = None,
) -> SceneResult:
    """Rewrite scene `scene_id` (only `fields`), or insert a new scene after `after_scene_id`."""
    fields = fields or []
    scenes = script.scenes
    if task == "rewrite":
        idx = next((i for i, s in enumerate(scenes) if s.root.id == scene_id), None)
        if idx is None:
            raise WriterError([f"không có scene {scene_id}"])
        current: DraftScene | None = draft_of(scenes[idx])
        assert current is not None
        kind = current.type
        prev = scenes[idx - 1] if idx > 0 else None
        nxt = scenes[idx + 1] if idx + 1 < len(scenes) else None
        new_id = current.id
    else:
        current = None
        kind = scene_type or "feature_demo"
        at = 0
        if after_scene_id is not None:
            found = next((i for i, s in enumerate(scenes) if s.root.id == after_scene_id), None)
            if found is None:
                raise WriterError([f"không có scene {after_scene_id}"])
            at = found + 1
        prev = scenes[at - 1] if at > 0 else None
        nxt = scenes[at] if at < len(scenes) else None
        used = {s.root.id for s in scenes}
        n = len(scenes) + 1
        while f"s{n}" in used:
            n += 1
        new_id = f"s{n}"

    base = _prompt(ctx, script, task, instruction, fields, kind, current, prev, nxt)
    prompt = base
    errors: list[str] = []
    for attempt in range(1, MAX_REPAIRS + 2):
        out = caller.call("scene", prompt, SceneWriterOutput)
        written = out.scene
        if current is not None:
            draft = _merge_rewrite(current, written, fields)
        else:
            draft = written.model_copy(update={"type": kind, "id": new_id})
        errors = check_scene(draft, "scene", ctx.features, ctx.demo_max_words)
        if not errors:
            warnings: list[str] = []
            data: dict[str, Any] = scene_dict(draft, new_id, ctx, warnings)
            return SceneResult(Scene.model_validate(data), warnings, attempt)
        listed = "\n".join(f"- {e}" for e in errors)
        prompt = (
            f"{base}\n\n<previous_output>\n{out.model_dump_json(indent=1)}\n</previous_output>\n\n"
            f"Scene trên còn lỗi, hãy sửa đúng các lỗi này và trả lại json đầy đủ cùng cấu trúc:\n"
            f"{listed}"
        )
    # the repairs are used up: formal limits are fixed by code, structure errors still fail
    fixed, trims = trim_scene(draft, "scene", ctx.demo_max_words)
    errors = check_scene(fixed, "scene", ctx.features, ctx.demo_max_words, strict_min=False)
    if errors:
        raise WriterError(errors)
    warnings = list(trims)
    data = scene_dict(fixed, new_id, ctx, warnings)
    return SceneResult(Scene.model_validate(data), warnings, MAX_REPAIRS + 1)
