import type { Script } from "../generated";
import type { InputPropsInput } from "../props";
import { KARAOKE_WORDS, captionsFromVoiceover } from "../timing";

/** Placeholder click log for the phone dev clip (source pixels of the 780x1688 clip). */
export const DEV_CLICK_LOG = [
  { t_ms: 1500, x: 390, y: 700 },
  { t_ms: 3800, x: 200, y: 1250 },
];

/**
 * Click log of the 1920x1080 desktop dev clip (see scripts/make-desktop-assets.ts, which draws the UI
 * changes at these times). The last two clicks are 0.9s apart so the camera pans between them.
 */
export const DESKTOP_CLICK_LOG = [
  { t_ms: 1200, x: 1560, y: 160, type: "click" as const },
  { t_ms: 3400, x: 765, y: 300, type: "click" as const },
  { t_ms: 4300, x: 1045, y: 300, type: "click" as const },
];

/** Scene durations of the desktop sample, in ms (hook, feature_demo, before_after, cta). */
export const DESKTOP_DURATIONS_MS = [3000, 7500, 4000, 3000];

/** Focus log of the same 1920x1080 dev clip: boxes the camera frames (clip pixels / clip time). */
export const DESKTOP_FOCUS_LOG = [
  { t_ms: 1200, bbox: { x: 1470, y: 125, w: 180, h: 70 }, kind: "click" as const, hold_ms: 1500 },
  { t_ms: 3400, bbox: { x: 640, y: 262, w: 250, h: 76 }, kind: "click" as const, hold_ms: 900 },
  { t_ms: 4300, bbox: { x: 920, y: 262, w: 250, h: 76 }, kind: "click" as const, hold_ms: 1500 },
  { t_ms: 6200, bbox: { x: 480, y: 330, w: 960, h: 480 }, kind: "section" as const, hold_ms: 1500 },
];

/** The sample script as a desktop_focus video (same scenes, durations and captions). */
export function focusSampleScript(base: Script): Script {
  return { ...desktopSampleScript(base), template: "desktop_focus" };
}

/** desktop_focus assets: hook and CTA are product footage too, with focus boxes. */
export function buildFocusProps(script: Script): InputPropsInput {
  const [hook, demo, , cta] = script.scenes;
  const clip = { clip_width: 1920, clip_height: 1080 };
  return {
    script,
    assets: {
      [hook.id]: {
        screenshot_url: "dev-assets/web-1.png",
        ...clip,
        focus_log: [{ t_ms: 0, bbox: { x: 360, y: 180, w: 1200, h: 360 }, kind: "section" as const, hold_ms: 0 }],
      },
      [demo.id]: {
        clip_url: "dev-assets/web-clip.mp4",
        start_offset_ms: 0,
        click_log: DESKTOP_CLICK_LOG,
        focus_log: DESKTOP_FOCUS_LOG,
        ...clip,
        captions: captionsFromVoiceover(demo.voiceover, demo.duration_ms ?? 7500, KARAOKE_WORDS),
      },
      [cta.id]: {
        clip_url: "dev-assets/web-clip.mp4",
        start_offset_ms: 0,
        focus_log: [{ t_ms: 0, bbox: { x: 1470, y: 125, w: 180, h: 70 }, kind: "highlight" as const, hold_ms: 1800 }],
        ...clip,
      },
    },
  };
}

/** The sample script as a desktop_showcase video: karaoke captions, fixed scene durations. */
export function desktopSampleScript(base: Script): Script {
  return {
    ...base,
    template: "desktop_showcase",
    theme: { ...base.theme, caption_style: "karaoke" },
    scenes: base.scenes.map((s, i) => ({ ...s, duration_ms: DESKTOP_DURATIONS_MS[i] ?? s.duration_ms })),
  };
}

/** The same sample as a phone_showcase video. */
export function phoneSampleScript(base: Script): Script {
  return { ...base, template: "phone_showcase" };
}

/**
 * Pairs the sample script with the generated files in public/dev-assets.
 * Paths are relative to the bundle's public dir; resolveAsset() turns them into staticFile URLs.
 */
export function buildSampleProps(script: Script): InputPropsInput {
  const [hook, demo] = script.scenes;
  if (script.template === "phone_showcase") {
    return {
      script,
      assets: {
        [hook.id]: { screenshot_url: "dev-assets/screen-1.png" },
        [demo.id]: {
          clip_url: "dev-assets/clip.mp4",
          start_offset_ms: 0,
          click_log: DEV_CLICK_LOG,
          clip_width: 780,
          clip_height: 1688,
        },
      },
    };
  }
  return {
    script,
    assets: {
      [hook.id]: { screenshot_url: "dev-assets/web-1.png" },
      [demo.id]: {
        clip_url: "dev-assets/web-clip.mp4",
        start_offset_ms: 0,
        click_log: DESKTOP_CLICK_LOG,
        clip_width: 1920,
        clip_height: 1080,
        captions: captionsFromVoiceover(demo.voiceover, demo.duration_ms ?? 7500, KARAOKE_WORDS),
      },
    },
  };
}
