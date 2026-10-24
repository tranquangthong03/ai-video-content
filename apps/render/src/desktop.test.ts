import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { activeWordIndex, wordsOf } from "./captionWords";
import { buildSampleProps, desktopSampleScript, phoneSampleScript } from "./dev/sampleProps";
import { ScriptSchema, ThemeSchema } from "./generated";
import { ICON_NAMES, ICON_PATHS } from "./icons";
import { InputPropsSchema } from "./props";
import { ensureYuv420p, probePixelFormat } from "./pixelFormat";
import { sourceHash } from "./renderer";
import { BULLET, MEDIA, placeBullets, splitHeadline } from "./templates/DesktopShowcase/layout";
import { productNameOf } from "./templates/DesktopShowcase/DesktopVideo";
import { captionsFromVoiceover, sceneRanges } from "./timing";

const sampleJson = JSON.parse(
  readFileSync(new URL("../../../packages/script-schema/examples/sample_script.json", import.meta.url), "utf8"),
);
const base = ScriptSchema.parse(sampleJson);

describe("script fields for the desktop template", () => {
  it("parses the sample with template, capture, badge, headline and key points", () => {
    expect(base.template).toBe("desktop_showcase");
    expect(base.capture).toEqual({ viewport: "desktop", width: 1920, height: 1080 });
    expect(base.badge).toBe("Quản lý dự án");
    expect(base.headline_highlight).toBe("nhanh gấp đôi");
    for (const s of base.scenes) {
      expect(s.key_point).toBeTruthy();
      expect(s.icon).toBeTruthy();
    }
  });

  it("applies defaults for template, capture, badge and highlight", () => {
    const { template: _t, capture: _c, badge: _b, headline_highlight: _h, ...rest } = sampleJson;
    const parsed = ScriptSchema.parse(rest);
    expect(parsed.template).toBe("desktop_showcase");
    expect(parsed.capture.width).toBe(1920);
    expect(parsed.badge).toBeNull();
    expect(parsed.headline_highlight).toBeNull();
  });

  it("enforces the length limits and the enums", () => {
    const bad = (patch: object) => ScriptSchema.safeParse({ ...sampleJson, ...patch }).success;
    expect(bad({ headline: "x".repeat(41) })).toBe(false);
    expect(bad({ badge: "x".repeat(25) })).toBe(false);
    expect(bad({ headline: undefined })).toBe(false);
    expect(bad({ template: "tablet_showcase" })).toBe(false);
    const withScene = (patch: object) => ({
      ...sampleJson,
      scenes: [{ ...sampleJson.scenes[0], ...patch }, ...sampleJson.scenes.slice(1)],
    });
    expect(ScriptSchema.safeParse(withScene({ key_point: "x".repeat(61) })).success).toBe(false);
    expect(ScriptSchema.safeParse(withScene({ icon: "rocket" })).success).toBe(false);
    expect(ScriptSchema.safeParse(withScene({ icon: null, key_point: null })).success).toBe(true);
  });

  it("accepts the karaoke caption style", () => {
    expect(ThemeSchema.safeParse({ ...sampleJson.theme, caption_style: "karaoke" }).success).toBe(true);
    expect(ThemeSchema.safeParse({ ...sampleJson.theme, caption_style: "neon" }).success).toBe(false);
  });
});

describe("headline highlight", () => {
  it("splits the headline around the highlighted phrase", () => {
    expect(splitHeadline("Quản lý công việc nhanh gấp đôi", "nhanh gấp đôi")).toEqual({
      before: "Quản lý công việc ",
      mark: "nhanh gấp đôi",
      after: "",
    });
  });

  it("leaves the headline plain without a highlight or when it is not a substring", () => {
    expect(splitHeadline("Xin chào", null).mark).toBeNull();
    expect(splitHeadline("Xin chào", "tạm biệt")).toEqual({ before: "Xin chào", mark: null, after: "" });
  });
});

describe("bullets", () => {
  const starts = [0, 90, 180, 270, 360, 450];

  it("shows only the scenes that have started, newest at the bottom", () => {
    const placed = placeBullets(starts, 100);
    expect(placed.map((p) => p.index)).toEqual([0, 1]);
    expect(placed[1].slot).toBe(1);
    expect(placeBullets(starts, -1)).toEqual([]);
  });

  it("fades and slides a new pill in", () => {
    const first = placeBullets(starts, 91).find((p) => p.index === 1)!;
    const done = placeBullets(starts, 90 + BULLET.slideFrames).find((p) => p.index === 1)!;
    expect(first.opacity).toBeLessThan(0.3);
    expect(first.enter).toBeLessThan(0.3);
    expect(done.opacity).toBe(1);
    expect(done.enter).toBe(1);
  });

  it("keeps at most four lines: the oldest scrolls up and fades out when a fifth arrives", () => {
    const before = placeBullets(starts, 359);
    expect(before.map((p) => p.index)).toEqual([0, 1, 2, 3]);
    const mid = placeBullets(starts, 360 + 6).find((p) => p.index === 0)!;
    expect(mid.opacity).toBeGreaterThan(0);
    expect(mid.opacity).toBeLessThan(1);
    expect(mid.slot).toBeLessThan(0);
    const after = placeBullets(starts, 360 + BULLET.slideFrames + 1);
    expect(after.map((p) => p.index)).toEqual([1, 2, 3, 4]);
    expect(after.map((p) => p.slot)).toEqual([0, 1, 2, 3]);
    expect(placeBullets(starts, 1000).map((p) => p.index)).toEqual([2, 3, 4, 5]);
  });
});

