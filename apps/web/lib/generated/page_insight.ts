// AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.
import { z } from "zod"

export const PageInsightSchema = z.object({ "url": z.string().default(""), "title": z.string().default(""), "page_type": z.enum(["landing_hero","landing_features","pricing","app_dashboard","app_list","app_editor","app_detail","app_settings","product_listing","product_detail","docs","other"]), "purpose": z.string(), "actions": z.array(z.object({ "ref": z.string(), "name": z.string(), "intent": z.enum(["create","edit","filter","search","export","share","view","navigate_feature","other"]) }).strict()).default([]), "claimed_features": z.array(z.object({ "name": z.string(), "quote": z.string() }).strict()).default([]), "visual_quality": z.number().gte(0).lte(1) }).strict()
export type PageInsight = z.infer<typeof PageInsightSchema>

