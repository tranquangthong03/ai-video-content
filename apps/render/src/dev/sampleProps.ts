import type { Script } from "../generated";
import type { InputPropsInput } from "../props";

/** Placeholder click log for the dev clip (source pixels of the 780x1688 clip). */
export const DEV_CLICK_LOG = [
  { t_ms: 1500, x: 390, y: 700 },
  { t_ms: 3800, x: 200, y: 1250 },
];

/**
 * Pairs the sample script with the generated files in public/dev-assets.
 * Paths are relative to the bundle's public dir; resolveAsset() turns them into staticFile URLs.
 */
export function buildSampleProps(script: Script): InputPropsInput {
  const [hook, demo] = script.scenes;
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