describe("icons", () => {
  it("draws every icon the schema allows, and nothing else", () => {
    const allowed = ["check", "globe", "bolt", "link", "star", "users", "chart", "lock", "sparkles", "code", "image", "edit", "filter", "upload"];
    expect([...ICON_NAMES].sort()).toEqual([...allowed].sort());
    for (const name of ICON_NAMES) expect(ICON_PATHS[name].length).toBeGreaterThan(0);
  });
});

describe("caption words", () => {
  it("splits a group over its words by character count when it has no timestamps", () => {
    const words = wordsOf({ text: "ab cdef", start_ms: 0, end_ms: 600 });
    expect(words.map((w) => w.text)).toEqual(["ab", "cdef"]);
    expect(words[0]).toMatchObject({ start_ms: 0, end_ms: 200 });
    expect(words[1]).toMatchObject({ start_ms: 200, end_ms: 600 });
  });

  it("prefers the timestamps it was given", () => {
    const given = [{ text: "xin", start_ms: 0, end_ms: 100 }, { text: "chào", start_ms: 100, end_ms: 900 }];
    expect(wordsOf({ text: "xin chào", start_ms: 0, end_ms: 900, words: given })).toBe(given);
  });

  it("finds the word being spoken", () => {
    const words = wordsOf({ text: "a b c", start_ms: 0, end_ms: 300 });
    expect([-5, 0, 150, 250, 999].map((ms) => activeWordIndex(words, ms))).toEqual([-1, 0, 1, 2, 2]);
  });

  it("generated captions carry words, in groups of the requested size", () => {
    const caps = captionsFromVoiceover("một hai ba bốn năm sáu bảy", 7000, 4);
    expect(caps.map((c) => c.words?.length)).toEqual([4, 3]);
    expect(caps[0].words?.[0]).toMatchObject({ text: "một", start_ms: 0, end_ms: 1000 });
    expect(caps[1].end_ms).toBe(7000);
  });
});

describe("desktop sample", () => {
  const props = InputPropsSchema.parse(buildSampleProps(desktopSampleScript(base)));

  it("uses karaoke captions, fixed durations and a click log with a close pair", () => {
    expect(props.script.template).toBe("desktop_showcase");
    expect(props.script.theme.caption_style).toBe("karaoke");
    expect(sceneRanges(props.script).map((r) => r.frames)).toEqual([90, 225, 120, 90]);
    const clicks = props.assets.s2.click_log!;
    expect(clicks).toHaveLength(3);
    expect(clicks[2].t_ms - clicks[1].t_ms).toBeLessThan(1500);
    expect(props.assets.s2.captions!.every((c) => (c.words?.length ?? 0) >= 1)).toBe(true);
  });

  it("the phone sample keeps the phone clip", () => {
    const phone = InputPropsSchema.parse(buildSampleProps(phoneSampleScript(base)));
    expect(phone.script.template).toBe("phone_showcase");
    expect(phone.assets.s2.clip_width).toBe(780);
  });

  it("the media frame is 16:9 and 92% of the canvas width", () => {
    expect(MEDIA.w).toBe(994);
    expect(Math.abs(MEDIA.w / MEDIA.h - 16 / 9)).toBeLessThan(0.01);
  });

  it("names the product from the script title", () => {
    expect(productNameOf("TaskFlow - Quản lý công việc không còn rối")).toBe("TaskFlow");
    expect(productNameOf("Chỉ một tên")).toBe("Chỉ một tên");
  });
});

describe("pixel format fix", () => {
  const hasFfmpeg = spawnSync("ffmpeg", ["-version"]).status === 0;

  it.skipIf(!hasFfmpeg)("re-encodes a full-range yuvj420p file to yuv420p and leaves yuv420p alone", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "pixfmt-"));
    const file = path.join(dir, "in.mp4");
    const make = (pix: string) =>
      spawnSync("ffmpeg", ["-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=1", "-pix_fmt", pix, "-c:v", "libx264", file]);
    make("yuvj420p");
    expect(probePixelFormat(file)).toBe("yuvj420p");
    expect(ensureYuv420p(file)).toBe("yuv420p");
    expect(probePixelFormat(file)).toBe("yuv420p");
    const before = statSync(file).mtimeMs;
    expect(ensureYuv420p(file)).toBe("yuv420p"); // already fine: untouched
    expect(statSync(file).mtimeMs).toBe(before);
    rmSync(dir, { recursive: true, force: true });
  });
});

describe("bundle cache key", () => {
  it("is stable across calls", () => {
    expect(sourceHash()).toBe(sourceHash());
    expect(sourceHash()).toMatch(/^[0-9a-f]{16}$/);
  });
});
