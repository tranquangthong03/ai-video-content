import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { ScriptSchema, type EditOp } from "./generated";
import { validateEditOp } from "./validate-edit-op";

const script = ScriptSchema.parse(
  JSON.parse(
    readFileSync(new URL("../../../packages/script-schema/examples/sample_script.json", import.meta.url), "utf8"),
  ),
);

describe("validateEditOp", () => {
  it("accepts a layout valid for the scene type", () => {
    const op: EditOp = { op: "set", scene_id: "s4", field: "layout", value: "logo_center" };
    expect(validateEditOp(op, script)).toEqual([]);
  });

  it("rejects a layout invalid for the scene type", () => {
    const op: EditOp = { op: "set", scene_id: "s4", field: "layout", value: "swipe" };
    expect(validateEditOp(op, script)).toHaveLength(1);
  });

  it("rejects set feature on a hook, accepts it on feature_demo", () => {
    const onHook: EditOp = { op: "set", scene_id: "s1", field: "feature", value: "x" };
    const onDemo: EditOp = { op: "set", scene_id: "s2", field: "feature", value: "x" };
    expect(validateEditOp(onHook, script)).toHaveLength(1);
    expect(validateEditOp(onDemo, script)).toEqual([]);
  });

  it("accepts set on_screen_text on every scene type", () => {
    for (const scene of script.scenes) {
      const op: EditOp = { op: "set", scene_id: scene.id, field: "on_screen_text", value: "x" };
      expect(validateEditOp(op, script)).toEqual([]);
    }
  });

  it("rejects unknown scene references", () => {
    expect(validateEditOp({ op: "delete", scene_id: "nope" }, script)).toHaveLength(1);
    expect(validateEditOp({ op: "move", scene_id: "s1", after_scene_id: "nope" }, script)).toHaveLength(1);
    expect(validateEditOp({ op: "move", scene_id: "s1", after_scene_id: null }, script)).toEqual([]);
  });
});
