import type { Scene, Script } from "./generated";
import type { Caption } from "./props";

export const FPS = 30;
export const WIDTH = 1080;
export const HEIGHT = 1920;

const WORDS_PER_SECOND = 2.5;
const MIN_SCENE_MS = 2000;
const CAPTION_WORDS = 3;

const words = (text: string) => text.trim().split(/\s+/).filter(Boolean);

/** duration_ms when known (after TTS), otherwise estimated from the voiceover length. */
export function sceneDurationMs(scene: Pick<Scene, "duration_ms" | "voiceover">): number {
  if (scene.duration_ms != null) return scene.duration_ms;
  const estimate = Math.round((words(scene.voiceover).length / WORDS_PER_SECOND) * 1000);
  return Math.max(MIN_SCENE_MS, estimate);
}

export const msToFrames = (ms: number, fps = FPS) => Math.max(1, Math.round((ms / 1000) * fps));

export const sceneFrames = (scene: Pick<Scene, "duration_ms" | "voiceover">, fps = FPS) =>
  msToFrames(sceneDurationMs(scene), fps);

export function totalFrames(script: Pick<Script, "scenes">, fps = FPS): number {
  return script.scenes.reduce((sum, s) => sum + sceneFrames(s, fps), 0);
}

/** Frame range [from, to) of every scene on the composition timeline. */
export function sceneRanges(script: Pick<Script, "scenes">, fps = FPS) {
  let from = 0;
  return script.scenes.map((scene) => {
    const frames = sceneFrames(scene, fps);
    const range = { scene, from, to: from + frames, frames };
    from += frames;
    return range;
  });
}

/** Fallback captions (no TTS word timestamps yet): even split of the voiceover over the scene. */
export function captionsFromVoiceover(voiceover: string, durationMs: number): Caption[] {
  const all = words(voiceover);
  if (all.length === 0) return [];
  const chunks: string[][] = [];
  for (let i = 0; i < all.length; i += CAPTION_WORDS) chunks.push(all.slice(i, i + CAPTION_WORDS));
  const step = durationMs / all.length;
  let cursor = 0;
  return chunks.map((chunk) => {
    const start = cursor;
    cursor += step * chunk.length;
    return { text: chunk.join(" "), start_ms: Math.round(start), end_ms: Math.round(cursor) };
  });
}

/** Music volume: low while a voiceover plays, with short ramps to avoid pumping. */
export function musicVolume(
  frame: number,
  voiceRanges: { from: number; to: number }[],
  { normal = 0.15, ducked = 0.06, ramp = 8 } = {},
): number {
  let duck = 0;
  for (const r of voiceRanges) {
    const inside = Math.min(1, Math.max(0, (frame - r.from) / ramp)) *
      Math.min(1, Math.max(0, (r.to - frame) / ramp));
    duck = Math.max(duck, inside);
  }
  return normal + (ducked - normal) * duck;
}
