// AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.
import { z } from "zod"

export const FocusPlanSchema = z.object({ "plan": z.array(z.object({ "from_ms": z.number().int().gte(0), "to_ms": z.number().int().gte(0), "item_id": z.union([z.string(), z.null()]).default(null), "framing": z.enum(["establish","tight","medium","wide"]), "reason": z.string().default("") }).strict()) }).strict()
export type FocusPlan = z.infer<typeof FocusPlanSchema>

