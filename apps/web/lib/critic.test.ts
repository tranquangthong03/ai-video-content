import { describe, expect, it } from "vitest";
import { criticRows } from "./critic";
import { validateEditOp } from "./validate-edit-op";
import { setOpFields } from "./responses";

const view = (hook: number, proof: number | null) => ({
  scores: {
    hook_strength: { score: hook, reason: "a" },
    benefit_clarity: { score: 8, reason: "b" },
    proof_usage: { score: proof, reason: "c" },
    cta_strength: { score: 7, reason: "d" },
    flow: { score: 9, reason: "e" },
  },
  weak_scenes: [],
  issues: [],
  summary: "",
});

describe("critic bars", () => {
  it("one row per criterion with the bar width and the pass flag against the threshold", () => {
    const rows = criticRows({ threshold: 7, before: view(5, 8), final: view(8, 8) });
    expect(rows.map((r) => r.key)).toEqual(["hook_strength", "benefit_clarity", "proof_usage", "cta_strength", "flow"]);
    expect(rows[0]).toMatchObject({ score: 8, percent: 80, ok: true });
    expect(rows[3]).toMatchObject({ score: 7, ok: true });
  });

  it("falls back to the first scoring and shows an empty proof bank as not scored", () => {
    const rows = criticRows({ threshold: 7, before: view(5, null) });
    expect(rows[0]).toMatchObject({ score: 5, ok: false });
    expect(rows[2]).toMatchObject({ score: null, percent: 0, ok: null });
    expect(criticRows(null)).toEqual([]);
  });
});

describe("choosing a hook", () => {
  const script = {
    hook_options: [
      { kind: "pain_question", voiceover: "a" },
      { kind: "result_first", voiceover: "b" },
    ],
    scenes: [
      { id: "s1", type: "hook" },
      { id: "s2", type: "feature_demo" },
    ],
  } as never;

  it("is a plain set op", () => {
    expect(setOpFields("s1", "hook_option", "2").edit?.ops).toEqual([{ op: "set", scene_id: "s1", field: "hook_option", value: "2" }]);
  });

  it("is valid on the hook scene with a known option, not elsewhere", () => {
    const op = (scene_id: string, value: string) => ({ op: "set", scene_id, field: "hook_option", value }) as never;
    expect(validateEditOp(op("s1", "2"), script)).toEqual([]);
    expect(validateEditOp(op("s1", "result_first"), script)).toEqual([]);
    expect(validateEditOp(op("s1", "3"), script)).toHaveLength(1);
    expect(validateEditOp(op("s2", "1"), script)).toHaveLength(1);
  });
});
