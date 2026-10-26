import type { ScoreLine, Scorecard } from "./api";

export const STATUS_TEXT: Record<ScoreLine["status"], string> = {
  pass: "Đạt",
  fail: "Không đạt",
  na: "Chưa đánh giá",
  info: "Thông tin",
};

/** One-line verdict shown above the table. */
export function scoreVerdict(card: Scorecard): string {
  if (card.total === 0) return "Chưa có tiêu chí nào để chấm";
  if (card.all_passed) return `Đạt cả ${card.total} tiêu chí`;
  return `Đạt ${card.passed}/${card.total} tiêu chí, ${card.failed} chưa đạt`;
}

/** The lines that did not pass, worst first (the ones the user should look at). */
export function failedLines(card: Scorecard): ScoreLine[] {
  return card.lines.filter((l) => l.status === "fail");
}
