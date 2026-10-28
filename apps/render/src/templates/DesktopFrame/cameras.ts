import { buildShotPath, type CameraPath } from "../../camera";
import type { Script } from "../../generated";
import type { InputProps } from "../../props";
import { FPS, sceneRanges } from "../../timing";
import { clipPlayback } from "../DesktopShowcase/playback";
import { MEDIA } from "./layout";

export const MEDIA_FRAME = { w: MEDIA.w, h: MEDIA.h };

/** Frames over which one scene fades into the next (when the cameras are at rest). */
export const FRAME_CROSSFADE_FRAMES = 10;
/** The camera must be at rest this long around a crossfade. */
const REST_MS = 120;

/** The shot camera of every recorded scene (the renderer, the metrics scripts and the preview all use this). */
export function frameCamerasOf(script: Script, assets: InputProps["assets"]): Record<string, CameraPath> {
  const out: Record<string, CameraPath> = {};
  for (const r of sceneRanges(script, FPS)) {
    const a = assets[r.scene.id];
    if (!a?.clip_url) continue;
    const { startMs, rate } = clipPlayback(a, FPS, r.frames);
    const clip = { w: a.clip_width ?? 1280, h: a.clip_height ?? 720 };
    out[r.scene.id] = buildShotPath(a.zoom_shots ?? [], clip, MEDIA_FRAME, startMs + ((r.frames - 1) / FPS) * 1000 * rate);
  }
  return out;
}

export type Boundary = { index: number; frame: number; crossfade: boolean; moving: boolean };

/**
 * How scene i hands over to scene i+1: a crossfade only when both cameras stand still on the full
 * view around the hand-over (two pictures blended while one of them zooms is a ghost); else a hard cut.
 */
export function boundariesOf(script: Script, assets: InputProps["assets"], cameras: Record<string, CameraPath>): Boundary[] {
  const ranges = sceneRanges(script, FPS);
  const overlapMs = (FRAME_CROSSFADE_FRAMES / FPS) * 1000;
  const calm = (id: string, from: number, to: number) => {
    const cam = cameras[id];
    if (!cam) return true; // a card or a screenshot: no camera
    for (let t = from; t <= to; t += 33) if (cam.moving(t) || cam.at(t).zoom > 1.001) return false;
    return true;
  };
  const out: Boundary[] = [];
  for (let i = 0; i < ranges.length - 1; i++) {
    const a = ranges[i];
    const b = ranges[i + 1];
    const pa = assets[a.scene.id];
    const pb = assets[b.scene.id];
    const endA = pa?.clip_url ? clipPlayback(pa, FPS, a.frames) : null;
    const startB = pb?.clip_url ? clipPlayback(pb, FPS, b.frames) : null;
    // scene i runs on for the overlap (its clock goes past its end), scene i+1 plays its first frames
    const tEnd = endA ? endA.startMs + ((a.frames - 1) / FPS) * 1000 * endA.rate : 0;
    const tStart = startB ? startB.startMs : 0;
    const restA = calm(a.scene.id, tEnd - overlapMs - REST_MS, tEnd + overlapMs);
    const restB = calm(b.scene.id, tStart, tStart + overlapMs + REST_MS);
    const crossfade = restA && restB;
    const moving = !crossfade && (!restA || !restB);
    out.push({ index: i, frame: b.from, crossfade, moving });
  }
  return out;
}
