// AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.
import { z } from "zod"

export const BeatOpSchema = z.discriminatedUnion("op", [z.object({ "op": z.literal("set"), "beat_id": z.string(), "text": z.string().min(1), "feature_id": z.union([z.string(), z.null()]).default(null) }).strict(), z.object({ "op": z.literal("delete"), "beat_id": z.string() }).strict(), z.object({ "op": z.literal("insert"), "after_beat_id": z.union([z.string(), z.null()]), "text": z.string().min(1), "feature_id": z.union([z.string(), z.null()]).default(null) }).strict(), z.object({ "op": z.literal("move"), "beat_id": z.string(), "after_beat_id": z.union([z.string(), z.null()]) }).strict(), z.object({ "op": z.literal("set_meta"), "field": z.enum(["title","goal","duration_s"]), "value": z.union([z.string(), z.number()]) }).strict()])
export type BeatOp = z.infer<typeof BeatOpSchema>

