// AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.
import { z } from "zod"

export const BrowserActionSchema = z.object({ "do": z.enum(["goto","click","type","scroll","wait","hover"]), "target": z.union([z.string(), z.null()]).default(null), "selector": z.union([z.string(), z.null()]).default(null), "url": z.union([z.string(), z.null()]).default(null), "text": z.union([z.string(), z.null()]).default(null), "ms": z.union([z.number().int().gte(0), z.null()]).default(null), "zoom": z.boolean().default(false) }).strict()
export type BrowserAction = z.infer<typeof BrowserActionSchema>

