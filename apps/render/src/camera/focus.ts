/**
 * Focus-first virtual camera. Pure functions of time: given the clip's focus log (boxes the
 * recorder wanted to show, in clip pixels and clip time) they return the window of the clip that
 * fills the media frame.
 *
 *  - first 1000 ms: "establishing shot", the whole page fitted to the frame width; the frame
 *    above and below it is filled by the backdrop (the clip itself, enlarged, blurred, dimmed)
 *  - then a spring move (about 0.5 s) to the first target; from then on the camera is never
 *    below cover (zoom 1.0) and never above CAMERA_CONFIG.maxZoom
 *  - every target is framed so its padded box fills about 70% of the view width
 *    (less for hover/scroll); a box wider than the view keeps the minimum zoom, centered
 *  - moves between targets are springs, the window is always clamped inside the clip
 */
import { CAMERA_CONFIG, type CameraConfig, type FocusKind, type Framing } from "./config";
import type { Size } from "../geometry";
import { springStep } from "./index";

export type ClipBox = { x: number; y: number; w: number; h: number };
/** A camera target: from the recorder's focus_log (kind) or from the focus_track (framing). */
export type FocusLike = { t_ms: number; bbox: ClipBox; kind?: FocusKind; framing?: Framing; hold_ms?: number };
/** The part of the clip shown in the media frame (clip pixels); same aspect as the frame. */
export type View = { x: number; y: number; w: number; h: number };
export type FocusCamera = {
  view: View;
  /** cover units: 1.0 = just filling the frame, < 1 only during the establishing shot */
  zoom: number;
  /** 1 = establishing shot (whole page), 0 = cover framing */
  establishing: number;
};

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const lerp = (a: number, b: number, u: number) => a + (b - a) * u;

/** Scale at which the clip just covers the frame. */
export const coverScale = (clip: Size, frame: Size) => Math.max(frame.w / clip.w, frame.h / clip.h);

/** Width of the clip window at zoom 1.0 (cover). */
const coverWidth = (clip: Size, frame: Size) => frame.w / coverScale(clip, frame);

const viewAt = (cx: number, cy: number, w: number, frame: Size): View => ({
  x: cx - w / 2,
  y: cy - (w * frame.h) / frame.w / 2,
  w,
  h: (w * frame.h) / frame.w,
});

/** The whole clip width in the frame, centered vertically; the window is taller than the clip. */
export function establishingView(clip: Size, frame: Size): View {
  return viewAt(clip.w / 2, clip.h / 2, clip.w, frame);
}

/** Window inside the clip (never outside) for a given centre and zoom. */
export function insideClip(cx: number, cy: number, zoom: number, clip: Size, frame: Size): View {
  const w = coverWidth(clip, frame) / zoom;
  const h = (w * frame.h) / frame.w;
  // a window larger than the clip (zoom below cover) is centred; the backdrop fills the rest
  return {
    x: w >= clip.w ? (clip.w - w) / 2 : clamp(cx - w / 2, 0, clip.w - w),
    y: h >= clip.h ? (clip.h - h) / 2 : clamp(cy - h / 2, 0, clip.h - h),
    w,
    h,
  };
}

/** Where the camera should look for one focus point. */
export function targetView(fp: FocusLike, clip: Size, frame: Size, cfg: CameraConfig = CAMERA_CONFIG): View {
  if (fp.framing === "establish") return establishingView(clip, frame);
  const pad = 1 + 2 * cfg.padding;
  const bw = fp.bbox.w * pad;
  const bh = fp.bbox.h * pad;
  const cover = coverWidth(clip, frame);
  const share = fp.framing ? cfg.framingShare[fp.framing] : (cfg.share[fp.kind ?? "click"] ?? 0.7);
  // the view that gives the padded box `share` of its width, and also holds it vertically
  let w = bw / share;
  const hAspect = frame.h / frame.w;
  w = Math.max(w, bh / (share * hAspect));
  let zoom = clamp(cover / w, cfg.minZoom, cfg.maxZoom);
  if (fp.framing) {
    // a focus_track target is never cut: when its padded box is wider (or taller) than the window
    // at cover, the camera zooms out below cover - down to the whole clip width - to hold it all
    const needed = Math.max(bw, bh / hAspect);
    zoom = Math.min(zoom, Math.max(cover / needed, cover / clip.w));
  }
  return insideClip(fp.bbox.x + fp.bbox.w / 2, fp.bbox.y + fp.bbox.h / 2, zoom, clip, frame);
}

