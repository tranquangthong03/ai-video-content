/**
 * Virtual camera and cursor for the desktop_showcase media frame. Pure functions of time: given the
 * click log of a clip they return where the camera looks and where the cursor is. All points are in
 * clip pixels on input and in media-frame pixels on output; times are clip-time milliseconds.
 *
 * click, dblclick: zoom the camera and ripple. highlight: a gentler zoom. hover: the cursor moves
 * there but the camera does not zoom. scroll: ignored.
 */
import { mapClipPoint, type Point, type Size } from "../geometry";

export type ClipClick = {
  t_ms: number;
  x: number;
  y: number;
  type?: "click" | "dblclick" | "scroll" | "highlight" | "hover";
};
export type SpringConfig = { damping: number; stiffness: number; mass: number };
export type CameraPreset = { spring: SpringConfig; clickZoom: number };
/** Visible window: `scale` zoom, `left`/`top` = frame pixel (unzoomed) at the window's top-left. */
export type Camera = { scale: number; left: number; top: number };

export const HOLD_MS = 1200; // how long a zoom is held after the last click of a chain
export const CHAIN_GAP_MS = 1500; // clicks closer than this share one zoom (the camera pans)
export const PAN_LEAD_MS = 300; // the pan toward the next click starts this long before it
export const CURSOR_LEAD_MS = 400; // the cursor starts moving this long before the click
export const RIPPLE_MS = 600;
export const HIGHLIGHT_ZOOM = 0.35; // share of the click zoom used for a highlight
const PRESS_MS = 260;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const lerp = (a: number, b: number, u: number) => a + (b - a) * u;
const easeInOutCubic = (u: number) => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2);

/** Step response (0 -> 1) of a damped spring, closed form; same model Remotion's spring() uses. */
export function springStep(tSec: number, { damping, stiffness, mass }: SpringConfig): number {
  if (tSec <= 0) return 0;
  const w0 = Math.sqrt(stiffness / mass);
  const zeta = damping / (2 * Math.sqrt(stiffness * mass));
  if (zeta < 1) {
    const wd = w0 * Math.sqrt(1 - zeta * zeta);
    return 1 - Math.exp(-zeta * w0 * tSec) * (Math.cos(wd * tSec) + ((zeta * w0) / wd) * Math.sin(wd * tSec));
  }
  if (zeta === 1) return 1 - Math.exp(-w0 * tSec) * (1 + w0 * tSec);
  const r = Math.sqrt(zeta * zeta - 1);
  const s1 = -w0 * (zeta - r);
  const s2 = -w0 * (zeta + r);
  return 1 - (s2 * Math.exp(s1 * tSec) - s1 * Math.exp(s2 * tSec)) / (s2 - s1);
}

type Event = { t: number; x: number; y: number; k: number }; // k: share of the click zoom
type Chain = { start: number; end: number; points: Event[]; k: number };

const toFrame = (c: ClipClick, clip: Size, frame: Size) =>
  mapClipPoint({ x: c.x, y: c.y }, clip, { x: 0, y: 0, ...frame });

/** Events that move the camera: clicks (full zoom) and highlights (gentle zoom). */
function zoomEvents(clicks: ClipClick[], clip: Size, frame: Size): Event[] {
  return clicks
    .filter((c) => c.type === undefined || c.type === "click" || c.type === "dblclick" || c.type === "highlight")
    .sort((a, b) => a.t_ms - b.t_ms)
    .map((c) => ({ t: c.t_ms, ...toFrame(c, clip, frame), k: c.type === "highlight" ? HIGHLIGHT_ZOOM : 1 }));
}

/** Consecutive events closer than CHAIN_GAP_MS belong to one zoom. */
function chainsOf(evts: Event[]): Chain[] {
  const chains: Chain[] = [];
  for (const e of evts) {
    const last = chains[chains.length - 1];
    if (last && e.t - last.end < CHAIN_GAP_MS) {
      last.points.push(e);
      last.end = e.t;
      last.k = Math.max(last.k, e.k);
    } else {
      chains.push({ start: e.t, end: e.t, points: [e], k: e.k });
    }
  }
  return chains;
}

const envelope = (c: Chain, tMs: number, spring: SpringConfig) =>
  clamp(
    springStep((tMs - c.start) / 1000, spring) - springStep((tMs - (c.end + HOLD_MS)) / 1000, spring),
    0,
    1.1,
  );

