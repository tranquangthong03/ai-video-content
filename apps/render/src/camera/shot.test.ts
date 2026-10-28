import { describe, expect, it } from "vitest";
import { buildShotPath, fitZoom, fullView, shotView, type ZoomShot } from "./shot";

const CLIP = { w: 1280, h: 720 };
const FRAME = { w: 1040, h: 585 };
const FPS = 30;

const shot = (overrides: Partial<ZoomShot> = {}): ZoomShot => ({
  in_start_ms: 2000,
  in_end_ms: 2600,
  out_start_ms: 4400,
  out_end_ms: 4900,
  box: { x: 300, y: 200, w: 400, h: 240 },
  zoom: 1.7,
  ...overrides,
});

describe("the shot camera", () => {
  it("stands on the full view, perfectly still, when there is no shot", () => {
    const path = buildShotPath([], CLIP, FRAME);
    const first = path.at(0);
    for (let t = 0; t < 10000; t += 33) {
      expect(path.at(t).view).toEqual(first.view);
      expect(path.moving(t)).toBe(false);
    }
    expect(first.zoom).toBe(1);
    expect(first.view).toEqual({ x: 0, y: 0, w: 1280, h: 720 });
  });

  it("contains a clip of another aspect: the whole page is in view, bars go to the backdrop", () => {
    const full = fullView({ w: 1440, h: 900 }, FRAME);
    expect(full.h).toBeCloseTo(900);
    expect(full.w).toBeCloseTo(1600);
    expect(buildShotPath([], { w: 1440, h: 900 }, FRAME).at(0).establishing).toBe(1);
  });

  it("moves in, holds still, moves out, and is back on the full view afterwards", () => {
    const path = buildShotPath([shot()], CLIP, FRAME);
    const held = path.at(3000).view;
    expect(path.at(4000).view).toEqual(held);
    expect(path.at(2300).view.w).toBeLessThan(1280);
    expect(path.at(2300).view.w).toBeGreaterThan(held.w);
    expect(path.at(4700).view.w).toBeGreaterThan(held.w);
    expect(path.at(5200).view).toEqual({ x: 0, y: 0, w: 1280, h: 720 });
    expect(path.moving(2300)).toBe(true);
    expect(path.moving(3500)).toBe(false);
    expect(path.moves).toHaveLength(2);
  });

  it("zooms to one fixed level, lowered only as far as the block needs, and always holds the block whole", () => {
    const wide = shot({ box: { x: 100, y: 100, w: 900, h: 400 } });
    expect(fitZoom(wide.box, CLIP, FRAME)).toBeCloseTo(1280 / 900);
    const v = shotView(wide, CLIP, FRAME);
    expect(v.w).toBeCloseTo(900, 0);
    expect(v.x).toBeLessThanOrEqual(wide.box.x + 1e-6);
    expect(v.x + v.w).toBeGreaterThanOrEqual(wide.box.x + wide.box.w - 1e-6);
    const tall = shotView(shot({ box: { x: 500, y: 40, w: 200, h: 640 } }), CLIP, FRAME);
    expect(tall.y).toBeLessThanOrEqual(40 + 1e-6);
    expect(tall.y + tall.h).toBeGreaterThanOrEqual(680 - 1e-6);
  });

  it("keeps the window inside the clip when the block sits at an edge", () => {
    const v = shotView(shot({ box: { x: 1000, y: 560, w: 270, h: 150 } }), CLIP, FRAME);
    expect(v.x).toBeGreaterThanOrEqual(0);
    expect(v.y).toBeGreaterThanOrEqual(0);
    expect(v.x + v.w).toBeLessThanOrEqual(1280 + 1e-6);
    expect(v.y + v.h).toBeLessThanOrEqual(720 + 1e-6);
  });

  it("moves at the eased speed the shot's duration gives (no frame jumps more than the ease peak)", () => {
    const path = buildShotPath([shot()], CLIP, FRAME);
    let prev = path.at(0).view;
    let worst = 0;
    for (let f = 1; f < 200; f++) {
      const v = path.at((f / FPS) * 1000).view;
      worst = Math.max(worst, Math.abs(prev.w / v.w - 1));
      prev = v;
    }
    expect(worst).toBeLessThan(0.06);
  });
});
