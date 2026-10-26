import { describe, expect, it } from "vitest";
import {
  CAMERA_CONFIG,
  coverScale,
  coverShare,
  establishingEndMs,
  establishingView,
  focusCameraAt,
  focusFromClicks,
  targetView,
  viewTransform,
  type FocusLike,
} from "./index";

const CLIP = { w: 1440, h: 900 };
const FRAME = { w: 1000, h: 1250 }; // 4:5 media frame
const COVER_W = FRAME.w / coverScale(CLIP, FRAME); // clip width visible at cover: 720
const fp = (t_ms: number, x: number, y: number, w: number, h: number, kind: FocusLike["kind"] = "click"): FocusLike => ({
  t_ms,
  bbox: { x, y, w, h },
  kind,
  hold_ms: 1500,
});
const LOG: FocusLike[] = [
  fp(2000, 100, 120, 260, 60), // a field on the left
  fp(4500, 900, 600, 220, 70), // a button on the right, lower
  fp(7000, 500, 300, 400, 300, "section"),
  fp(9000, 1100, 100, 200, 60, "hover"),
];
const cam = (t: number, log = LOG) => focusCameraAt(t, log, CLIP, FRAME);
const centre = (v: { x: number; y: number; w: number; h: number }) => ({ x: v.x + v.w / 2, y: v.y + v.h / 2 });

describe("geometry of the cover unit", () => {
  it("cover shows the whole clip height: a 720 px wide window of the 1440 px clip", () => {
    expect(coverScale(CLIP, FRAME)).toBeCloseTo(1250 / 900, 6);
    expect(COVER_W).toBeCloseTo(720, 3);
  });

  it("the establishing view is the full clip width, taller than the clip, same aspect as the frame", () => {
    const v = establishingView(CLIP, FRAME);
    expect(v.w).toBe(1440);
    expect(v.h / v.w).toBeCloseTo(FRAME.h / FRAME.w, 6);
    expect(v.h).toBeGreaterThan(CLIP.h);
    expect(centre(v)).toEqual({ x: 720, y: 450 });
  });

  it("viewTransform maps the view corners onto the frame corners", () => {
    const v = { x: 200, y: 50, w: 600, h: 750 };
    const t = viewTransform(v, FRAME);
    expect(v.x * t.scale + t.translateX).toBeCloseTo(0, 6);
    expect((v.x + v.w) * t.scale + t.translateX).toBeCloseTo(FRAME.w, 6);
    expect((v.y + v.h) * t.scale + t.translateY).toBeCloseTo(FRAME.h, 6);
  });
});

describe("framing a target", () => {
  it("a small box fills ~70% of the view width, padding included, and is centred", () => {
    const v = targetView(fp(0, 600, 400, 280, 80), CLIP, FRAME);
    const padded = 280 * (1 + 2 * CAMERA_CONFIG.padding);
    expect(padded / v.w).toBeCloseTo(0.7, 1);
    expect(centre(v).x).toBeCloseTo(740, 3);
  });

  it("a tiny box is limited to the maximum zoom (1.4 cover)", () => {
    const v = targetView(fp(0, 700, 400, 30, 20), CLIP, FRAME);
    expect(COVER_W / v.w).toBeCloseTo(CAMERA_CONFIG.maxZoom, 6);
    expect(CAMERA_CONFIG.maxZoom).toBe(1.4);
  });

  it("a box wider than the view keeps the minimum zoom (cover) and is centred on it", () => {
    const v = targetView(fp(0, 300, 100, 1000, 700, "section"), CLIP, FRAME);
    expect(COVER_W / v.w).toBeCloseTo(CAMERA_CONFIG.minZoom, 6);
    expect(centre(v).x).toBeCloseTo(800, 3); // the box centre, the window fits inside the clip
    expect(v.y).toBeGreaterThanOrEqual(0);
  });

  it("hover and scroll zoom less than a click on the same box", () => {
    const box = { x: 500, y: 400, w: 300, h: 100 };
    const click = targetView({ t_ms: 0, bbox: box, kind: "click" }, CLIP, FRAME);
    const hover = targetView({ t_ms: 0, bbox: box, kind: "hover" }, CLIP, FRAME);
    const scroll = targetView({ t_ms: 0, bbox: box, kind: "scroll" }, CLIP, FRAME);
    expect(hover.w).toBeGreaterThan(click.w);
    expect(scroll.w).toBeGreaterThanOrEqual(hover.w);
  });

  it("the view stays inside the clip even for a box in the corner", () => {
    const v = targetView(fp(0, 1380, 860, 50, 30), CLIP, FRAME);
    expect(v.x + v.w).toBeLessThanOrEqual(1440 + 1e-6);
    expect(v.y + v.h).toBeLessThanOrEqual(900 + 1e-6);
    expect(v.x).toBeGreaterThanOrEqual(0);
  });
});

