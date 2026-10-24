import { CROSSFADE_FRAMES } from "./layout";

type ClipTiming = {
  start_offset_ms?: number;
  trim_start_ms?: number;
  playback_rate?: number;
  freeze_last_frame?: boolean;
  clip_duration_ms?: number;
};

/**
 * How a scene plays its clip. `startMs` is where in the clip playback begins (loading phase and setup
 * trimmed off), `rate` the playback speed. `lastFrame` is the scene frame from which the video holds
 * its last frame, or null when it never needs to: set when the clip's end is known and either the scene
 * asks for freeze_last_frame or it runs into the crossfade overrun after its nominal end.
 */
export function clipPlayback(a: ClipTiming, fps: number, sceneFrames: number) {
  const startMs = (a.start_offset_ms ?? 0) + (a.trim_start_ms ?? 0);
  const rate = a.playback_rate ?? 1;
  let lastFrame: number | null = null;
  if (a.clip_duration_ms !== undefined) {
    const playable = Math.max(1, Math.floor(((a.clip_duration_ms - startMs) / 1000) * (fps / rate)));
    const overruns = playable < sceneFrames + CROSSFADE_FRAMES;
    if (a.freeze_last_frame || overruns) lastFrame = Math.max(0, playable - 1);
  }
  return { startMs, rate, lastFrame };
}
