import { describe, expect, it } from "vitest";
import { failedLines, scoreVerdict } from "./scorecard";
import type { Scorecard } from "./api";

const line = (id: string, status: "pass" | "fail" | "na" | "info") => ({ id, label: id, target: "", value: null, status, note: "" });

describe("scorecard", () => {
  it("says how many criteria passed", () => {
    const card: Scorecard = { lines: [line("a", "pass"), line("b", "fail"), line("c", "info")], passed: 1, failed: 1, total: 2, all_passed: false };
    expect(scoreVerdict(card)).toBe("Đạt 1/2 tiêu chí, 1 chưa đạt");
    expect(failedLines(card).map((l) => l.id)).toEqual(["b"]);
    expect(scoreVerdict({ ...card, failed: 0, passed: 2, all_passed: true })).toBe("Đạt cả 2 tiêu chí");
    expect(scoreVerdict({ lines: [], passed: 0, failed: 0, total: 0, all_passed: false })).toBe("Chưa có tiêu chí nào để chấm");
  });
});
