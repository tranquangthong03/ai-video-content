"""Apply EditOps to a Script.

set / delete / move / set_theme are applied deterministically here. rewrite and insert need the
LLM, so they come back as `llm_tasks` for the Scene Writer; set_global changes the brief and needs
the whole script written again (`needs_full_regen`). Scenes no op mentions stay byte-identical.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.schemas.generated.edit_op import (
    DeleteOp,
    EditOp,
    InsertOp,
    MoveOp,
    RewriteOp,
    SetGlobalOp,
    SetOp,
    SetThemeOp,
)
from app.schemas.generated.script import Script
from app.script import catalog as cat
from app.script.validate import validate_edit_op, validate_script
from app.script.visuals import visual_for_scene
from app.script.writer import WriterContext

MIN_SCENES = 3
THEME_ENUMS = {
    "motion_preset": ("energetic", "calm"),
    "caption_style": ("tiktok_bounce", "minimal", "karaoke"),
    "music_mood": ("energetic", "upbeat", "calm", "corporate"),
}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
FIELD_LABELS = {
    "voiceover": "lời đọc",
    "on_screen_text": "chữ trên màn hình",
    "layout": "bố cục",
    "feature": "tính năng",
}


@dataclass
class ApplyResult:
    script: Script
    changes: list[str] = field(default_factory=list)
    llm_tasks: list[dict[str, Any]] = field(default_factory=list)
    needs_full_regen: bool = False
    global_ops: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def unpack(self) -> tuple[Script, list[str], list[dict[str, Any]], bool]:
        return self.script, self.changes, self.llm_tasks, self.needs_full_regen


def _index(scenes: list[dict[str, Any]], scene_id: str) -> int | None:
    return next((i for i, s in enumerate(scenes) if s["id"] == scene_id), None)


def apply_ops(
    script: Script, ops: list[EditOp] | list[Any], ctx: WriterContext | None = None
) -> ApplyResult:
    """Apply ops in order. Invalid ones are skipped and reported in `errors`, never half-applied."""
    result = ApplyResult(script)
    data = script.model_dump()
    scenes: list[dict[str, Any]] = data["scenes"]

    def current() -> Script:
        return Script.model_validate(data)

    for wrapped in ops:
        op = getattr(wrapped, "root", wrapped)
        wrapped_op = wrapped if isinstance(wrapped, EditOp) else EditOp(root=wrapped)
        problems = validate_edit_op(wrapped_op, current())
        if problems:
            result.errors += problems
            continue
        if isinstance(op, SetOp):
            _set(op, scenes, result, ctx, data)
        elif isinstance(op, DeleteOp):
            if len(scenes) <= MIN_SCENES:
                result.errors.append(f"delete: video cần ít nhất {MIN_SCENES} scene")
                continue
            i = _index(scenes, op.scene_id)
            assert i is not None
            removed = scenes.pop(i)
            if removed["type"] in ("hook", "cta"):
                result.warnings.append(f"đã xóa scene {removed['type']} {op.scene_id}")
            result.changes.append(f"Xóa scene {op.scene_id} ({removed['type']})")
        elif isinstance(op, MoveOp):
            _move(op, scenes, result)
        elif isinstance(op, SetThemeOp):
            _set_theme(op, data, result)
        elif isinstance(op, RewriteOp):
            result.llm_tasks.append(
                {
                    "kind": "rewrite",
                    "scene_id": op.scene_id,
                    "fields": list(op.fields),
                    "instruction": op.instruction,
                }
            )
            result.changes.append(f"Viết lại {', '.join(op.fields)} của scene {op.scene_id}")
        elif isinstance(op, InsertOp):
            result.llm_tasks.append(
                {
                    "kind": "insert",
                    "after_scene_id": op.after_scene_id,
                    "scene_type": op.scene_type,
                    "instruction": op.instruction,
                }
            )
            result.changes.append(f"Thêm scene {op.scene_type}: {op.instruction}")
        elif isinstance(op, SetGlobalOp):
            result.needs_full_regen = True
            result.global_ops.append({"field": op.field, "value": op.value})
            result.changes.append(f"Đổi định hướng chung ({op.field}) → viết lại toàn bộ kịch bản")

    try:
        rebuilt = current()
        result.script = script if rebuilt == script else rebuilt  # untouched: same object
    except ValidationError as e:  # a bug here would silently drop the user's edit
        result.errors.append(f"kịch bản sau chỉnh sửa không hợp lệ: {e.errors()[0]['msg']}")
        result.script = script
        return result
    result.errors += validate_script(result.script)
    return result


def _set(
    op: SetOp,
    scenes: list[dict[str, Any]],
    result: ApplyResult,
    ctx: WriterContext | None,
    data: dict[str, Any],
) -> None:
    i = _index(scenes, op.scene_id)
    assert i is not None
    scene = scenes[i]
    value = op.value.strip()
    label = FIELD_LABELS[op.field]
    if op.field == "feature":
        if ctx is None or value not in ctx.features:
            result.errors.append(f"set: tính năng «{value}» không có trong sản phẩm")
            return
        scene["feature"] = value
        visual = visual_for_scene(
            "feature_demo",
            ctx.features[value],
            ctx.home_url,
            setup_len=ctx.setup_counts.get(value),
            show_setup=scene["visual"].get("show_setup", False),
            scene_id=op.scene_id,
            lite=ctx.lite,
        )
        scene["visual"] = visual.visual
        result.warnings += visual.warnings
    elif op.field == "layout":
        scene["layout"] = value
    elif op.field == "voiceover":
        words = cat.word_count(value)
        if words > cat.VOICEOVER_MAX_WORDS:
            result.warnings.append(f"scene {op.scene_id}: lời đọc {words} từ (khuyến nghị ≤ 30)")
        scene["voiceover"] = value
    else:
        scene["on_screen_text"] = value or None
    result.changes.append(f"Scene {op.scene_id}: đặt {label} = «{value}»")


def _move(op: MoveOp, scenes: list[dict[str, Any]], result: ApplyResult) -> None:
    i = _index(scenes, op.scene_id)
    assert i is not None
    scene = scenes.pop(i)
    at = 0
    if op.after_scene_id is not None:
        j = _index(scenes, op.after_scene_id)
        if j is None or op.after_scene_id == op.scene_id:
            scenes.insert(i, scene)
            result.errors.append(f"move: không có scene {op.after_scene_id}")
            return
        at = j + 1
    scenes.insert(at, scene)
    result.changes.append(f"Chuyển scene {op.scene_id} sang vị trí {at + 1}")


def _set_theme(op: SetThemeOp, data: dict[str, Any], result: ApplyResult) -> None:
    theme = data["theme"]
    value = op.value.strip()
    if op.field == "primary":
        if not HEX.match(value):
            result.errors.append(f"set_theme: màu «{value}» không hợp lệ (cần dạng #RRGGBB)")
            return
        value = value.upper()
    elif op.field in THEME_ENUMS and value not in THEME_ENUMS[op.field]:
        result.errors.append(
            f"set_theme: {op.field} «{value}» không hợp lệ ({', '.join(THEME_ENUMS[op.field])})"
        )
        return
    old = theme[op.field]
    theme[op.field] = value
    result.changes.append(f"Đổi {op.field}: {old} → {value}")
