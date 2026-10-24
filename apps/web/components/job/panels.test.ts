import { describe, expect, it } from "vitest";
import type { JobDetail } from "@/lib/api";
import { currentStep, summarize } from "./panels";

const base = (over: Partial<JobDetail["state"]>, pendingKind?: string): JobDetail =>
  ({
    state: { job_id: "j", url: "u", status: "running", step: "explore", progress_text: "", progress_pct: 0, latest_screenshot: null, error: null, created_at: "", updated_at: "", ...over },
    steps: [],
    queue_position: null,
    pending: pendingKind ? ({ kind: pendingKind } as JobDetail["pending"]) : null,
    pending_extra: null,
    history: [],
    video_url: null,
    report: null,
    can_resume: false,
  }) as JobDetail;

describe("job page helpers", () => {
  it("the pending question decides the current step", () => {
    expect(currentStep(base({ status: "waiting" }, "confirm_understanding"))).toBe("confirm");
    expect(currentStep(base({ status: "waiting" }, "choose_concept"))).toBe("concept");
    expect(currentStep(base({ status: "waiting" }, "outline_review"))).toBe("outline");
    expect(currentStep(base({ status: "waiting" }, "clarify"))).toBe("outline");
    expect(currentStep(base({ status: "waiting" }, "script_review"))).toBe("script");
    expect(currentStep(base({ status: "running", step: "produce" }))).toBe("produce");
    expect(currentStep(base({ status: "done", step: "done" }))).toBe("done");
  });

  it("summarizes answered interactions in Vietnamese", () => {
    const h = { kind: "outline_review", interaction_id: "i", action: "edit", answers: null, instruction: "đổi mở đầu" };
    expect(summarize(h)).toBe("Sửa: đổi mở đầu");
    expect(summarize({ ...h, kind: "script_review", action: "approve", instruction: null })).toBe("Đã duyệt");
    expect(summarize({ ...h, kind: "choose_concept", action: "answer", instruction: null, answers: { concept_id: "c1", notes: "Đặt thời lượng 60 giây." } })).toBe(
      "Hướng «c1» · Đặt thời lượng 60 giây.",
    );
  });
});
