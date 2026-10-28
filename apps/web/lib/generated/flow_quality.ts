// AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.
import { z } from "zod"

export const FlowQualitySchema = z.object({ "value_actions": z.number().int().gte(0), "label": z.union([z.string(), z.null()]).default(null), "empty_warning": z.union([z.string(), z.null()]).default(null), "env_warning": z.union([z.string(), z.null()]).default(null), "empty_signals": z.array(z.string()).default([]), "estimated": z.boolean().default(false) }).strict()
export type FlowQuality = z.infer<typeof FlowQualitySchema>

