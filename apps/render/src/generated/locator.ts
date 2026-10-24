// AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.
import { z } from "zod"

export const LocatorSpecSchema = z.object({ "role": z.union([z.string(), z.null()]).default(null), "name": z.union([z.string(), z.null()]).default(null), "text": z.union([z.string(), z.null()]).default(null), "css": z.union([z.string(), z.null()]).default(null), "nth": z.union([z.number().int().gte(0), z.null()]).default(null), "tag": z.union([z.string(), z.null()]).default(null), "fingerprint": z.union([z.string(), z.null()]).default(null), "bbox": z.union([z.object({ "x": z.number(), "y": z.number(), "w": z.number(), "h": z.number() }).strict(), z.null()]).default(null) }).strict()
export type LocatorSpec = z.infer<typeof LocatorSpecSchema>

