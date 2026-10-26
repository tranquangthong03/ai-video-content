import { FIELDS_BY_TYPE, LAYOUTS_BY_TYPE, type EditOp, type Script } from "./generated";

type Table = Record<string, readonly string[]>;

/** Returns human-readable errors; empty array means the op is consistent with the script. */
export function validateEditOp(op: EditOp, script: Script): string[] {
  const errors: string[] = [];
  const scenes = new Map(script.scenes.map((s) => [s.id, s]));

  for (const key of ["scene_id", "after_scene_id"] as const) {
    const ref = (op as Record<string, unknown>)[key];
    if (typeof ref === "string" && !scenes.has(ref)) errors.push(`${op.op}: unknown ${key} '${ref}'`);
  }

  if (op.op === "set") {
    const scene = scenes.get(op.scene_id);
    if (scene && op.field === "hook_option") {
      if (scene.type !== "hook") errors.push(`set: hook_option only applies to a hook scene, not ${scene.id}`);
      else if (!(script.hook_options ?? []).some((o, i) => op.value === String(i + 1) || op.value === o.kind)) {
        errors.push(`set: no hook option '${op.value}'`);
      }
    } else if (scene && !(FIELDS_BY_TYPE as Table)[scene.type].includes(op.field)) {
      errors.push(`set: field '${op.field}' does not exist on scene ${scene.id} (type '${scene.type}')`);
    } else if (scene && op.field === "layout" && !(LAYOUTS_BY_TYPE as Table)[scene.type].includes(op.value)) {
      errors.push(`set: layout '${op.value}' is invalid for scene ${scene.id} (type '${scene.type}')`);
    }
  }
  return errors;
}
