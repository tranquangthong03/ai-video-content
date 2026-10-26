import { z } from "zod";
import { ScriptSchema } from "./generated";

export const ClickSchema = z.object({
  t_ms: z.number(),
  x: z.number(),
  y: z.number(),
  type: z.enum(["click", "dblclick", "scroll", "highlight", "hover"]).optional(),
});

export const WordSchema = z.object({ text: z.string(), start_ms: z.number(), end_ms: z.number() });

export const CaptionSchema = z.object({
  text: z.string(),
  start_ms: z.number(),
  end_ms: z.number(),
  words: z.array(WordSchema).optional(), // per-word timing, for karaoke highlighting
});

/** One camera target recorded with the clip: a box (clip pixels) to frame and how long to stay on it. */
export const FocusSchema = z.object({
  t_ms: z.number().min(0),
  bbox: z.object({ x: z.number(), y: z.number(), w: z.number().positive(), h: z.number().positive() }),
  kind: z.enum(["click", "dblclick", "hover", "type", "highlight", "section", "scroll"]),
  hold_ms: z.number().min(0).default(0),
});
export type FocusPoint = z.infer<typeof FocusSchema>;

/** One stretch of the focus track the producer worked out: what to look at, how, and for how long. */
export const FocusTrackSchema = z.object({
  t_ms: z.number().min(0),
  bbox: z.object({ x: z.number(), y: z.number(), w: z.number().positive(), h: z.number().positive() }),
  framing: z.enum(["establish", "tight", "medium", "wide"]),
  hold_ms: z.number().min(0).default(0),
  source: z.enum(["plan", "rule", "fallback"]),
  item_id: z.string().nullish(),
  text: z.string().nullish(),
  item_kind: z.string().nullish(),
  region: z.string().nullish(),
  reason: z.string().nullish(),
});
export type FocusTrackEntry = z.infer<typeof FocusTrackSchema>;

/** Per-scene media. URLs are absolute (http/data) or paths relative to the bundle's public dir. */
export const SceneAssetsSchema = z.object({
  audio_url: z.string().optional(),
  clip_url: z.string().optional(),
  start_offset_ms: z.number().min(0).optional(), // trims the loading phase off the clip start
  trim_start_ms: z.number().min(0).optional(), // extra trim after start_offset_ms: cuts the setup part
  playback_rate: z.number().min(1).max(1.5).optional(), // speeds up a clip that is longer than the speech
  freeze_last_frame: z.boolean().optional(), // hold the last frame when the scene outlasts the clip
  clip_duration_ms: z.number().positive().optional(), // length of the clip file (needed to freeze its end)
  screenshot_url: z.string().optional(),
  click_log: z.array(ClickSchema).optional(), // x,y in source clip pixels, t_ms in clip time
  focus_log: z.array(FocusSchema).optional(), // what the camera should look at, clip pixels / clip time
  focus_track: z.array(FocusTrackSchema).optional(), // the producer's final focus plan; wins over focus_log
  // stretches the producer already cut out of clip_url (original clip time); informational only
  segments: z.array(z.object({ from_ms: z.number(), to_ms: z.number() })).optional(),
  // punch-ins at the start of shots (scene time): the frame grows by `scale` within 6 frames
  punches: z.array(z.object({ t_ms: z.number().min(0), scale: z.number().min(0).max(0.3) })).optional(),
  // one shot per spoken phrase and what changed at its start (informational)
  shots: z.array(z.object({ from_ms: z.number(), to_ms: z.number(), change: z.string() })).optional(),
  // before_after / split_frames: two real frames of the flow (first frame, hero frame)
  before_url: z.string().optional(),
  after_url: z.string().optional(),
  cta_domain: z.string().optional(), // short domain shown under the CTA button
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