/** Where the camera looks inside a chain at time t: pans from click to click. */
function focusOf(c: Chain, tMs: number, spring: SpringConfig): Point {
  let pos: Point = c.points[0];
  for (let i = 1; i < c.points.length; i++) {
    const panStart = Math.max(c.points[i - 1].t, c.points[i].t - PAN_LEAD_MS);
    if (tMs < panStart) break;
    const u = clamp(springStep((tMs - panStart) / 1000, spring), 0, 1);
    pos = { x: lerp(c.points[i - 1].x, c.points[i].x, u), y: lerp(c.points[i - 1].y, c.points[i].y, u) };
  }
  return pos;
}

/** Camera at time t. Never shows anything outside the frame (the window is clamped to its edges). */
export function cameraAt(
  tMs: number,
  clicks: ClipClick[],
  clip: Size,
  frame: Size,
  preset: CameraPreset,
): Camera {
  const chains = chainsOf(zoomEvents(clicks, clip, frame));
  let best: { chain: Chain; env: number } | null = null;
  for (const chain of chains) {
    const env = envelope(chain, tMs, preset.spring) * chain.k;
    if (env > 0 && (!best || env > best.env)) best = { chain, env };
  }
  if (!best) return { scale: 1, left: 0, top: 0 };
  const scale = Math.max(1, 1 + (preset.clickZoom - 1) * best.env);
  const focus = focusOf(best.chain, tMs, preset.spring);
  const vw = frame.w / scale;
  const vh = frame.h / scale;
  return {
    scale,
    left: clamp(focus.x - vw / 2, 0, frame.w - vw),
    top: clamp(focus.y - vh / 2, 0, frame.h - vh),
  };
}

/** Frame point -> position on screen after the camera transform. */
export const project = (p: Point, cam: Camera): Point => ({
  x: (p.x - cam.left) * cam.scale,
  y: (p.y - cam.top) * cam.scale,
});

export type CursorState = {
  x: number; // frame px, before the camera transform (use project())
  y: number;
  opacity: number;
  press: number; // 0..1, peaks mid-click: the cursor dips
  ripples: { x: number; y: number; age: number }[]; // age 0..1
};

type CursorEvent = { t: number; x: number; y: number; press: boolean };

/** Cursor at time t: glides to each click or hover (starting CURSOR_LEAD_MS early); clicks ripple. */
export function cursorAt(tMs: number, clicks: ClipClick[], clip: Size, frame: Size): CursorState {
  const evts: CursorEvent[] = clicks
    .filter((c) => c.type === undefined || c.type === "click" || c.type === "dblclick" || c.type === "hover")
    .sort((a, b) => a.t_ms - b.t_ms)
    .map((c) => ({ t: c.t_ms, ...toFrame(c, clip, frame), press: c.type !== "hover" }));
  const home: Point = { x: frame.w * 0.78, y: frame.h * 0.85 };
  if (evts.length === 0) return { ...home, opacity: 0, press: 0, ripples: [] };

  let pos = home;
  let prevT = -Infinity;
  let from = home;
  for (const e of evts) {
    const moveStart = Math.max(prevT, e.t - CURSOR_LEAD_MS);
    if (tMs >= moveStart) {
      const u = easeInOutCubic(clamp((tMs - moveStart) / Math.max(1, e.t - moveStart), 0, 1));
      pos = { x: lerp(from.x, e.x, u), y: lerp(from.y, e.y, u) };
    }
    from = e;
    prevT = e.t;
  }

  const first = evts[0].t - CURSOR_LEAD_MS;
  const last = evts[evts.length - 1].t + 2000;
  const fadeIn = clamp((tMs - (first - 500)) / 500, 0, 1);
  const fadeOut = clamp((last + 300 - tMs) / 300, 0, 1);

  let press = 0;
  const ripples: CursorState["ripples"] = [];
  for (const e of evts) {
    if (!e.press) continue;
    const dt = tMs - e.t;
    if (dt >= 0 && dt < PRESS_MS) press = Math.max(press, Math.sin((Math.PI * dt) / PRESS_MS));
    if (dt >= 0 && dt <= RIPPLE_MS) ripples.push({ x: e.x, y: e.y, age: dt / RIPPLE_MS });
  }
  return { ...pos, opacity: Math.min(fadeIn, fadeOut), press, ripples };
}

// the focus-first camera (desktop_focus) and its knobs
export * from "./focus";
export { CAMERA_CONFIG } from "./config";
export { pickFocus } from "./pick";
export type { CameraConfig, FocusKind, Framing } from "./config";
export { cameraForScene } from "./scene";
