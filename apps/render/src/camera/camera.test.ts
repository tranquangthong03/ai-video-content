import { describe, expect, it } from "vitest";
import {
  CHAIN_GAP_MS,
  CURSOR_LEAD_MS,
  HOLD_MS,
  RIPPLE_MS,
  cameraAt,
  cursorAt,
  project,
  springStep,
  type CameraPreset,
  type ClipClick,
} from "./index";

const CLIP = { w: 1920, h: 1080 };
const FRAME = { w: 994, h: 559 };
const ENERGETIC: CameraPreset = { spring: { damping: 9, stiffness: 160, mass: 0.7 }, clickZoom: 2.0 };
const CALM: CameraPreset = { spring: { damping: 22, stiffness: 70, mass: 1 }, clickZoom: 1.6 };
const cam = (t: number, clicks: ClipClick[], preset = ENERGETIC) => cameraAt(t, clicks, CLIP, FRAME, preset);
const click = (t_ms: number, x: number, y: number): ClipClick => ({ t_ms, x, y });

describe("springStep", () => {
  it("starts at 0 and settles at 1 for under-, critically and over-damped springs", () => {
    for (const s of [ENERGETIC.spring, CALM.spring, { damping: 20, stiffness: 100, mass: 1 }]) {
      expect(springStep(0, s)).toBe(0);
      expect(springStep(-1, s)).toBe(0);
      expect(springStep(6, s)).toBeCloseTo(1, 3);
    }
  });
});

describe("cameraAt", () => {
  it("shows the whole frame without clicks and before the first click", () => {
    expect(cam(2000, [])).toEqual({ scale: 1, left: 0, top: 0 });
    expect(cam(900, [click(1000, 960, 540)])).toEqual({ scale: 1, left: 0, top: 0 });
  });

  it("zooms to the preset scale after a click, holds, then returns", () => {
    const clicks = [click(1000, 960, 540)];
    expect(cam(2000, clicks).scale).toBeCloseTo(2.0, 1);
    expect(cam(1000 + HOLD_MS - 100, clicks).scale).toBeCloseTo(2.0, 1);
    expect(cam(1000 + HOLD_MS + 3000, clicks).scale).toBeCloseTo(1, 2);
    expect(cam(2000, clicks, CALM).scale).toBeCloseTo(1.6, 1);
  });

  it("zooms in smoothly (monotonic ramp, no jump)", () => {
    const clicks = [click(1000, 960, 540)];
    const scales = [0, 100, 200, 300, 400, 600].map((dt) => cam(1000 + dt, clicks, CALM).scale);
    for (let i = 1; i < scales.length; i++) expect(scales[i]).toBeGreaterThanOrEqual(scales[i - 1]);
    expect(scales[1] - 1).toBeLessThan(0.3);
  });

  it("keeps zoom between clicks closer than the chain gap and pans instead of zooming out", () => {
    const clicks = [click(1000, 300, 300), click(1900, 1600, 800)];
    expect(1900 - 1000).toBeLessThan(CHAIN_GAP_MS);
    let minScale = Infinity;
    for (let t = 1800; t <= 1900 + HOLD_MS - 100; t += 50) minScale = Math.min(minScale, cam(t, clicks).scale);
    expect(minScale).toBeGreaterThan(1.9);
    // the window moves right from the first click to the second
    const a = cam(1500, clicks).left;
    const b = cam(2400, clicks).left;
    expect(b).toBeGreaterThan(a + 100);
  });

  it("zooms out between clicks further apart than the chain gap", () => {
    const clicks = [click(1000, 300, 300), click(1000 + CHAIN_GAP_MS + 1200, 1600, 800)];
    expect(cam(1000 + HOLD_MS + 600, clicks).scale).toBeLessThan(1.15);
  });

  it("never reveals anything outside the frame, even for clicks on the corners", () => {
    const corners = [click(0, 0, 0), click(0, 1920, 0), click(0, 0, 1080), click(0, 1920, 1080)];
    for (const c of corners) {
      for (const t of [200, 600, 1200]) {
        const k = cam(t, [c]);
        expect(k.left).toBeGreaterThanOrEqual(0);
        expect(k.top).toBeGreaterThanOrEqual(0);
        expect(k.left + FRAME.w / k.scale).toBeLessThanOrEqual(FRAME.w + 1e-6);
        expect(k.top + FRAME.h / k.scale).toBeLessThanOrEqual(FRAME.h + 1e-6);
      }
    }
    const br = cam(1200, [click(0, 1920, 1080)]);
    expect(br.left).toBeCloseTo(FRAME.w - FRAME.w / br.scale, 3);
  });

  it("centers on the click when there is room", () => {
    const k = cam(1500, [click(1000, 960, 540)]);
    const p = project({ x: FRAME.w / 2, y: FRAME.h / 2 }, k);
    expect(p.x).toBeCloseTo(FRAME.w / 2, 0);
    expect(p.y).toBeCloseTo(FRAME.h / 2, 0);
  });

  it("ignores scroll events", () => {
    const events: ClipClick[] = [{ t_ms: 1000, x: 900, y: 500, type: "scroll" }];
    expect(cam(1500, events).scale).toBe(1);
    expect(cursorAt(1500, events, CLIP, FRAME).opacity).toBe(0);
    expect(cam(1500, [{ ...click(1000, 900, 500), type: "dblclick" }]).scale).toBeGreaterThan(1.5);
  });
});