describe("focusCameraAt", () => {
  it("starts with the establishing shot and holds it for the first second", () => {
    for (const t of [0, 400, 990]) {
      const c = cam(t);
      expect(c.view).toEqual(establishingView(CLIP, FRAME));
      expect(c.establishing).toBeCloseTo(1, 6);
      expect(c.zoom).toBeCloseTo(0.5, 6); // 720 / 1440
    }
  });

  it("then moves to the first target and arrives within the transition time", () => {
    const first = targetView(LOG[0], CLIP, FRAME);
    expect(cam(1000 + 100).establishing).toBeLessThan(1);
    const arrived = cam(establishingEndMs());
    expect(arrived.view.w).toBeCloseTo(first.w, 3);
    expect(arrived.view.x).toBeCloseTo(first.x, 1);
  });

  it("is never below cover once the establishing shot is over, over a long sweep", () => {
    const end = establishingEndMs();
    for (let t = end; t <= 12000; t += 16) {
      const c = cam(t);
      expect(c.zoom).toBeGreaterThanOrEqual(CAMERA_CONFIG.minZoom - 1e-6);
      expect(c.zoom).toBeLessThanOrEqual(CAMERA_CONFIG.maxZoom + 1e-6);
      expect(c.establishing).toBe(0);
    }
    expect(coverShare(LOG, CLIP, FRAME, end, 12000)).toBe(1);
  });

  it("always stays inside the clip after the establishing shot", () => {
    for (let t = establishingEndMs(); t <= 12000; t += 25) {
      const v = cam(t).view;
      expect(v.x).toBeGreaterThanOrEqual(-1e-6);
      expect(v.y).toBeGreaterThanOrEqual(-1e-6);
      expect(v.x + v.w).toBeLessThanOrEqual(CLIP.w + 1e-6);
      expect(v.y + v.h).toBeLessThanOrEqual(CLIP.h + 1e-6);
    }
  });

  it("moves between targets smoothly: no jump larger than a frame's worth of a spring", () => {
    let prev = cam(0);
    let maxCentre = 0;
    let maxLogZoom = 0;
    for (let t = 33; t <= 12000; t += 33) {
      const c = cam(t);
      maxCentre = Math.max(maxCentre, Math.hypot(centre(c.view).x - centre(prev.view).x, centre(c.view).y - centre(prev.view).y));
      maxLogZoom = Math.max(maxLogZoom, Math.abs(Math.log(c.zoom / prev.zoom)));
      prev = c;
    }
    // a critically damped spring never moves more than ~15% of the whole move in one 30 fps frame
    const views = [establishingView(CLIP, FRAME), ...LOG.map((p) => targetView(p, CLIP, FRAME))];
    const longest = Math.max(
      ...views.slice(1).map((v, i) => Math.hypot(centre(v).x - centre(views[i]).x, centre(v).y - centre(views[i]).y)),
    );
    expect(maxCentre / longest).toBeLessThan(0.17);
    const widest = Math.max(...views.slice(1).map((v, i) => Math.abs(Math.log(v.w / views[i].w))));
    expect(maxLogZoom / widest).toBeLessThan(0.17);
  });

  it("is continuous in time (the same value just before and after a hand-over)", () => {
    const start2 = LOG[1].t_ms - CAMERA_CONFIG.leadMs;
    const a = cam(start2 - 1).view;
    const b = cam(start2 + 1).view;
    expect(Math.abs(a.x - b.x)).toBeLessThan(2);
    expect(Math.abs(a.w - b.w)).toBeLessThan(2);
  });

  it("without any focus it rests on the centre at cover after the establishing shot", () => {
    const c = focusCameraAt(establishingEndMs() + 500, [], CLIP, FRAME);
    expect(c.zoom).toBeCloseTo(1, 3);
    expect(centre(c.view).x).toBeCloseTo(720, 1);
  });

  it("targets closer together than the minimum segment are merged, not jittered", () => {
    const burst = [fp(2000, 200, 200, 100, 50), fp(2050, 210, 205, 100, 50), fp(2100, 220, 210, 100, 50)];
    let prev = focusCameraAt(1800, burst, CLIP, FRAME);
    for (let t = 1833; t < 4000; t += 33) {
      const c = focusCameraAt(t, burst, CLIP, FRAME);
      expect(Math.abs(c.view.x - prev.view.x)).toBeLessThan(40);
      prev = c;
    }
  });
});

describe("fallback to the click log", () => {
  it("turns clicks into boxes around them and ignores scrolls", () => {
    const f = focusFromClicks([
      { t_ms: 1000, x: 500, y: 300, type: "click" },
      { t_ms: 2000, x: 800, y: 600, type: "scroll" },
      { t_ms: 3000, x: 900, y: 500 },
      { t_ms: 4000, x: 100, y: 100, type: "hover" },
    ]);
    expect(f.map((p) => p.kind)).toEqual(["click", "click", "hover"]);
    expect(f[0].bbox).toEqual({ x: 360, y: 230, w: 280, h: 140 });
  });

  it("the camera works from a click log alone and is never below cover afterwards", () => {
    const f = focusFromClicks([
      { t_ms: 2000, x: 400, y: 200, type: "click" },
      { t_ms: 5000, x: 1000, y: 700, type: "click" },
    ]);
    for (let t = establishingEndMs(); t <= 8000; t += 40) {
      expect(focusCameraAt(t, f, CLIP, FRAME).zoom).toBeGreaterThanOrEqual(1 - 1e-6);
    }
  });
});

describe("a hook that opens close", () => {
  it("starts on its first target instead of the establishing shot of the whole page", () => {
    const opening = focusCameraAt(0, LOG, CLIP, FRAME, CAMERA_CONFIG, true);
    expect(opening.establishing).toBe(0);
    expect(opening.view.w).toBeCloseTo(targetView(LOG[0], CLIP, FRAME, CAMERA_CONFIG).w, 3);
    expect(cam(0).establishing).toBeGreaterThan(0.99); // the normal clip still opens wide
  });

  it("without any focus it falls back to the usual opening", () => {
    expect(focusCameraAt(0, [], CLIP, FRAME, CAMERA_CONFIG, true).establishing).toBeGreaterThan(0.99);
  });
});
