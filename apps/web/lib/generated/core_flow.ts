// AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.
import { z } from "zod"

export const CoreFlowSchema = z.object({ "id": z.string().min(1), "title": z.string().min(1), "persona": z.string(), "goal": z.string(), "start_url": z.string(), "expected_steps": z.array(z.string()).min(1).max(12), "success_signal": z.string(), "needs_submit": z.boolean(), "value": z.string(), "related_feature_ids": z.array(z.string()).default([]), "required_actions": z.array(z.string()).max(4).default([]), "source": z.enum(["proposed","user"]).default("proposed"), "confidence": z.number().gte(0).lte(1).default(0.7), "notes": z.union([z.string(), z.null()]).default(null) }).strict()
export type CoreFlow = z.infer<typeof CoreFlowSchema>

