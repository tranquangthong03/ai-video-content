/** Core flow cards (select_flow, flow_storyboard_review): pure helpers, tested in flows.test.ts. */
import type { CoreFlow, FlowQuality, FlowRun } from "./generated";
import { toggleSelection } from "./selection";

export const MAX_FLOWS = 2;

/** Two short examples under the box where the user describes a flow of their own. */
export const FLOW_EXAMPLES = [
  "Nhân viên tạo hồ sơ nhân viên mới và lưu",
  "Người dùng tải ảnh lên, nén và so sánh trước/sau",
];

/** What the card says about a flow: how many steps make something appear, and the warning when too few. */
export function qualityLine(q: FlowQuality | undefined): { text: string; warn: string | null } | null {
  if (!q) return null;
  const n = q.value_actions;
  return {
    text: `${q.estimated ? "~" : ""}${n} thao tác tạo kết quả`,
    warn: q.label ?? null,
  };
}

type Step = FlowRun["steps"][number];

/** Adds or removes a flow id (the first picked is the main flow); never more than `max`. */
export const toggleFlow = (order: string[], id: string, max = MAX_FLOWS, infeasible: Record<string, string> = {}): string[] =>
  id in infeasible ? order : toggleSelection(order, id, max);

export const FLOW_STATUS_LABEL: Record<FlowRun["status"], string> = {
  reached_goal: "Đạt mục tiêu",
  stopped_before_submit: "Dừng trước khi gửi",
  partial: "Chưa trọn luồng",
  failed: "Không thực hiện được",
};

/** The label comes from the code-verified goal when there is one: the model never says "reached". */
export function flowStatusLabel(run: FlowRun): string {
  if (run.goal_status === "not_reached") return "Chưa đạt mục tiêu";
  if (run.goal_status === "stopped_before_submit") return "Dừng trước khi gửi";
  return FLOW_STATUS_LABEL[run.status];
}

export function flowStatusTone(status: FlowRun["status"]): "success" | "default" | "warning" {
  if (status === "reached_goal") return "success";
  if (status === "stopped_before_submit") return "default";
  return "warning";
}

/** A run with no step to film (or a failed one) cannot be approved. */
export const canApprove = (run: FlowRun): boolean => run.status !== "failed" && run.steps.length >= 2;

export interface ChapterGroup {
  id: string;
  title: string;
  steps: Step[];
}

/** Steps grouped under their chapter, in order; steps without a chapter go to a last "Khác" group. */
export function groupByChapter(run: FlowRun): ChapterGroup[] {
  const groups: ChapterGroup[] = run.chapters.map((c) => ({ id: c.id, title: c.title, steps: [] }));
  const other: ChapterGroup = { id: "", title: "Khác", steps: [] };
  for (const step of run.steps) {
    const group = groups.find((g) => g.id === step.chapter_id);
    (group ?? other).steps.push(step);
  }
  return other.steps.length ? [...groups.filter((g) => g.steps.length), other] : groups.filter((g) => g.steps.length);
}

/** A one-line description of a step for the grid ("Chọn «Leave Type» = Annual"). */
export function stepLine(step: Step): string {
  if (step.note.trim()) return step.note.trim();
  const target = step.target_text ? `«${step.target_text}»` : "";
  return [step.action.do, target, step.value ?? ""].filter(Boolean).join(" ");
}

export interface SubmitOffer {
  /** the switch is shown: at least one chosen flow needs to send data */
  offered: boolean;
  /** why it cannot be turned on (shared demo site), else null */
  blocked: string | null;
}

export function submitOffer(flows: CoreFlow[], selected: string[], blockedReason: string | null | undefined): SubmitOffer {
  const needs = flows.some((f) => selected.includes(f.id) && f.needs_submit);
  return { offered: needs, blocked: blockedReason ?? null };
}

/** select_flow → "answer". Submit is sent only when switched on AND confirmed AND not blocked. */
export function flowAnswers(opts: {
  selected: string[];
  description: string;
  allowSubmit: boolean;
  confirmed: boolean;
  blocked?: string | null;
}): Record<string, string | string[]> {
  const answers: Record<string, string | string[]> = { selected_flows: opts.selected };
  const description = opts.description.trim();
  if (description) answers.flow_description = description;
  if (opts.allowSubmit && opts.confirmed && !opts.blocked) {
    answers.allow_submit = "true";
    answers.submit_confirmed = "true";
  }
  return answers;
}

/** Shown when the flow gives nothing to suggest from. */
export const EDIT_PLACEHOLDER = "Ví dụ: bỏ một bước, thêm một bước, hoặc nói rõ bạn muốn làm lại luồng khác";

const POINTING = ["hover", "highlight", "goto", "scroll"];
const words = (text: string): string[] => text.toLowerCase().split(/[^\p{L}\p{N}]+/u).filter((w) => w.length >= 4);

/**
 * Up to three sentences to change THIS storyboard (no model call): add an expected step the run
 * never touched, drop the last real step, stop before the action the user asked for.
 */
export function editSuggestions(run: FlowRun, flow?: CoreFlow): string[] {
  const out: string[] = [];
  const used = new Set(run.steps.flatMap((s) => words(`${s.target_text ?? ""} ${s.value ?? ""} ${s.note}`)));
  const unused = flow?.expected_steps.find((e) => words(e).length > 0 && !words(e).some((w) => used.has(w)));
  if (unused) out.push(`Thêm bước: ${unused}`);
  const real = run.steps.filter((s) => !POINTING.includes(s.action.do) && !s.blank && !s.no_effect);
  const last = real[real.length - 1];
  if (last && real.length > 1) out.push(`Bỏ bước ${last.i}${last.target_text ? ` (${last.target_text})` : ""}`);
  const action = flow?.required_actions?.[0];
  if (action && run.goal_status !== "stopped_before_submit") out.push(`Dừng trước khi ${action}`);
  return out.slice(0, 3);
}
