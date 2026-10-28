/**
 * The planned camera path of one clip.
 *
 * The old camera reacted to each focus point with a spring, so every new target was a snap
 * (zoom 10-17 % in ONE frame) between stretches where nothing moved. This one plans the whole
 * clip first, then answers "where is the camera at time t":
 *
 *  - one move per target: it starts `leadMs` BEFORE the moment the target is looked at, lasts
 *    400-900 ms (longer for a bigger zoom change or a longer pan) and eases in and out (smoothstep)
 *  - the speed limits are hard: the move is stretched until its fastest frame stays under the zoom
 *    and pan limits; when the time before the next move runs out the target is only approached
 *    part of the way (a smaller zoom change) instead of snapping
 *  - while holding, the camera never stands still: a very slow zoom-in with a lean toward the focus
 *  - two targets close in time and in space become one (no zooming out and in again)
 *  - a clip can start from the view the previous scene ended on (same page): no second
 *    establishing shot
 *
 * Pure functions: the same focus list always gives the same path.
 */
import { CAMERA_CONFIG, type CameraConfig } from "./config";
import {
  coverScale,
  establishingView,
  insideClip,
  lerpView,
  targetView,
  type FocusCamera,
  type ClipBox,
  type FocusLike,
  type View,
} from "./focus";
import type { Size } from "../geometry";

export const FPS = 30;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
export const smoothstep = (u: number) => {
  const x = clamp(u, 0, 1);
  return x * x * (3 - 2 * x);
};
const centre = (v: View) => ({ x: v.x + v.w / 2, y: v.y + v.h / 2 });

export interface Move {
  start: number; // ms
  duration: number; // ms
  from: View;
  to: View;
  /** the moment (ms) of the focus target this move was planned for */
  target: number;
}

/** A stretch of the path: a move between two views, or a hold on one (drifting slowly). */
type Seg =
  | { kind: "move"; t0: number; t1: number; from: View; to: View }
  | { kind: "hold"; t0: number; t1: number; base: View; focus: { x: number; y: number }; box?: ClipBox };

export interface CameraPath {
  at(tMs: number): FocusCamera;
  /** true while a move is under way (punch-ins keep out of its way) */
  moving(tMs: number): boolean;
  /** the view the camera is on at the end of the clip: the next scene may start from it */
  endView(): View;
  moves: Move[];
}

export interface PathOptions {
  /** a hook opens already on its first target */
  closeOpening?: boolean;
  /** same page as the previous scene: start from the view that scene ended on */
  startView?: View | null;
  /** clip length, for endView (defaults to the last move's end plus a second) */
  endMs?: number;
}

/** Targets close in time and in space are one: the union of their boxes, looked at from the first moment. */
export function mergeFocus(focus: FocusLike[], clip: Size, cfg: CameraConfig = CAMERA_CONFIG): FocusLike[] {
  const { mergeGapMs, mergeNear } = cfg.path;
  const out: FocusLike[] = [];
  for (const fp of [...focus].sort((a, b) => a.t_ms - b.t_ms)) {
    const last = out[out.length - 1];
    if (last && last.framing !== "establish" && fp.framing !== "establish" && fp.t_ms - last.t_ms < mergeGapMs) {
      const x0 = Math.min(last.bbox.x, fp.bbox.x);
      const y0 = Math.min(last.bbox.y, fp.bbox.y);
      const x1 = Math.max(last.bbox.x + last.bbox.w, fp.bbox.x + fp.bbox.w);
      const y1 = Math.max(last.bbox.y + last.bbox.h, fp.bbox.y + fp.bbox.h);
      if (x1 - x0 <= mergeNear * clip.w * 1.8 && y1 - y0 <= mergeNear * clip.w) {
        out[out.length - 1] = {
          ...last,
          bbox: { x: x0, y: y0, w: x1 - x0, h: y1 - y0 },
          framing: last.framing ? "medium" : last.framing,
          hold_ms: Math.max(0, fp.t_ms + (fp.hold_ms ?? 0) - last.t_ms),
        };
        continue;
      }
    }
    out.push(fp);
  }
  return out;
}

/**
 * Width after zooming in slowly for `travel` (log units): it goes down to `minW` (the maximum zoom),
 * turns around and breathes out again, back and forth, instead of standing still at the limit.
 */
export function breathe(width: number, minW: number, travel: number): number {
  const lnMin = Math.log(minW);
  const top = Math.max(Math.log(width), lnMin + 0.03); // some room to breathe even at the limit
  const span = top - lnMin;
  const p = (((top - Math.log(width)) + travel) % (2 * span) + 2 * span) % (2 * span);
  return Math.exp(lnMin + (p <= span ? span - p : p - span));
}

