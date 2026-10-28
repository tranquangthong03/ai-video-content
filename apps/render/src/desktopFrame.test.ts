import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { ScriptSchema } from "./generated";
import { InputPropsSchema, type InputProps } from "./props";
import { boundariesOf, frameCamerasOf } from "./templates/DesktopFrame/cameras";
import { BULLET, CANVAS, CAPTIONS, HEADER, MEDIA } from "./templates/DesktopFrame/layout";
import { FPS, sceneRanges } from "./timing";

const sampleJson = JSON.parse(
  readFileSync(new URL("../../../packages/script-schema/examples/sample_script.json", import.meta.url), "utf8"),
);
const script = ScriptSchema.parse({ ...sampleJson, template: "desktop_frame" });

describe("desktop_frame layout", () => {
  it("is a 16:9 frame, about 96% of the width, right under the header, with captions then bullets below", () => {
    expect(MEDIA.w / MEDIA.h).toBeCloseTo(16 / 9, 6);
    expect(MEDIA.w / CANVAS.w).toBeGreaterThanOrEqual(0.95);
    expect(MEDIA.left * 2 + MEDIA.w).toBe(CANVAS.w);
    expect(HEADER.top + HEADER.height).toBeLessThanOrEqual(MEDIA.top);
    expect(MEDIA.top + MEDIA.h).toBeLessThanOrEqual(CAPTIONS.top);
    expect(CAPTIONS.top + CAPTIONS.height).toBeLessThanOrEqual(BULLET.top);
    expect(BULLET.maxLines).toBe(2);
    expect(BULLET.top + 2 * BULLET.pill + BULLET.gap).toBeLessThanOrEqual(CANVAS.h);
    expect(CAPTIONS.fontSize).toBeGreaterThanOrEqual(56); // large captions
  });
});

/** Assets for every scene of the sample: a 1280x720 clip, with the given zoom shots on the scenes named. */
function assetsWith(shots: Record<string, InputProps["assets"][string]["zoom_shots"]>): InputProps["assets"] {
  const out: InputProps["assets"] = {};
  for (const r of sceneRanges(script, FPS)) {
    out[r.scene.id] = { clip_url: `${r.scene.id}.mp4`, clip_width: 1280, clip_height: 720, clip_duration_ms: 20000, zoom_shots: shots[r.scene.id] };
  }
  return InputPropsSchema.parse({ script, assets: out }).assets;
}

const shot = (from: number, to: number) => ({
  in_start_ms: from,
  in_end_ms: from + 700,
  out_start_ms: to,
  out_end_ms: to + 600,
  box: { x: 300, y: 200, w: 400, h: 240 },
  zoom: 1.7,
  chain_prev: false,
});

describe("desktop_frame hand-over between scenes", () => {
  const ids = sceneRanges(script, FPS).map((r) => r.scene.id);

  it("crossfades only while both cameras stand still on the full view; no shots at all = crossfade everywhere", () => {
    const assets = assetsWith({});
    const cuts = boundariesOf(script, assets, frameCamerasOf(script, assets));
    expect(cuts.length).toBe(ids.length - 1);
    expect(cuts.every((b) => b.crossfade && !b.moving)).toBe(true);
  });

  it("cuts straight (no crossfade) when a scene ends while the camera is zoomed or moving", () => {
    // scene 1 holds a zoom until its very end
    const first = sceneRanges(script, FPS)[0];
    const endMs = (first.frames / FPS) * 1000;
    const assets = assetsWith({ [ids[0]]: [shot(endMs - 1500, endMs + 900)] });
    const cuts = boundariesOf(script, assets, frameCamerasOf(script, assets));
    expect(cuts[0].crossfade).toBe(false);
    expect(cuts[0].moving).toBe(true);
    expect(cuts.slice(1).every((b) => b.crossfade)).toBe(true);
  });

  it("the camera of every scene is still when it has no shot, and returns to the full view after one", () => {
    const assets = assetsWith({ [ids[1]]: [shot(1000, 3000)] });
    const cams = frameCamerasOf(script, assets);
    expect(cams[ids[0]].moving(1500)).toBe(false);
    expect(cams[ids[1]].at(2000).zoom).toBeGreaterThan(1.2);
    expect(cams[ids[1]].at(5000).zoom).toBeCloseTo(1, 6);
  });
});
