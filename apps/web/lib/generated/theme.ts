// AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.
import { z } from "zod"

export const ThemeSchema = z.object({ "primary": z.string().regex(new RegExp("^#[0-9a-fA-F]{6}$")), "accent": z.string().regex(new RegExp("^#[0-9a-fA-F]{6}$")), "font": z.string().min(1), "logo_asset": z.union([z.string(), z.null()]).default(null), "motion_preset": z.enum(["energetic","calm"]), "caption_style": z.enum(["tiktok_bounce","minimal"]), "music_mood": z.enum(["energetic","upbeat","calm","corporate"]), "voice_id": z.string().min(1), "language": z.enum(["vi","en"]) }).strict()
export type Theme = z.infer<typeof ThemeSchema>

