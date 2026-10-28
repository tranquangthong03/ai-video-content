import type { MarketingBrief } from "./generated";

/** What the marketing_brief card keeps while the user types (strings only; turned into a MarketingBrief on send). */
export interface BriefForm {
  audience: string;
  mainBenefit: string;
  secondary: string; // one per line or separated by ;
  points: { value: string; unit: string; claim: string }[];
  offer: string;
  ctaText: string;
  ctaUrl: string;
  tone: string;
  avoid: string; // one per line or separated by ;
}

export const MAX_POINTS = 5;

export const emptyForm = (): BriefForm => ({
  audience: "",
  mainBenefit: "",
  secondary: "",
  points: [],
  offer: "",
  ctaText: "",
  ctaUrl: "",
  tone: "",
  avoid: "",
});

const text = (v: string) => v.replace(/\s+/g, " ").trim();
const orNull = (v: string) => text(v) || null;
const list = (v: string) => [...new Set(v.split(/[;\n]/).map(text).filter(Boolean))];

/** A chip was clicked: it fills the field; clicking the one already there clears it. */
export const pickIdea = (current: string, idea: string) => (text(current) === text(idea) ? "" : idea);

export const addPoint = (form: BriefForm): BriefForm =>
  form.points.length >= MAX_POINTS ? form : { ...form, points: [...form.points, { value: "", unit: "", claim: "" }] };

export const removePoint = (form: BriefForm, index: number): BriefForm => ({
  ...form,
  points: form.points.filter((_, i) => i !== index),
});

export const editPoint = (form: BriefForm, index: number, patch: Partial<BriefForm["points"][number]>): BriefForm => ({
  ...form,
  points: form.points.map((p, i) => (i === index ? { ...p, ...patch } : p)),
});

/** A point needs a number and its sentence; a half-filled row is reported, not silently sent. */
export function pointProblems(form: BriefForm): string[] {
  return form.points.flatMap((p, i) => {
    const hasAny = p.value.trim() || p.claim.trim();
    if (!hasAny) return [];
    if (!/\d/.test(p.value)) return [`Số liệu ${i + 1}: cần một con số`];
    if (!p.claim.trim()) return [`Số liệu ${i + 1}: cần câu đầy đủ chứa con số`];
    return [];
  });
}

export function isEmpty(brief: MarketingBrief): boolean {
  return !(
    brief.audience ||
    brief.main_benefit ||
    brief.secondary_benefits.length ||
    brief.proof_points.length ||
    brief.offer ||
    brief.cta_text ||
    brief.cta_url ||
    brief.tone ||
    brief.avoid.length
  );
}

/** The form as a MarketingBrief (empty fields become null / []; rows without a number or a sentence are dropped). */
export function toBrief(form: BriefForm): MarketingBrief {
  return {
    audience: orNull(form.audience),
    main_benefit: orNull(form.mainBenefit),
    secondary_benefits: list(form.secondary),
    proof_points: form.points
      .filter((p) => /\d/.test(p.value) && p.claim.trim())
      .map((p) => ({ value: text(p.value), unit: orNull(p.unit), claim: text(p.claim), source_note: null })),
    offer: orNull(form.offer),
    cta_text: orNull(form.ctaText),
    cta_url: orNull(form.ctaUrl),
    tone: orNull(form.tone),
    avoid: list(form.avoid),
  };
}
