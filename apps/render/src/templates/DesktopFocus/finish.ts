/**
 * The finishing touches of the desktop_focus template, as pure functions of frames and boxes:
 * kinetic on-screen text (word by word, on the beat of the voice-over), the stat callout and the
 * corner it takes, punch-ins at the start of a shot, and the before/after halves.
 */
import { wordsOf } from "../../captionWords";
import type { Caption } from "../../props";

export interface Size {
  w: number;
  h: number;
}
export interface Rect extends Size {
  x: number;
  y: number;
}

export const STAGGER_MS = 75; // 60-90 ms between words
export const POP_FRAMES = 8;
export const POP_FROM = 0.85;
export const PUNCH_GROW_FRAMES = 6;
export const PUNCH_DECAY_FRAMES = 24;
export const STAT_START_SHARE = 0.15; // inside the first 30 % of the scene
export const STAT_POP_FRAMES = 12;

/** Lower case, no accents, letters and digits only: how a spoken word and a written one are compared. */
export function fold(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/đ/gi, "d")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

export interface KineticWord {
  text: string;
  startFrame: number;
  highlight: boolean;
}

/** The word to colour: one with a digit or %, else the longest word of at least five letters. */
export function highlightIndex(words: string[]): number {
  const numeric = words.findIndex((w) => /\d/.test(w));
  if (numeric >= 0) return numeric;
  let best = -1;
  words.forEach((w, i) => {
    const len = fold(w).length;
    if (len >= 5 && (best < 0 || len > fold(words[best]).length)) best = i;
  });
  return best;
}

/** Word by word from `anchor`, STAGGER_MS apart; the keyword is flagged. */
export function kineticWords(text: string, anchor: number, fps: number): KineticWord[] {
  const words = text.trim().split(/\s+/).filter(Boolean);
  const hi = highlightIndex(words);
  const step = Math.max(1, Math.round((STAGGER_MS / 1000) * fps));
  return words.map((w, i) => ({ text: w, startFrame: anchor + i * step, highlight: i === hi }));
}

/** The frame the voice says the first word of the on-screen text (else `fallback`). */
export function anchorFrame(text: string, captions: Caption[], fps: number, fallback: number): number {
  const first = fold(text.trim().split(/\s+/)[0] ?? "");
  if (!first) return fallback;
  for (const c of captions) {
    for (const w of wordsOf(c)) if (fold(w.text) === first) return Math.round((w.start_ms / 1000) * fps);
  }
  return fallback;
}

/** 0.85 → 1 over POP_FRAMES (ease-out); a word that has not started is invisible. */
export function popOf(frame: number, startFrame: number): { scale: number; opacity: number } {
  if (frame < startFrame) return { scale: POP_FROM, opacity: 0 };
  const p = Math.min(1, (frame - startFrame) / POP_FRAMES);
  const eased = 1 - (1 - p) * (1 - p);
  return { scale: POP_FROM + (1 - POP_FROM) * eased, opacity: Math.min(1, p * 2) };
}

export interface Punch {
  t_ms: number;
  scale: number;
}

/** Extra zoom (≥ 1) from the punch-ins: grows within 6 frames, then eases back. */
export function punchFactor(frame: number, punches: Punch[], fps: number): number {
  let factor = 1;
  for (const p of punches) {
    const at = (p.t_ms / 1000) * fps;
    const dt = frame - at;
    if (dt < 0) continue;
    const grow = Math.min(1, dt / PUNCH_GROW_FRAMES);
    const decay = dt <= PUNCH_GROW_FRAMES ? 1 : Math.max(0, 1 - (dt - PUNCH_GROW_FRAMES) / PUNCH_DECAY_FRAMES);
    factor = Math.max(factor, 1 + p.scale * (1 - (1 - grow) * (1 - grow)) * decay);
  }
  return factor;
}

export function statStartFrame(durationFrames: number): number {
  return Math.round(durationFrames * STAT_START_SHARE);
}

export type Corner = "top-right" | "top-left" | "bottom-right" | "bottom-left";
const CORNER_ORDER: Corner[] = ["top-right", "top-left", "bottom-right", "bottom-left"];

export function cornerRect(corner: Corner, frame: Size, box: Size, margin: number, bottomReserve = 0): Rect {
  const x = corner.endsWith("right") ? frame.w - box.w - margin : margin;
  const y = corner.startsWith("top") ? margin : frame.h - bottomReserve - box.h - margin;
  return { x, y, w: box.w, h: box.h };
}

export function intersects(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

/** The first corner whose callout box does not cover the focus (top-right by default). */
export function pickStatCorner(focus: Rect | null, frame: Size, box: Size, margin = 28, bottomReserve = 0): Corner {
  if (!focus) return CORNER_ORDER[0];
  const free = CORNER_ORDER.find((c) => !intersects(cornerRect(c, frame, box, margin, bottomReserve), focus));
  return free ?? CORNER_ORDER[0];
}

/** Left half = before, right half = after, with a thin gap. */
export function splitHalves(frame: Size, gap = 6): { left: Rect; right: Rect } {
  const w = Math.floor((frame.w - gap) / 2);
  return { left: { x: 0, y: 0, w, h: frame.h }, right: { x: w + gap, y: 0, w: frame.w - w - gap, h: frame.h } };
}
