// AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.
import { z } from "zod"

export const BriefSuggestionsSchema = z.object({ "audience": z.array(z.string()).default([]), "main_benefit": z.array(z.string()).default([]), "offer": z.array(z.string()).default([]) }).strict()
export type BriefSuggestions = z.infer<typeof BriefSuggestionsSchema>

