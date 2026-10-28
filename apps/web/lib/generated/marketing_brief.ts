// AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.
import { z } from "zod"

export const MarketingBriefSchema = z.object({ "audience": z.union([z.string(), z.null()]).default(null), "main_benefit": z.union([z.string(), z.null()]).default(null), "secondary_benefits": z.array(z.string()).default([]), "proof_points": z.array(z.object({ "value": z.string(), "unit": z.union([z.string(), z.null()]).default(null), "claim": z.string(), "source_note": z.union([z.string(), z.null()]).default(null) }).strict()).default([]), "offer": z.union([z.string(), z.null()]).default(null), "cta_text": z.union([z.string(), z.null()]).default(null), "cta_url": z.union([z.string(), z.null()]).default(null), "tone": z.union([z.string(), z.null()]).default(null), "avoid": z.array(z.string()).default([]) }).strict()
export type MarketingBrief = z.infer<typeof MarketingBriefSchema>

