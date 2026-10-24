import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { buildSampleProps } from "./dev/sampleProps";
import { ScriptSchema } from "./generated";
import { LAYOUTS_BY_TYPE } from "./generated/layouts";
import { coverFit, mapClipPoint } from "./geometry";
import { InputPropsSchema } from "./props";
import { FallbackScene, SCENES, resolveScene } from "./templates/PhoneShowcase";
import { PHONE_SCREEN } from "./templates/PhoneShowcase/DemoPhone";
import { captionsFromVoiceover, musicVolume, sceneDurationMs, totalFrames } from "./timing";

const sample = ScriptSchema.parse(
  JSON.parse(
    readFileSync(new URL("../../../packages/script-schema/examples/sample_script.json", import.meta.url), "utf8"),
  ),
);

describe("input props", () => {
  it("parses the sample props", () => {
    const props = InputPropsSchema.parse(buildSampleProps(sample));
    expect(props.script.scenes).toHaveLength(4);
    expect(Object.keys(props.assets)).toEqual(["s1", "s2"]);
  });

  it("defaults assets to {} and rejects malformed assets", () => {
    expect(InputPropsSchema.parse({ script: sample }).assets).toEqual({});
    const bad = { script: sample, assets: { s1: { click_log: [{ t_ms: "x" }] } } };
    expect(InputPropsSchema.safeParse(bad).success).toBe(false);
  });
});

describe("durations", () => {
  const scene = (voiceover: string, duration_ms: number | null) => ({ voiceover, duration_ms });

  it("uses duration_ms when set", () => {
    expect(sceneDurationMs(scene("một hai ba", 5000))).toBe(5000);
  });

  it("estimates words / 2.5s with a 2s minimum when duration_ms is null", () => {
    expect(sceneDurationMs(scene("một hai ba", null))).toBe(2000); // 1.2s -> clamped
    expect(sceneDurationMs(scene(Array(10).fill("từ").join(" "), null))).toBe(4000);
  });

  it("sums scene frames at 30fps", () => {
    const withDuration = { scenes: [{ ...sample.scenes[0], duration_ms: 3000 }, { ...sample.scenes[1], duration_ms: 2000 }] };
    expect(totalFrames(withDuration, 30)).toBe(150);
    const estimated = { scenes: [{ ...sample.scenes[0], duration_ms: null }] };
    expect(totalFrames(estimated, 30)).toBeGreaterThanOrEqual(60);
  });
});

describe("scene table", () => {
  it("has a component for every generated layout", () => {
    for (const [type, layouts] of Object.entries(LAYOUTS_BY_TYPE)) {
      for (const layout of layouts) {
        expect(resolveScene(type, layout)).not.toBe(FallbackScene);
        expect((SCENES as Record<string, Record<string, unknown>>)[type][layout]).toBeDefined();
      }
    }
  });

  it("falls back for an unknown layout or type", () => {
    expect(resolveScene("hook", "nope")).toBe(FallbackScene);
    expect(resolveScene("unknown", "full_screen")).toBe(FallbackScene);
  });
});

describe("click geometry", () => {
  const clip = { w: 780, h: 1688 };

  it("cover fit of the 780x1688 clip on the 1080x1920 canvas", () => {
    const fit = coverFit(clip, { w: 1080, h: 1920 });
    // width ratio (1.385) beats height ratio (1.137): fills the width, crops the height
    expect(fit.scale).toBeCloseTo(1080 / 780, 5);
    expect(fit.offsetX).toBeCloseTo(0, 5);
    expect(fit.offsetY).toBeCloseTo((1920 - 1688 * (1080 / 780)) / 2, 5);
  });

  it("maps the clip center to the canvas center (cover)", () => {
    const p = mapClipPoint({ x: 390, y: 844 }, clip, { x: 0, y: 0, w: 1080, h: 1920 });
    expect(p.x).toBeCloseTo(540, 3);
    expect(p.y).toBeCloseTo(960, 3);
  });

  it("maps clip corners with crop offsets (cover)", () => {
    const frame = { x: 0, y: 0, w: 1080, h: 1920 };
    const { scale, offsetX, offsetY } = coverFit(clip, frame);
    expect(mapClipPoint({ x: 0, y: 0 }, clip, frame)).toEqual({ x: offsetX, y: offsetY });
    expect(mapClipPoint({ x: 780, y: 1688 }, clip, frame).x).toBeCloseTo(offsetX + 780 * scale);
  });

  it("maps inside the phone screen frame, including its origin", () => {
    const frame = { x: 100, y: 200, w: PHONE_SCREEN.w, h: PHONE_SCREEN.h };
    const center = mapClipPoint({ x: 390, y: 844 }, clip, frame);
    expect(center.x).toBeCloseTo(100 + PHONE_SCREEN.w / 2, 3);
    expect(center.y).toBeCloseTo(200 + PHONE_SCREEN.h / 2, 3);
  });
});

describe("captions and music", () => {
  it("splits voiceover into timed chunks covering the whole duration", () => {
    const caps = captionsFromVoiceover("một hai ba bốn năm", 5000);
    expect(caps.map((c) => c.text)).toEqual(["một hai ba", "bốn năm"]);
    expect(caps[0].start_ms).toBe(0);
    expect(caps[caps.length - 1].end_ms).toBe(5000);
  });

  it("ducks music during voiceover only", () => {
    const ranges = [{ from: 30, to: 90 }];
    expect(musicVolume(0, ranges)).toBeCloseTo(0.15);
    expect(musicVolume(60, ranges)).toBeCloseTo(0.06);
    expect(musicVolume(200, ranges)).toBeCloseTo(0.15);
  });
});
