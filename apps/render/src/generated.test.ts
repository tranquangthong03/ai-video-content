import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { EditPlanSchema, SceneSchema, ScriptSchema } from "./generated/index.js";

const example = (name: string) =>
  JSON.parse(
    readFileSync(new URL(`../../../packages/script-schema/examples/${name}`, import.meta.url), "utf8"),
  );
const scene = (type: string) => example("sample_script.json").scenes.find((s: { type: string }) => s.type === type);

describe("generated Zod schemas", () => {
  it("parses sample_script.json", () => {
    expect(ScriptSchema.parse(example("sample_script.json")).scenes).toHaveLength(4);
  });

  it("parses sample_edit_plan.json", () => {
    expect(EditPlanSchema.parse(example("sample_edit_plan.json")).ops).toHaveLength(4);
  });

  it("fills list defaults", () => {
    const s = scene("feature_demo");
    delete s.visual.actions;
    expect(SceneSchema.parse(s).visual.actions).toEqual([]);
  });

  it("rejects hook with split_vertical", () => {
    expect(SceneSchema.safeParse({ ...scene("hook"), layout: "split_vertical" }).success).toBe(false);
  });

  it("rejects extra field on hook", () => {
    expect(SceneSchema.safeParse({ ...scene("hook"), before_text: "x" }).success).toBe(false);
  });

  it("rejects missing required fields", () => {
    const { after_text: _a, ...noAfter } = scene("before_after");
    const { feature: _f, ...noFeature } = scene("feature_demo");
    expect(SceneSchema.safeParse(noAfter).success).toBe(false);
    expect(SceneSchema.safeParse(noFeature).success).toBe(false);
  });

  it("rejects fewer than 3 scenes", () => {
    const data = example("sample_script.json");
    data.scenes = data.scenes.slice(0, 2);
    expect(ScriptSchema.safeParse(data).success).toBe(false);
  });

  it("rejects an unknown edit op", () => {
    const data = example("sample_edit_plan.json");
    data.ops.push({ op: "explode" });
    expect(EditPlanSchema.safeParse(data).success).toBe(false);
  });
});
