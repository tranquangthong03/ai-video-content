// AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.
import { z } from "zod"

export const OutlineSchema = z.object({ "concept_id": z.string(), "title": z.string().min(1), "goal": z.enum(["awareness","conversion","tutorial","recruitment"]), "duration_s": z.union([z.literal(30), z.literal(45), z.literal(60)]), "feature_ids": z.array(z.string()), "version": z.number().int().gte(1).default(1), "beats": z.array(z.object({ "id": z.string().regex(new RegExp("^b[0-9]+$")), "text": z.string().min(1), "feature_id": z.union([z.string(), z.null()]).default(null) }).strict()).min(1) }).strict()
export type Outline = z.infer<typeof OutlineSchema>

