import { describe, expect, it } from "vitest";
import { CAMERA_CONFIG } from "./config";
import { coverScale, establishingView, type FocusLike, type View } from "./focus";
import { buildCameraPath, driftView, mergeFocus, moveDuration, smoothstep } from "./path";
import { buildSceneCameras } from "./scene";

const CLIP = { w: 1440, h: 900 };
const FRAME = { w: 1000, h: 1250 };
const FPS = 30;
const COVER_W = FRAME.w / coverScale(CLIP, FRAME);

const track = (t_ms: number, x: number, y: number, w: number, h: number, framing: FocusLike["framing"] = "tight"): FocusLike => ({
  t_ms,
  bbox: { x, y, w, h },
  framing,
  hold_ms: 1500,
});

// a form being filled in, then a button far away, then a result: the shape of a real flow
const FLOW: FocusLike[] = [
  track(0, 0, 0, 1440, 900, "establish"),
  track(2000, 480, 170, 480, 60),
  track(5200, 480, 330, 480, 60),
  track(8400, 1180, 760, 160, 56),
  track(11800, 300, 420, 800, 300, "medium"),
];

const frames = (ms: number) => Array.from({ length: Math.floor((ms / 1000) * FPS) }, (_, i) => (i / FPS) * 1000);
const centreOf = (v: View) => ({ x: v.x + v.w / 2, y: v.y + v.h / 2 });

/** The speeds the Motion QA reads off the video: zoom as |w0/w1 - 1|, pan as the centre's shift over the width. */
function speeds(path: ReturnType<typeof buildCameraPath>, ms: number) {
  let zoom = 0;
  let pan = 0;
  let prev = path.at(0).view;
  for (const t of frames(ms).slice(1)) {
    const v = path.at(t).view;
    zoom = Math.max(zoom, Math.abs(prev.w / v.w - 1));
    const a = centreOf(prev);
    const b = centreOf(v);
    pan = Math.max(pan, Math.hypot(b.x - a.x, b.y - a.y) / v.w);
    prev = v;
  }
  return { zoom, pan };
}

describe("the planned path keeps under the hard speed limits", () => {
  const path = buildCameraPath(FLOW, CLIP, FRAME);
  it("zoom <= 2.5 % and pan <= 1.5 % of the width, on every frame of a whole flow", () => {
    const { zoom, pan } = speeds(path, 15000);
    expect(zoom).toBeLessThanOrEqual(CAMERA_CONFIG.path.maxZoomRate);
    expect(pan).toBeLessThanOrEqual(CAMERA_CONFIG.path.maxPanRate);
    expect(zoom).toBeGreaterThan(0.002); // and it does move: this is not a frozen camera
  });

  it("also with targets crowded together and a big zoom change (the case that snapped before)", () => {
    const crowded = [
      track(0, 0, 0, 1440, 900, "establish"),
      track(1300, 100, 100, 200, 50),
      track(1900, 1100, 700, 200, 50),
      track(2500, 400, 300, 300, 50),
    ];
    const p = buildCameraPath(crowded, CLIP, FRAME);
    const { zoom, pan } = speeds(p, 6000);
    expect(zoom).toBeLessThanOrEqual(CAMERA_CONFIG.path.maxZoomRate);
    expect(pan).toBeLessThanOrEqual(CAMERA_CONFIG.path.maxPanRate);
  });
});

describe("moves", () => {
  it("start before the moment their target is looked at, never before the establishing shot is over", () => {
    const { moves } = buildCameraPath(FLOW, CLIP, FRAME);
    const first = moves[0];
    expect(first.start).toBeGreaterThanOrEqual(CAMERA_CONFIG.establishingMs);
    moves.slice(1).forEach((m, i) => {
      const prevEnd = moves[i].start + moves[i].duration;
      // at least 300 ms before the moment (a long move earlier still), unless the last move was in the way
      expect(m.start <= m.target - 300 + 1 || Math.abs(m.start - prevEnd) < 1).toBe(true);
    });
  });

  it("last 400-900 ms, longer only when a big change needs it to stay under the limits", () => {
    const { moves } = buildCameraPath(FLOW, CLIP, FRAME);
    for (const m of moves) expect(m.duration).toBeGreaterThanOrEqual(CAMERA_CONFIG.path.moveMinMs - 1);
    const small = moveDuration(
      { x: 100, y: 0, w: 720, h: 900 },
      { x: 140, y: 10, w: 700, h: 875 },
      FPS,
      CAMERA_CONFIG,
    );
    expect(small.ms).toBeLessThanOrEqual(CAMERA_CONFIG.path.moveMaxMs);
    const big = moveDuration(establishingView(CLIP, FRAME), { x: 600, y: 300, w: 400, h: 500 }, FPS, CAMERA_CONFIG);
    expect(big.ms).toBeGreaterThan(small.ms);
  });

  it("do not overlap, and a move that cannot fit goes only part of the way instead of snapping", () => {
    const tight = [
      track(0, 0, 0, 1440, 900, "establish"),
      track(1200, 60, 60, 120, 40),
      track(1500, 1250, 780, 120, 40),
    ];
    const p = buildCameraPath(tight, CLIP, FRAME);
    for (let i = 1; i < p.moves.length; i++) expect(p.moves[i].start).toBeGreaterThanOrEqual(p.moves[i - 1].start + p.moves[i - 1].duration - 1);
    expect(speeds(p, 5000).zoom).toBeLessThanOrEqual(CAMERA_CONFIG.path.maxZoomRate);
  });

  it("ease like a smoothstep: slow out of the start, slow into the end", () => {
    expect(smoothstep(0)).toBe(0);
    expect(smoothstep(1)).toBe(1);
    expect(smoothstep(0.1)).toBeLessThan(0.1);
    expect(smoothstep(0.9)).toBeGreaterThan(0.9);
  });
});

