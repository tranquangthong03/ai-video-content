import type { CriticReport, CriticView } from "./api";

export const CRITERIA = ["hook_strength", "benefit_clarity", "proof_usage", "cta_strength", "flow"] as const;

export const CRITERION_LABEL: Record<string, string> = {
  hook_strength: "Hook",
  benefit_clarity: "Lợi ích rõ ràng",
  proof_usage: "Dùng bằng chứng thật",
  cta_strength: "Kêu gọi hành động",
  flow: "Mạch kể",
};

export const HOOK_KIND_LABEL: Record<string, string> = {
  pain_question: "Câu hỏi nỗi đau",
  result_first: "Kết quả trước",
  shocking_number: "Con số bất ngờ",
  counterintuitive: "Ngược trực giác",
  you_are_doing_it_wrong: "Bạn đang làm sai",
};

export interface CriticRow {
  key: string;
  label: string;
  /** null: not scored (no proof bank) */
  score: number | null;
  reason: string;
  /** width of the bar, 0-100 */
  percent: number;
  ok: boolean | null;
}

/** The scores shown to the user: the last scored version, one row per criterion. */
export function criticRows(report: CriticReport | null | undefined): CriticRow[] {
  const view: CriticView | undefined = report?.final ?? report?.before;
  if (!view) return [];
  return CRITERIA.map((key) => {
    const s = view.scores[key];
    const score = s?.score ?? null;
    return {
      key,
      label: CRITERION_LABEL[key],
      score,
      reason: s?.reason ?? "",
      percent: score === null ? 0 : Math.max(0, Math.min(100, score * 10)),
      ok: score === null ? null : score >= report!.threshold,
    };
  });
}
