import { describe, expect, it } from "vitest";
import { buildResponse, conceptFields, confirmFields, editFields, setOpFields } from "./responses";
import { demoKindLabel, seconds, splitHighlight, timeAgo } from "./labels";
import { shouldPoll } from "./use-job";
import { SAMPLE_URLS } from "./sample-urls";

const pending = { interaction_id: "int_1", job_id: "j1" };

describe("building responses", () => {
  it("validates with the generated schema and fills the defaults", () => {
    const r = buildResponse(pending, "approve", { base_version: 2 });
    expect(r).toMatchObject({ interaction_id: "int_1", job_id: "j1", action: "approve", base_version: 2 });
    expect(r.edit).toBeNull();
  });

  it("refuses an action the schema does not know", () => {
    // @ts-expect-error not a UserResponse action
    expect(() => buildResponse(pending, "hack")).toThrow();
  });

  it("confirm: unchecked features are excluded, a changed description and notes are sent", () => {
    const fields = confirmFields({
      allFeatureIds: ["a", "b", "c"],
      selected: new Set(["a", "c"]),
      oneLiner: "Mô tả mới",
      originalOneLiner: "Mô tả cũ",
      answers: { oq1: " Nhóm nhỏ ", oq2: "  " },
      notes: "Nhấn mạnh tốc độ",
    });
    const r = buildResponse(pending, "answer", fields);
    expect(r.profile_edit?.exclude_feature_ids).toEqual(["b"]);
    expect(r.profile_edit?.one_liner).toBe("Mô tả mới");
    expect(r.answers).toEqual({ oq1: "Nhóm nhỏ", notes: "Nhấn mạnh tốc độ" });
  });

  it("confirm: an unchanged description is not sent and empty answers are null", () => {
    const r = buildResponse(
      pending,
      "answer",
      confirmFields({
        allFeatureIds: ["a"],
        selected: new Set(["a"]),
        oneLiner: "x",
        originalOneLiner: "x",
        answers: {},
        notes: "",
      }),
    );
    expect(r.profile_edit?.one_liner).toBeNull();
    expect(r.answers).toBeNull();
  });

  it("concept: a duration other than the proposed one becomes a note", () => {
    const same = conceptFields({ conceptId: "c1", durationS: 30, proposedS: 30, notes: "" });
    expect(same.answers).toEqual({ concept_id: "c1", notes: "" });
    const longer = conceptFields({ conceptId: "c1", durationS: 60, proposedS: 30, notes: "Vui vẻ" });
    expect(longer.answers?.notes).toBe("Vui vẻ Đặt thời lượng 60 giây.");
  });

  it("free-text edits and quick `set` ops are valid edit payloads", () => {
    expect(buildResponse(pending, "edit", editFields("  đổi mở đầu ")).edit?.instruction).toBe("đổi mở đầu");
    const op = buildResponse(pending, "edit", setOpFields("s2", "voiceover", "Lời mới")).edit?.ops[0];
    expect(op).toEqual({ op: "set", scene_id: "s2", field: "voiceover", value: "Lời mới" });
  });
});

describe("labels and polling", () => {
  it("names demo kinds in Vietnamese", () => {
    expect(demoKindLabel("interaction")).toBe("Thao tác");
    expect(demoKindLabel("navigation")).toBe("Chuyển trang");
    expect(demoKindLabel("showcase")).toBe("Giới thiệu");
    expect(demoKindLabel("failed")).toBe("Chưa kiểm chứng");
    expect(demoKindLabel(null)).toBe("Chưa kiểm chứng");
  });

  it("splits a headline around its highlight", () => {
    expect(splitHighlight("Quản lý việc nhanh gấp đôi", "nhanh gấp đôi")).toEqual(["Quản lý việc ", "nhanh gấp đôi", ""]);
    expect(splitHighlight("Không có", "xyz")).toEqual(["Không có", "", ""]);
    expect(splitHighlight("Không có", null)).toEqual(["Không có", "", ""]);
  });

  it("formats time", () => {
    expect(seconds(7100)).toBe("7.1s");
    const now = Date.parse("2026-01-01T12:00:00Z");
    expect(timeAgo("2026-01-01T11:58:00Z", now)).toBe("2 phút trước");
    expect(timeAgo("2026-01-01T11:59:59Z", now)).toBe("vừa xong");
  });

  it("polls only while a job runs or queues", () => {
    expect(["running", "queued", undefined].every(shouldPoll)).toBe(true);
    expect(["waiting", "done", "failed", "cancelled"].some(shouldPoll)).toBe(false);
  });

  it("offers todomvc, plausible and squoosh as sample urls", () => {
    expect(SAMPLE_URLS.map((s) => new URL(s.url).hostname)).toEqual(["todomvc.com", "plausible.io", "squoosh.app"]);
  });
});