describe("hover and highlight events", () => {
  it("does not zoom for a hover but the cursor still goes there, without a ripple", () => {
    const hover: ClipClick[] = [{ t_ms: 3000, x: 400, y: 300, type: "hover" }];
    expect(cam(3600, hover).scale).toBe(1);
    const c = cursorAt(3000, hover, CLIP, FRAME);
    expect(c.x).toBeCloseTo((400 * FRAME.w) / CLIP.w, 3);
    expect(c.ripples).toHaveLength(0);
    expect(cursorAt(3100, hover, CLIP, FRAME).press).toBe(0);
    expect(cursorAt(3000, hover, CLIP, FRAME).opacity).toBe(1);
  });

  it("zooms a highlight gently: more than 1, clearly less than a click", () => {
    const hl: ClipClick[] = [{ t_ms: 1000, x: 960, y: 540, type: "highlight" }];
    const gentle = cam(2000, hl).scale;
    const full = cam(2000, [click(1000, 960, 540)]).scale;
    expect(gentle).toBeGreaterThan(1.2);
    expect(gentle).toBeLessThan(full - 0.4);
    expect(cursorAt(2000, hl, CLIP, FRAME).opacity).toBe(0); // a highlight does not move the cursor
  });

  it("a click after a hover chain keeps the click zoom", () => {
    const mixed: ClipClick[] = [
      { t_ms: 1000, x: 400, y: 300, type: "hover" },
      click(1500, 960, 540),
    ];
    expect(cam(2500, mixed).scale).toBeCloseTo(2.0, 1);
  });
});

describe("cursorAt", () => {
  const clicks = [click(3000, 960, 540), click(5000, 200, 200)];

  it("is hidden well before the first click and after the last one", () => {
    expect(cursorAt(0, clicks, CLIP, FRAME).opacity).toBe(0);
    expect(cursorAt(9000, clicks, CLIP, FRAME).opacity).toBe(0);
    expect(cursorAt(3000, clicks, CLIP, FRAME).opacity).toBe(1);
  });

  it("starts moving CURSOR_LEAD_MS before the click and lands on it", () => {
    const before = cursorAt(3000 - CURSOR_LEAD_MS - 50, clicks, CLIP, FRAME);
    const start = cursorAt(3000 - CURSOR_LEAD_MS, clicks, CLIP, FRAME);
    const mid = cursorAt(3000 - CURSOR_LEAD_MS / 2, clicks, CLIP, FRAME);
    const at = cursorAt(3000, clicks, CLIP, FRAME);
    expect(before.x).toBeCloseTo(start.x, 3);
    expect(at.x).toBeCloseTo(FRAME.w / 2, 3);
    expect(at.y).toBeCloseTo(FRAME.h / 2, 3);
    expect(mid.x).toBeLessThan(start.x);
    expect(mid.x).toBeGreaterThan(at.x);
  });

  it("moves from one click to the next and rests on the last one", () => {
    const toSecond = cursorAt(5000, clicks, CLIP, FRAME);
    expect(toSecond.x).toBeCloseTo((200 * FRAME.w) / CLIP.w, 3);
    expect(cursorAt(5800, clicks, CLIP, FRAME).x).toBeCloseTo(toSecond.x, 3);
  });

  it("presses and ripples right after the click only", () => {
    expect(cursorAt(3000 - 10, clicks, CLIP, FRAME).ripples).toHaveLength(0);
    const during = cursorAt(3000 + 100, clicks, CLIP, FRAME);
    expect(during.press).toBeGreaterThan(0.5);
    expect(during.ripples).toHaveLength(1);
    expect(during.ripples[0].age).toBeCloseTo(100 / RIPPLE_MS, 5);
    expect(cursorAt(3000 + RIPPLE_MS + 50, clicks, CLIP, FRAME).ripples).toHaveLength(0);
    expect(cursorAt(3000 + 400, clicks, CLIP, FRAME).press).toBe(0);
  });

  it("has no cursor without clicks", () => {
    expect(cursorAt(1000, [], CLIP, FRAME).opacity).toBe(0);
  });
});
