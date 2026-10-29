import { describe, expect, it } from "vitest";
import type { CoreFlow, FlowRun } from "./generated";
import { FlowRunSchema, CoreFlowSchema } from "./generated";
import { buildResponse } from "./responses";
import { EDIT_PLACEHOLDER, FLOW_EXAMPLES, canApprove, editSuggestions, flowAnswers, groupByChapter, qualityLine, stepLine, submitOffer, toggleFlow } from "./flows";

const flow = (id: string, needsSubmit: boolean): CoreFlow =>
  CoreFlowSchema.parse({
    id, title: id, persona: "p", goal: "g", start_url: "https://x.test/", expected_steps: ["a"],
    success_signal: "s", needs_submit: needsSubmit, value: "v",
  });

const run = (over: Partial<FlowRun> = {}): FlowRun =>
  FlowRunSchema.parse({
    flow_id: "f", status: "stopped_before_submit",
    steps: [
      { i: 1, action: { do: "goto" }, note: "Mở trang", chapter_id: "c1" },
      { i: 2, action: { do: "select" }, target_text: "Leave Type", value: "Annual", chapter_id: "c1" },
      { i: 3, action: { do: "type" }, note: "Ghi lý do", chapter_id: "c2" },
      { i: 4, action: { do: "highlight" }, note: "", chapter_id: null },
    ],
    chapters: [
      { id: "c1", title: "Mở form", step_ids: [1, 2] },
      { id: "c2", title: "Điền", step_ids: [3] },
    ],
    ...over,
  });

describe("flow choice", () => {
  it("keeps the order, allows at most two and removes on a second click", () => {
    expect(toggleFlow(["a"], "b")).toEqual(["a", "b"]);
    expect(toggleFlow(["a", "b"], "c")).toEqual(["a", "b"]);
    expect(toggleFlow(["a", "b"], "a")).toEqual(["b"]);
  });

  it("never selects a flow that cannot be done on this account", () => {
    const cannot = { a: "No Leave Types with Leave Balance" };
    expect(toggleFlow([], "a", 2, cannot)).toEqual([]);
    expect(toggleFlow([], "b", 2, cannot)).toEqual(["b"]);
    expect(toggleFlow(["b"], "b", 2, cannot)).toEqual([]);
  });

  it("offers the submit switch only when a chosen flow needs it, and carries the shared-demo reason", () => {
    const flows = [flow("a", false), flow("b", true)];
    expect(submitOffer(flows, ["a"], null)).toEqual({ offered: false, blocked: null });
    expect(submitOffer(flows, ["a", "b"], "Site dùng chung")).toEqual({ offered: true, blocked: "Site dùng chung" });
  });

  it("sends the submit answers only when switched on, confirmed and not blocked", () => {
    const base = { selected: ["a"], description: "  xin nghỉ  " };
    expect(flowAnswers({ ...base, allowSubmit: true, confirmed: true })).toEqual({
      selected_flows: ["a"], flow_description: "xin nghỉ", allow_submit: "true", submit_confirmed: "true",
    });
    expect(flowAnswers({ ...base, allowSubmit: true, confirmed: false })).not.toHaveProperty("allow_submit");
    expect(flowAnswers({ ...base, allowSubmit: false, confirmed: true })).not.toHaveProperty("allow_submit");
    expect(flowAnswers({ ...base, allowSubmit: true, confirmed: true, blocked: "x" })).not.toHaveProperty("allow_submit");
    expect(flowAnswers({ selected: ["a"], description: " ", allowSubmit: false, confirmed: false })).toEqual({ selected_flows: ["a"] });
  });

  it("builds a response the generated schema accepts", () => {
    const pending = { interaction_id: "i", job_id: "j" };
    const r = buildResponse(pending, "answer", { answers: flowAnswers({ selected: ["a"], description: "", allowSubmit: false, confirmed: false }) });
    expect(r.answers).toEqual({ selected_flows: ["a"] });
  });
});

describe("storyboard", () => {
  it("groups steps under their chapter and puts the rest last", () => {
    const groups = groupByChapter(run());
    expect(groups.map((g) => [g.title, g.steps.map((s) => s.i)])).toEqual([
      ["Mở form", [1, 2]], ["Điền", [3]], ["Khác", [4]],
    ]);
  });

  it("describes a step by its note, else by what it did", () => {
    const r = run();
    expect(stepLine(r.steps[0])).toBe("Mở trang");
    expect(stepLine(r.steps[1])).toBe("select «Leave Type» Annual");
  });

  it("refuses to approve a failed or empty run", () => {
    expect(canApprove(run())).toBe(true);
    expect(canApprove(run({ status: "failed" }))).toBe(false);
    expect(canApprove(run({ steps: run().steps.slice(0, 1) }))).toBe(false);
  });
});

describe("what the select_flow card says about a flow", () => {
  it("shows the value actions, and the warning only when they are too few", () => {
    expect(qualityLine(undefined)).toBeNull();
    expect(qualityLine({ value_actions: 4, label: null, empty_warning: null, env_warning: null, empty_signals: [], estimated: true })).toEqual({ text: "~4 thao tác tạo kết quả", warn: null });
    expect(qualityLine({ value_actions: 0, label: "Chỉ điều hướng — video sẽ ít hấp dẫn", empty_warning: null, env_warning: null, empty_signals: [], estimated: false })).toEqual({
      text: "0 thao tác tạo kết quả",
      warn: "Chỉ điều hướng — video sẽ ít hấp dẫn",
    });
  });

  it("offers two short examples for describing a flow", () => {
    expect(FLOW_EXAMPLES).toHaveLength(2);
    expect(FLOW_EXAMPLES.every((e) => e.length < 60)).toBe(true);
  });
});

describe("editSuggestions", () => {
  const f = CoreFlowSchema.parse({
    id: "f", title: "t", persona: "p", goal: "g", start_url: "https://x.test/",
    expected_steps: ["Mở trang", "Xem báo cáo tuần"], success_signal: "s", needs_submit: false, value: "v",
    required_actions: ["them vao gio"],
  });

  it("is made from this flow: an unused expected step, the last real step, the user's action", () => {
    const r = run({ goal_status: "not_reached" });
    const out = editSuggestions(r, f);
    expect(out).toContain("Thêm bước: Xem báo cáo tuần");
    expect(out.some((s) => s.startsWith("Bỏ bước 3"))).toBe(true);
    expect(out).toContain("Dừng trước khi them vao gio");
    expect(out.length).toBeLessThanOrEqual(3);
  });

  it("does not suggest stopping when the run already stopped, and has nothing without data", () => {
    expect(editSuggestions(run({ goal_status: "stopped_before_submit" }), f)).not.toContain("Dừng trước khi them vao gio");
    expect(editSuggestions(run({ steps: [] }))).toEqual([]);
  });

  it("carries no example from a particular site", () => {
    const text = JSON.stringify([EDIT_PLACEHOLDER, editSuggestions(run(), f)]);
    expect(text).not.toMatch(/Annual|My Leave|Personal/);
  });
});