/** The box a target is framed with: its box plus the padding, kept inside the clip. */
export function paddedBox(bbox: ClipBox, clip: Size, cfg: CameraConfig): ClipBox {
  const dx = bbox.w * cfg.padding;
  const dy = bbox.h * cfg.padding;
  const x0 = clamp(bbox.x - dx, 0, clip.w);
  const y0 = clamp(bbox.y - dy, 0, clip.h);
  const x1 = clamp(bbox.x + bbox.w + dx, 0, clip.w);
  const y1 = clamp(bbox.y + bbox.h + dy, 0, clip.h);
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

/** Slide `v` (inside the clip) just far enough that `box` is whole inside it, when it can hold it at all. */
export function keepBox(v: View, box: ClipBox, clip: Size): View {
  const slide = (lo: number, size: number, b0: number, b1: number, max: number) =>
    b1 - b0 > size ? lo : clamp(clamp(lo, b1 - size, b0), 0, Math.max(0, max - size));
  return {
    ...v,
    x: v.w >= clip.w ? v.x : slide(v.x, v.w, box.x, box.x + box.w, clip.w),
    y: v.h >= clip.h ? v.y : slide(v.y, v.h, box.y, box.y + box.h, clip.h),
  };
}

/** A width that goes out by up to `amp` (log units) and back, instead of standing still. */
export function wobble(width: number, travel: number, amp = 0.04): number {
  const p = ((travel % (2 * amp)) + 2 * amp) % (2 * amp);
  return width * Math.exp(p <= amp ? p : 2 * amp - p);
}

/** The view after holding `dtMs` on `base`: a very slow zoom-in and a lean toward the focus centre. */
export function driftView(
  base: View,
  focusCentre: { x: number; y: number },
  dtMs: number,
  clip: Size,
  frame: Size,
  cfg: CameraConfig,
  /** the focus's padded box: the drift never lets its edge out of the view */
  box?: ClipBox,
): View {
  const dt = Math.max(0, dtMs) / 1000;
  const cover = frame.w / coverScale(clip, frame);
  // never closer than what still holds the focus box whole
  const roomW = box ? Math.max(box.w, (box.h * frame.w) / frame.h) : 0;
  // a view that is already as close as the box allows cannot zoom in: it breathes outward instead
  const tight = roomW > cover / cfg.maxZoom && roomW >= base.w * 0.97;
  const travel = cfg.path.driftZoomPerSec * dt;
  const w = tight ? wobble(base.w, travel) : breathe(base.w, Math.max(roomW, cover / cfg.maxZoom), travel);
  const c = centre(base);
  // (the establishing shot creeps in too: the whole page, a little closer, instead of standing still)
  const lean = base.w >= clip.w ? 0 : Math.min(1, cfg.path.driftPanPerSec * dt);
  const v = insideClip(c.x + (focusCentre.x - c.x) * lean, c.y + (focusCentre.y - c.y) * lean, cover / w, clip, frame);
  return box ? keepBox(v, box, clip) : v;
}

/** How long a move needs: the distance rule (400-900 ms) stretched until the speed limits hold. */
export function moveDuration(from: View, to: View, fps: number, cfg: CameraConfig): { ms: number; needed: number } {
  const p = cfg.path;
  const dz = Math.abs(Math.log(to.w / from.w));
  const a = centre(from);
  const b = centre(to);
  const dist = Math.hypot(b.x - a.x, b.y - a.y) / Math.min(from.w, to.w);
  const base = clamp(p.moveMinMs + 260 * Math.min(1.5, dist) + 330 * Math.min(1, dz / Math.log(1.6)), p.moveMinMs, p.moveMaxMs);
  const zoomFrames = (p.easePeak * dz) / (p.maxZoomRate * p.safety);
  const panFrames = (p.easePeak * dist) / (p.maxPanRate * p.safety);
  const needed = (Math.max(zoomFrames, panFrames) / fps) * 1000;
  return { ms: Math.max(base, needed), needed };
}

/** A view as a valid window of the clip (centred when taller/wider than the clip): idempotent. */
export function settle(v: View, clip: Size, frame: Size): View {
  const c = centre(v);
  return insideClip(c.x, c.y, frame.w / coverScale(clip, frame) / v.w, clip, frame);
}

/**
 * Not enough time to reach `view`: aim at the same spot from further away (a smaller zoom, up to the
 * whole page), as little as that needs. Only when even that cannot be done in time, go part of the way.
 */
export function fitTarget(from: View, view: View, duration: number, fps: number, clip: Size, frame: Size, cfg: CameraConfig): View {
  const c = centre(view);
  const cover = frame.w / coverScale(clip, frame);
  for (let f = 1.08; f <= 3; f *= 1.08) {
    const w = Math.min(view.w * f, Math.max(clip.w, view.w));
    const cand = insideClip(c.x, c.y, cover / w, clip, frame);
    if (moveDuration(from, cand, fps, cfg).needed <= duration) return cand;
    if (w >= clip.w) break;
  }
  const need = moveDuration(from, view, fps, cfg).needed;
  return settle(lerpView(from, view, clamp(duration / need, 0.05, 1)), clip, frame);
}

export function buildCameraPath(
  focusIn: FocusLike[],
  clip: Size,
  frame: Size,
  opts: PathOptions = {},
  cfg: CameraConfig = CAMERA_CONFIG,
  fps = FPS,
): CameraPath {
  const p = cfg.path;
  // an establishing entry is only the opening shot, which the path already starts with
  const focus = mergeFocus(focusIn.filter((f) => f.framing !== "establish"), clip, cfg);
  const est = establishingView(clip, frame);
  const targets = focus.map((fp) => {
    const view = targetView(fp, clip, frame, cfg);
    return { fp, view, c: centre(view), box: fp.framing === "establish" ? undefined : paddedBox(fp.bbox, clip, cfg) };
  });
  const fixed = opts.startView ?? (opts.closeOpening && targets.length ? targets[0].view : null);
  const first: View = fixed ?? est;

  const segs: Seg[] = [];
  const moves: Move[] = [];
  let hold: Extract<Seg, { kind: "hold" }> = {
    kind: "hold", t0: 0, t1: Infinity, base: first, focus: targets[0]?.c ?? centre(first),
    box: fixed && targets[0] ? targets[0].box : undefined,
  }; // fmt: skip
  segs.push(hold);
  const holdAt = (t: number) => driftView(hold.base, hold.focus, t - hold.t0, clip, frame, cfg, hold.box);

  const plan = (view: View, targetMs: number, wanted: number, settle: number, focusCentre: { x: number; y: number }, box?: ClipBox) => {
    let start = Math.max(wanted, settle, hold.t0);
    const need = moveDuration(holdAt(start), view, fps, cfg);
    // a long move starts earlier (as far as the previous one allows) so it still lands near the moment
    const extra = Math.max(0, need.ms - (p.moveMaxMs - 100));
    start = Math.max(hold.t0, settle, wanted - extra);
    const from = holdAt(start);
    const room = Math.max(p.moveMinMs, targetMs + p.moveMaxMs - start); // the latest sensible arrival
    const real = moveDuration(from, view, fps, cfg);
    const duration = Math.min(real.ms, room);
    // not enough time for the whole change: go only as far as the limits allow in that time
    const to = real.needed > duration ? fitTarget(from, view, duration, fps, clip, frame, cfg) : view;
    hold.t1 = start;
    const still = Math.abs(Math.log(to.w / from.w)) < 1e-4 && Math.hypot(centre(to).x - centre(from).x, centre(to).y - centre(from).y) < 0.5;
    if (still) {
      hold = { kind: "hold", t0: start, t1: Infinity, base: from, focus: focusCentre, box };
    } else {
      segs.push({ kind: "move", t0: start, t1: start + duration, from, to });
      moves.push({ start, duration, from, to, target: targetMs });
      hold = { kind: "hold", t0: start + duration, t1: Infinity, base: to, focus: focusCentre, box };
    }
    segs.push(hold);
  };

  if (targets.length === 0 && !fixed) {
    plan(insideClip(clip.w / 2, clip.h / 2, 1, clip, frame), 0, cfg.establishingMs, cfg.establishingMs, centre(first));
  }
  targets.forEach((t, i) => {
    const settle = i === 0 && !fixed ? cfg.establishingMs : 0; // the first move waits out the establishing shot
    plan(t.view, t.fp.t_ms, Math.max(0, t.fp.t_ms - p.leadMs), settle, t.c, t.box);
  });

  const lastEnd = moves.length ? moves[moves.length - 1].start + moves[moves.length - 1].duration : 0;
  const endMs = opts.endMs ?? lastEnd + 1000;

  const finish = (view: View): FocusCamera => {
    const cover = frame.w / coverScale(clip, frame);
    const zoom = cover / view.w;
    const establishing = clamp((1 - zoom) / (1 - cover / est.w), 0, 1);
    return { view, zoom, establishing };
  };
  const at = (tMs: number): FocusCamera => {
    const seg = segs.find((x) => tMs >= x.t0 && tMs < x.t1) ?? segs[segs.length - 1];
    if (seg.kind === "move") {
      const u = smoothstep((tMs - seg.t0) / (seg.t1 - seg.t0));
      return finish(settle(lerpView(seg.from, seg.to, u), clip, frame));
    }
    return finish(driftView(seg.base, seg.focus, tMs - seg.t0, clip, frame, cfg, seg.box));
  };
  const moving = (tMs: number) => moves.some((m) => tMs >= m.start - 80 && tMs <= m.start + m.duration + 80);
  return { at, moving, endView: () => at(endMs).view, moves };
}
