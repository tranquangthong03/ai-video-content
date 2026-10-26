"""Manual validators for rules the generated models cannot express (cross-object references)."""

from app.schemas.generated.edit_op import EditOp, SetOp
from app.schemas.generated.layouts import LAYOUTS_BY_TYPE
from app.schemas.generated.scene_meta import FIELDS_BY_TYPE
from app.schemas.generated.script import Script


def validate_script(script: Script) -> list[str]:
    """Return semantic errors of a Script. Per-scene layout rules are enforced by the schema."""
    errors: list[str] = []
    if script.headline_highlight and script.headline_highlight not in script.headline:
        errors.append("headline_highlight must be a substring of headline")
    seen: set[str] = set()
    for scene in script.scenes:
        if scene.root.id in seen:
            errors.append(f"scene {scene.root.id}: duplicate scene id")
        seen.add(scene.root.id)
    return errors


def hook_choice(script: Script, value: str) -> int | None:
    """Index of the hook option named by its kind or by its number (1 or 2), else None."""
    options = script.hook_options
    if value.strip().isdigit() and 1 <= int(value) <= len(options):
        return int(value) - 1
    return next((i for i, o in enumerate(options) if o.kind == value.strip()), None)


def validate_edit_op(op: EditOp, script: Script) -> list[str]:
    """Check that an EditOp refers to existing scenes and keeps layouts valid for the scene type."""
    errors: list[str] = []
    inner = op.root
    scenes = {s.root.id: s.root for s in script.scenes}
    for attr in ("scene_id", "after_scene_id"):
        ref = getattr(inner, attr, None)
        if ref is not None and ref not in scenes:
            errors.append(f"{inner.op}: unknown {attr} '{ref}'")
    if isinstance(inner, SetOp) and inner.scene_id in scenes:
        scene = scenes[inner.scene_id]
        if inner.field == "hook_option":
            if scene.type != "hook":
                errors.append(f"set: hook_option chỉ dùng cho scene hook, không phải {scene.id}")
            elif hook_choice(script, inner.value) is None:
                errors.append(f"set: không có phương án hook «{inner.value}»")
        elif inner.field not in FIELDS_BY_TYPE[scene.type]:
            errors.append(
                f"set: field '{inner.field}' does not exist on scene {scene.id} "
                f"(type '{scene.type}')"
            )
        elif inner.field == "layout" and inner.value not in LAYOUTS_BY_TYPE[scene.type]:
            errors.append(
                f"set: layout '{inner.value}' is invalid for scene {scene.id} (type '{scene.type}')"
            )
    return errors
