import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { buildFocusProps, focusSampleScript } from "./dev/sampleProps";
import { ScriptSchema } from "./generated";
import { FocusSchema, InputPropsSchema } from "./props";
import { placeBullets } from "./templates/DesktopShowcase/layout";
import { BULLET, BULLET_AREA_HEIGHT, CANVAS, CAPTION_STRIP, HEADER, MEDIA } from "./templates/DesktopFocus/layout";
import { sceneRanges } from "./timing";

const sampleJson = JSON.parse(
  readFileSync(new URL("../../../packages/script-schema/examples/sample_script.json", import.meta.url), "utf8"),
);
const base = ScriptSchema.parse(sampleJson);
const share = (px: number) => px / CANVAS.h;

describe("desktop_focus layout", () => {
  it("puts the header at 6%-17%, the media frame from ~19% and the bullets at 86%-95% of the height", () => {
    expect(share(HEADER.top)).toBeCloseTo(0.06, 2);
    expect(share(HEADER.top + HEADER.height)).toBeCloseTo(0.17, 2);
    expect(share(MEDIA.top)).toBeCloseTo(0.19, 2);
    expect(share(BULLET.top)).toBeCloseTo(0.86, 2);
    expect(share(BULLET.top + BULLET_AREA_HEIGHT)).toBeLessThanOrEqual(0.95);
  });

  it("the media frame is 4:5, about 1000 x 1250, centred, and everything fits the canvas without overlap", () => {
    expect(MEDIA.w / MEDIA.h).toBeCloseTo(4 / 5, 6);
    expect(MEDIA.left * 2 + MEDIA.w).toBe(CANVAS.w);
    expect(HEADER.top + HEADER.height).toBeLessThanOrEqual(MEDIA.top);
    expect(MEDIA.top + MEDIA.h).toBeLessThanOrEqual(BULLET.top);
    expect(BULLET.top + BULLET_AREA_HEIGHT).toBeLessThanOrEqual(CANVAS.h);
  });

  it("the caption strip sits inside the media frame, on its bottom edge", () => {
    expect(CAPTION_STRIP.height).toBeLessThan(MEDIA.h / 2);
    expect(CAPTION_STRIP.paddingBottom).toBeGreaterThan(0);
  });

  it("shows at most two bullets: a new line pushes the oldest out", () => {
    expect(BULLET.maxLines).toBe(2);
    const starts = [0, 100, 200, 300];
    expect(placeBullets(starts, 150, BULLET.maxLines).map((p) => p.index)).toEqual([0, 1]);
    const later = placeBullets(starts, 200 + 40, BULLET.maxLines);
    expect(later.map((p) => p.index)).toEqual([1, 2]);
    expect(later.map((p) => p.slot)).toEqual([0, 1]);
    expect(placeBullets(starts, 2000, BULLET.maxLines).map((p) => p.index)).toEqual([2, 3]);
  });
});

describe("desktop_focus data", () => {
  it("is a valid template, and the default", () => {
    expect(ScriptSchema.parse({ ...sampleJson, template: "desktop_focus" }).template).toBe("desktop_focus");
    const { template: _t, ...rest } = sampleJson;
    expect(ScriptSchema.parse(rest).template).toBe("desktop_focus");
    expect(ScriptSchema.safeParse({ ...sampleJson, template: "nope" }).success).toBe(false);
  });

  it("accepts a focus log on a scene's assets and rejects an unknown kind", () => {
    const props = InputPropsSchema.parse(buildFocusProps(focusSampleScript(base)));
    const demo = props.assets.s2.focus_log!;
    expect(demo.map((f) => f.kind)).toEqual(["click", "click", "click", "section"]);
    expect(demo.every((f) => f.hold_ms >= 0)).toBe(true);
    expect(FocusSchema.safeParse({ t_ms: 0, bbox: { x: 0, y: 0, w: 10, h: 10 }, kind: "teleport" }).success).toBe(false);
    expect(FocusSchema.safeParse({ t_ms: 0, bbox: { x: 0, y: 0, w: 0, h: 10 }, kind: "click" }).success).toBe(false);
  });

  it("the focus sample has product footage on the hook, the demo and the CTA", () => {
    const props = InputPropsSchema.parse(buildFocusProps(focusSampleScript(base)));
    expect(props.script.template).toBe("desktop_focus");
    const [hook, demo, , cta] = sceneRanges(props.script);
    for (const r of [hook, demo, cta]) {
      const a = props.assets[r.scene.id];
      expect(a.clip_url || a.screenshot_url).toBeTruthy();
      expect(a.focus_log?.length).toBeGreaterThan(0);
    }
  });
});
