// AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.
import { z } from "zod"

export const VideoConceptSchema = z.object({ "id": z.string().min(1), "angle": z.enum(["overview","deep_dive","pain_solution"]), "title": z.string().min(1), "goal": z.enum(["awareness","conversion","tutorial","recruitment"]), "hook_example": z.string(), "feature_ids": z.array(z.string()), "beats": z.array(z.string()).min(4).max(6), "duration_s": z.union([z.literal(30), z.literal(45), z.literal(60)]), "why": z.string(), "recommended": z.boolean() }).strict()
export type VideoConcept = z.infer<typeof VideoConceptSchema>