describe("holding", () => {
  it("never stands perfectly still: a slow zoom-in of about 1 % a second", () => {
    const p = buildCameraPath(FLOW, CLIP, FRAME);
    const hold = p.moves[0].start + p.moves[0].duration + 100; // inside the hold on the first target
    const next = p.moves[1].start;
    expect(next - hold).toBeGreaterThan(900); // (a whole second of holding to look at)
    const a = p.at(hold).view;
    const b = p.at(hold + 1000).view;
    expect(b.w).toBeLessThan(a.w);
    const rate = 1 - b.w / a.w;
    expect(rate).toBeGreaterThan(0.004);
    expect(rate).toBeLessThan(0.012);
  });

  it("drifts at most to the maximum zoom, and the window stays inside the clip", () => {
    const v = driftView({ x: 100, y: 100, w: COVER_W / 1.39, h: 500 }, { x: 400, y: 300 }, 60_000, CLIP, FRAME, CAMERA_CONFIG);
    expect(COVER_W / v.w).toBeLessThanOrEqual(CAMERA_CONFIG.maxZoom + 1e-6);
    expect(v.x).toBeGreaterThanOrEqual(0);
    expect(v.x + v.w).toBeLessThanOrEqual(CLIP.w + 1e-6);
  });

  it("the establishing shot creeps in too, instead of standing still for a second", () => {
    const p = buildCameraPath(FLOW, CLIP, FRAME);
    expect(p.at(600).view.w).toBeLessThan(p.at(0).view.w);
  });
});

describe("merging", () => {
  it("two close targets within 1.2 s become one path, not a zoom out and in", () => {
    const pair = [track(2000, 480, 170, 300, 60), track(2900, 560, 240, 300, 60)];
    expect(mergeFocus(pair, CLIP)).toHaveLength(1);
    const far = [track(2000, 100, 100, 200, 60), track(2900, 1100, 700, 200, 60)];
    expect(mergeFocus(far, CLIP)).toHaveLength(2); // not near: kept apart
    const late = [track(2000, 480, 170, 300, 60), track(4000, 560, 240, 300, 60)];
    expect(mergeFocus(late, CLIP)).toHaveLength(2); // near but 2 s apart: kept apart
    const p = buildCameraPath([track(0, 0, 0, 1440, 900, "establish"), ...pair], CLIP, FRAME);
    expect(p.moves).toHaveLength(1);
  });
});

describe("continuity", () => {
  it("a scene on the same page starts where the previous one ended, with no establishing shot", () => {
    const one = buildCameraPath(FLOW, CLIP, FRAME, { endMs: 14000 });
    const end = one.endView();
    const next = buildCameraPath([track(500, 480, 600, 400, 60)], CLIP, FRAME, { startView: end });
    expect(next.at(0).view.x).toBeCloseTo(end.x, 3);
    expect(next.at(0).view.w).toBeCloseTo(end.w, 3);
    expect(next.at(0).establishing).toBeCloseTo(one.at(14000).establishing, 3); // no jump back to the whole page
    const fresh = buildCameraPath([track(500, 480, 600, 400, 60)], CLIP, FRAME);
    expect(fresh.at(0).establishing).toBeGreaterThan(0.99); // a new page still opens wide
  });

  it("buildSceneCameras chains scenes flagged as the same page, and opens a hook close", () => {
    const a = { focus_track: FLOW } as never;
    const b = { focus_track: [track(500, 480, 600, 400, 60)], same_page: true } as never;
    const c = { focus_track: [track(500, 480, 600, 400, 60)] } as never;
    const cams = buildSceneCameras(
      [
        { id: "s1", type: "hook", assets: a, clip: CLIP, endMs: 14000 },
        { id: "s2", type: "feature_demo", assets: b, clip: CLIP, endMs: 5000 },
        { id: "s3", type: "feature_demo", assets: c, clip: CLIP, endMs: 5000 },
      ],
      FRAME,
    );
    expect(cams.s1.at(0).view.w).toBeLessThan(CLIP.w * 0.75); // the hook is already close, not on the whole page
    expect(cams.s1.at(0).establishing).toBeLessThan(0.5);
    expect(cams.s2.at(0).view.w).toBeCloseTo(cams.s1.endView().w, 3);
    expect(cams.s3.at(0).establishing).toBeGreaterThan(0.99);
  });
});

describe("holding for a long time", () => {
  it("breathes out again at the maximum zoom instead of standing still", () => {
    const p = buildCameraPath([track(500, 480, 170, 120, 40)], CLIP, FRAME, { closeOpening: true });
    const widths = [20, 40, 60, 80, 100].map((s) => p.at(s * 1000).view.w);
    for (let i = 1; i < widths.length; i++) expect(Math.abs(widths[i] - widths[i - 1])).toBeGreaterThan(1);
    const max = CAMERA_CONFIG.maxZoom;
    for (const w of widths) expect(COVER_W / w).toBeLessThanOrEqual(max + 1e-6);
  });
});
