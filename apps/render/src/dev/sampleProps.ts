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
