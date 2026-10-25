import { describe, expect, it } from "vitest";
import { CAMERA_CONFIG, coverScale, establishingView, focusCameraAt, pickFocus, targetView, type FocusLike } from "./index";

const CLIP = { w: 1440, h: 900 };
const FRAME = { w: 1000, h: 1250 };
const COVER_W = FRAME.w / coverScale(CLIP, FRAME); // 720
const entry = (t_ms: number, x: number, y: number, w: number, h: number, framing: FocusLike["framing"]): FocusLike => ({
  t_ms,
  bbox: { x, y, w, h },
  framing,
  hold_ms: 1500,
});
const padded = (w: number) => w * (1 + 2 * CAMERA_CONFIG.padding);
const holds = (v: { x: number; y: number; w: number; h: number }, b: { x: number; y: number; w: number; h: number }) => {
  const p = CAMERA_CONFIG.padding;
  return (
    v.x <= b.x - b.w * p + 1e-6 &&
    v.x + v.w >= b.x + b.w * (1 + p) - 1e-6 &&
    v.y <= b.y - b.h * p + 1e-6 &&
    v.y + v.h >= b.y + b.h * (1 + p) - 1e-6
  );
};

describe("focus_track framing", () => {
  it("padding is 12%", () => {
    expect(CAMERA_CONFIG.padding).toBe(0.12);
  });

  it("tight: the padded box fills ~70% of the view width; medium ~50% (but never below cover)", () => {
    const small = { x: 520, y: 400, w: 400, h: 50 };
    const tight = targetView(entry(0, small.x, small.y, small.w, small.h, "tight"), CLIP, FRAME);
    expect(padded(small.w) / tight.w).toBeCloseTo(0.7, 1);
    const medium = targetView(entry(0, small.x, small.y, small.w, small.h, "medium"), CLIP, FRAME);
    expect(medium.w).toBeGreaterThan(tight.w);
    expect(COVER_W / medium.w).toBeGreaterThanOrEqual(CAMERA_CONFIG.minZoom - 1e-6);
  });

  it("a block wider than the cover window zooms out below cover so no text is cut", () => {
    const block = { x: 200, y: 300, w: 900, h: 250 };
    const v = targetView(entry(0, block.x, block.y, block.w, block.h, "medium"), CLIP, FRAME);
    expect(COVER_W / v.w).toBeLessThan(1); // below cover
    expect(holds(v, block)).toBe(true);
  });

  it("zooms out no further than the whole clip width", () => {
    const v = targetView(entry(0, 0, 0, 1440, 900, "wide"), CLIP, FRAME);
    expect(v.w).toBeLessThanOrEqual(1440 + 1e-6);
    expect(v.w).toBeCloseTo(1440, 3);
  });

  it("a window taller than the clip is centred on it (the backdrop fills the rest)", () => {
    const v = targetView(entry(0, 200, 300, 900, 250, "wide"), CLIP, FRAME);
    expect(v.h).toBeGreaterThan(CLIP.h);
    expect(v.y + v.h / 2).toBeCloseTo(CLIP.h / 2, 3);
  });

  it("a small box inside the clip still never goes below cover and is capped at 1.4", () => {
    const v = targetView(entry(0, 700, 400, 30, 20, "tight"), CLIP, FRAME);
    expect(COVER_W / v.w).toBeCloseTo(CAMERA_CONFIG.maxZoom, 6);
  });

  it("an establish entry is the whole page", () => {
    expect(targetView(entry(0, 0, 0, 10, 10, "establish"), CLIP, FRAME)).toEqual(establishingView(CLIP, FRAME));
  });
});

describe("the camera over a focus_track", () => {
  const track = [
    entry(0, 0, 0, 1440, 900, "establish"),
    entry(1000, 480, 170, 480, 60, "tight"), // the input
    entry(2600, 480, 240, 480, 56, "medium"), // the new item
  ];

  it("starts at the establishing shot and ends framing the last target, fully inside the view", () => {
    const first = focusCameraAt(100, track, CLIP, FRAME);
    expect(first.view).toEqual(establishingView(CLIP, FRAME));
    const last = focusCameraAt(8000, track, CLIP, FRAME);
    expect(holds(last.view, track[2].bbox)).toBe(true);
    expect(last.zoom).toBeGreaterThanOrEqual(CAMERA_CONFIG.minZoom - 1e-6);
  });

  it("while on the input, the input is in view", () => {
    const c = focusCameraAt(2400, track, CLIP, FRAME);
    expect(holds(c.view, track[1].bbox)).toBe(true);
  });

  it("every moment keeps the current target's box in view once the camera has arrived", () => {
    for (const [t, e] of [[2300, track[1]], [5000, track[2]]] as const) {
      expect(holds(focusCameraAt(t, track, CLIP, FRAME).view, e.bbox)).toBe(true);
    }
  });
});

describe("pickFocus", () => {
  const log: FocusLike[] = [{ t_ms: 0, bbox: { x: 0, y: 0, w: 10, h: 10 }, kind: "click" }];
  const trk: FocusLike[] = [entry(0, 0, 0, 10, 10, "tight")];
  const clicks = [{ t_ms: 5, x: 50, y: 60, type: "click" }];

  it("prefers the focus_track, then the focus_log, then the clicks", () => {
    expect(pickFocus({ focus_track: trk, focus_log: log, click_log: clicks })).toBe(trk);
    expect(pickFocus({ focus_log: log, click_log: clicks })).toBe(log);
    expect(pickFocus({ click_log: clicks })[0].bbox.w).toBe(CAMERA_CONFIG.fallbackBox.w);
    expect(pickFocus({ focus_track: [], focus_log: log })).toBe(log);
  });
});
