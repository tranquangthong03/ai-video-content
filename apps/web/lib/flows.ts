/** Core flow cards (select_flow, flow_storyboard_review): pure helpers, tested in flows.test.ts. */
import type { CoreFlow, FlowRun } from "./generated";
import { toggleSelection } from "./selection";

export const MAX_FLOWS = 2;

type Step = FlowRun["steps"][number];

/** Adds or removes a flow id (the first picked is the main flow); never more than `max`. */
export const toggleFlow = (order: string[], id: string, max = MAX_FLOWS): string[] => toggleSelection(order, id, max);

export const FLOW_STATUS_LABEL: Record<FlowRun["status"], string> = {
  reached_goal: "Đạt mục tiêu",
  stopped_before_submit: "Dừng trước khi gửi",
  partial: "Chưa trọn luồng",
  failed: "Không thực hiện được",
};

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

/** The buttons under the storyboard that fill the edit box with an example sentence. */
export const EDIT_EXAMPLES = ["Bỏ bước 3", "Chọn loại nghỉ Annual thay vì Personal", "Thêm bước xem My Leave"];
