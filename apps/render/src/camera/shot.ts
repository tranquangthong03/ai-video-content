/**
 * The shot camera of the desktop_frame template ("Action Zoom"): the whole page, standing perfectly
 * still, except that EVERY action the browser performs gets a zoom on its element and label (planned by
 * the producer: producer/action_zoom.py). A shot that follows another one closely and nearby is chained:
 * the camera pans straight over instead of zooming out and in again.
 *
 *  - default = the FULL view: the clip fitted whole into the 16:9 frame (a clip of another aspect is
 *    contained, the bars are filled by the blurred backdrop). No drift, no punch-ins, no following
 *  - a zoom is a ZoomShot: move in (ease-in-out), hold perfectly still, move out to the full view
 *  - the zoomed window always holds the shot's whole box (the UI block with its padding): the level
 *    is lowered to what the block needs, and the producer drops the shot when that is below 1.3x
 *
 * Pure functions of clip time, like the other cameras: the same shots always give the same path.
 */
import type { Size } from "../geometry";
import { lerpView, type ClipBox, type FocusCamera, type View } from "./focus";
import { keepBox, smoothstep, type CameraPath, type Move } from "./path";

export type ZoomShot = {
  in_start_ms: number;
  in_end_ms: number;
  out_start_ms: number;
  out_end_ms: number;
  /** the UI block to hold whole, padded (clip pixels) */
  box: ClipBox;
  /** wanted zoom, 1.0 = the full view */
  zoom: number;
  /** this shot starts from the view of the previous one (a pan), which then does not zoom out */
  chain_prev?: boolean;
  /** short caption of the action (shown while the shot is held) */
  label?: string | null;
};

export const SHOT_CONFIG = { minLevel: 1.6, maxLevel: 2.6, share: 0.55, padding: 0.25, leadMs: 400, moveMs: 500, holdMs: 1200, nearMs: 1500 };

/** The whole clip in the frame (contain); wider/taller than the clip when the aspects differ. */
export function fullView(clip: Size, frame: Size): View {
  const w = Math.max(clip.w, (clip.h * frame.w) / frame.h);
  const h = (w * frame.h) / frame.w;
  return { x: (clip.w - w) / 2, y: (clip.h - h) / 2, w, h };
}

/** Largest zoom (full view = 1) at which a window still holds `box` whole. */
export function fitZoom(box: ClipBox, clip: Size, frame: Size): number {
  const full = fullView(clip, frame);
  const r = frame.h / frame.w;
  return Math.min(full.w / box.w, (full.w * r) / box.h);
}

/** The window of a shot: centred on its box, no smaller than the box needs, inside the clip. */
export function shotView(shot: ZoomShot, clip: Size, frame: Size): View {
  const full = fullView(clip, frame);
  const zoom = Math.max(1, Math.min(shot.zoom, fitZoom(shot.box, clip, frame)));
  const w = full.w / zoom;
  const h = (w * frame.h) / frame.w;
  const cx = shot.box.x + shot.box.w / 2;
  const cy = shot.box.y + shot.box.h / 2;
  // a window larger than the clip is centred (it is then the full view or close to it)
  const v: View = {
    x: w >= clip.w ? (clip.w - w) / 2 : Math.min(Math.max(cx - w / 2, 0), clip.w - w),
    y: h >= clip.h ? (clip.h - h) / 2 : Math.min(Math.max(cy - h / 2, 0), clip.h - h),
    w,
    h,
  };
  return keepBox(v, shot.box, clip);
}

type Seg = { t0: number; t1: number; from: View; to: View };

export function buildShotPath(shots: ZoomShot[], clip: Size, frame: Size, endMs?: number): CameraPath {
  const full = fullView(clip, frame);
  const ordered = [...shots].sort((a, b) => a.in_start_ms - b.in_start_ms);
  const views = ordered.map((s) => shotView(s, clip, frame));
  const segs: Seg[] = [];
  const moves: Move[] = [];
  const holds: { t0: number; t1: number; view: View }[] = [];
  ordered.forEach((s, k) => {
    const view = views[k];
    const next = ordered[k + 1];
    const from = s.chain_prev && k > 0 ? views[k - 1] : full;
    segs.push({ t0: s.in_start_ms, t1: s.in_end_ms, from, to: view });
    moves.push({ start: s.in_start_ms, duration: s.in_end_ms - s.in_start_ms, from, to: view, target: s.in_end_ms });
    if (next?.chain_prev) {
      holds.push({ t0: s.in_end_ms, t1: next.in_start_ms, view }); // the next shot pans on from here
      return;
    }
    holds.push({ t0: s.in_end_ms, t1: s.out_start_ms, view });
    segs.push({ t0: s.out_start_ms, t1: s.out_end_ms, from: view, to: full });
    moves.push({ start: s.out_start_ms, duration: s.out_end_ms - s.out_start_ms, from: view, to: full, target: s.out_end_ms });
  });
  const finish = (view: View): FocusCamera => {
    const outside = view.w > clip.w + 0.5 || view.h > clip.h + 0.5; // bars to fill: the backdrop shows
    return { view, zoom: full.w / view.w, establishing: outside ? 1 : 0 };
  };
  const at = (tMs: number): FocusCamera => {
    for (const h of holds) if (tMs >= h.t0 && tMs <= h.t1) return finish(h.view);
    const seg = segs.find((x) => tMs > x.t0 && tMs < x.t1);
    if (!seg) return finish(full);
    const u = smoothstep((tMs - seg.t0) / (seg.t1 - seg.t0));
    return finish(lerpView(seg.from, seg.to, u));
  };
  const moving = (tMs: number) => segs.some((s) => tMs > s.t0 && tMs < s.t1);
  return { at, moving, endView: () => at(endMs ?? Infinity).view, moves };
}

/** Frames (ms) between which the camera is away from the full view: shots plus their moves. */
export const zoomedSpans = (shots: ZoomShot[]) =>
  shots.map((s) => ({ from: s.in_start_ms, to: s.out_end_ms }));
