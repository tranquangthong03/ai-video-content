import { z } from "zod";
import { ScriptSchema } from "./generated";

export const ClickSchema = z.object({
  t_ms: z.number(),
  x: z.number(),
  y: z.number(),
  type: z.enum(["click", "dblclick", "scroll", "highlight"]).optional(),
});

export const WordSchema = z.object({ text: z.string(), start_ms: z.number(), end_ms: z.number() });

export const CaptionSchema = z.object({
  text: z.string(),
  start_ms: z.number(),
  end_ms: z.number(),
  words: z.array(WordSchema).optional(), // per-word timing, for karaoke highlighting
});

/** Per-scene media. URLs are absolute (http/data) or paths relative to the bundle's public dir. */
export const SceneAssetsSchema = z.object({
  audio_url: z.string().optional(),
  clip_url: z.string().optional(),
  start_offset_ms: z.number().min(0).optional(), // trims the loading phase off the clip start
  screenshot_url: z.string().optional(),
  click_log: z.array(ClickSchema).optional(), // x,y in source clip pixels, t_ms in clip time
  clip_width: z.number().positive().optional(),
  clip_height: z.number().positive().optional(),
  captions: z.array(CaptionSchema).optional(),
});

export const InputPropsSchema = z.object({
  script: ScriptSchema,
  assets: z.record(z.string(), SceneAssetsSchema).default({}),
  music_url: z.string().optional(),
});

export type Click = z.infer<typeof ClickSchema>;
export type Caption = z.infer<typeof CaptionSchema>;
export type SceneAssets = z.infer<typeof SceneAssetsSchema>;
export type InputProps = z.infer<typeof InputPropsSchema>;
/** What callers may send (defaults not yet applied). */
export type InputPropsInput = z.input<typeof InputPropsSchema>;