/** Boxes around clicks, for clips recorded before the focus log existed. */
export function focusFromClicks(
  clicks: { t_ms: number; x: number; y: number; type?: string }[],
  cfg: CameraConfig = CAMERA_CONFIG,
): FocusLike[] {
  const kinds: Record<string, FocusKind> = {
    click: "click",
    dblclick: "dblclick",
    hover: "hover",
    highlight: "highlight",
  };
  return clicks
    .filter((c) => c.type === undefined || c.type in kinds)
    .map((c) => ({
      t_ms: c.t_ms,
      kind: kinds[c.type ?? "click"],
      bbox: { x: c.x - cfg.fallbackBox.w / 2, y: c.y - cfg.fallbackBox.h / 2, w: cfg.fallbackBox.w, h: cfg.fallbackBox.h },
    }));
}

type Segment = { start: number; target: View };
/** In-between of two views: width in log space (even-feeling zoom), centre linear. */
export const lerpView = (a: View, b: View, u: number): View => {
  // zoom (width) in log space so it feels even; centre linear
  const w = Math.exp(lerp(Math.log(a.w), Math.log(b.w), u));
  const cx = lerp(a.x + a.w / 2, b.x + b.w / 2, u);
  const cy = lerp(a.y + a.h / 2, b.y + b.h / 2, u);
  const h = (w * a.h) / a.w;
  return { x: cx - w / 2, y: cy - h / 2, w, h };
};

/** Move progress 0..1; reaches exactly 1 once the spring is `arrived` of the way. */
const progress = (tSec: number, cfg: CameraConfig) =>
  clamp(springStep(tSec, cfg.spring) / cfg.arrived, 0, 1);

/** Camera at clip time tMs. `focus` may be empty: then it rests on the centre of the clip. */
export function focusCameraAt(
  tMs: number,
  focus: FocusLike[],
  clip: Size,
  frame: Size,
  cfg: CameraConfig = CAMERA_CONFIG,
  /** A hook opens already on its first target: no establishing shot of the whole page. */
  closeOpening = false,
): FocusCamera {
  const cover = coverWidth(clip, frame);
  const sorted = [...focus].sort((a, b) => a.t_ms - b.t_ms);
  const centre = insideClip(clip.w / 2, clip.h / 2, 1, clip, frame);
  const opening = closeOpening && sorted.length > 0;
  const est = opening ? targetView(sorted[0], clip, frame, cfg) : establishingView(clip, frame);
  const settleMs = opening ? 0 : cfg.establishingMs;

  const segments: Segment[] = [];
  if (sorted.length === 0) segments.push({ start: cfg.establishingMs, target: centre });
  sorted.forEach((fp, i) => {
    const prev = segments[segments.length - 1];
    const wanted = i === 0 ? settleMs : fp.t_ms - cfg.leadMs;
    const start = prev ? Math.max(wanted, prev.start + cfg.minSegmentMs) : Math.max(wanted, settleMs);
    segments.push({ start, target: targetView(fp, clip, frame, cfg) });
  });

  // walk the segments, each moving from where the previous one had got to at the hand-over
  let view = est;
  let from = est;
  for (let k = 0; k < segments.length; k++) {
    const seg = segments[k];
    if (tMs < seg.start) {
      view = from;
      break;
    }
    const next = segments[k + 1];
    if (next && tMs >= next.start) {
      from = lerpView(from, seg.target, progress((next.start - seg.start) / 1000, cfg));
      continue;
    }
    view = lerpView(from, seg.target, progress((tMs - seg.start) / 1000, cfg));
    break;
  }
  const zoom = cover / view.w;
  const whole = establishingView(clip, frame);
  const establishing = clamp((1 - zoom) / (1 - cover / whole.w), 0, 1);
  return { view, zoom, establishing };
}

/** CSS transform for a clip element of size `clip` placed at (0,0) so that `view` fills the frame. */
export function viewTransform(view: View, frame: Size) {
  const scale = frame.w / view.w;
  return { scale, translateX: -view.x * scale, translateY: -view.y * scale };
}

/** Share of the time in [fromMs, toMs] at which the camera is at or above cover (zoom >= 1). */
export function coverShare(
  focus: FocusLike[],
  clip: Size,
  frame: Size,
  fromMs: number,
  toMs: number,
  cfg: CameraConfig = CAMERA_CONFIG,
  stepMs = 33,
): number {
  let total = 0;
  let ok = 0;
  for (let t = fromMs; t <= toMs; t += stepMs) {
    total++;
    if (focusCameraAt(t, focus, clip, frame, cfg).zoom >= cfg.minZoom - 1e-6) ok++;
  }
  return total === 0 ? 1 : ok / total;
}

/** The establishing shot (plus the move out of it) is over from this clip time on. */
export const establishingEndMs = (cfg: CameraConfig = CAMERA_CONFIG) => cfg.establishingMs + cfg.transitionMs;
