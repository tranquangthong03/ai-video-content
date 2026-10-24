// Sanity check for trim / playback_rate / freeze_last_frame: renders three stills of the desktop sample's
// demo scene with a clip that is shorter than the scene (out/stills/playback-*.png).
import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { renderStill, selectComposition } from "@remotion/renderer";
import { COMPOSITION_ID } from "../src/compositionId";
import { buildSampleProps, desktopSampleScript } from "../src/dev/sampleProps";
import { ScriptSchema } from "../src/generated";
import { InputPropsSchema } from "../src/props";
import { OUT_DIR, freePort, getBundle } from "../src/renderer";
import { FPS, sceneRanges } from "../src/timing";

const here = path.dirname(fileURLToPath(import.meta.url));
const base = ScriptSchema.parse(
  JSON.parse(readFileSync(path.resolve(here, "../../../packages/script-schema/examples/sample_script.json"), "utf8")),
);
const props = InputPropsSchema.parse(buildSampleProps(desktopSampleScript(base)));
const demoId = props.script.scenes[1].id;
const [, demo] = sceneRanges(props.script);
// the 8s dev clip played at 1.5x after trimming its first 2s: 4s of video for a 7.5s scene
props.assets[demoId] = {
  ...props.assets[demoId],
  trim_start_ms: 2000,
  playback_rate: 1.5,
  freeze_last_frame: true,
  clip_duration_ms: 8000,
};
const outDir = path.join(OUT_DIR, "stills");
mkdirSync(outDir, { recursive: true });
const serveUrl = await getBundle();
const port = await freePort();
const composition = await selectComposition({ serveUrl, id: COMPOSITION_ID, inputProps: props, port });
for (const [name, seconds] of [["start", 0.5], ["mid", 2.0], ["frozen", 6.5]] as const) {
  const frame = demo.from + Math.round(seconds * FPS);
  const output = path.join(outDir, `playback-${name}.png`);
  await renderStill({ composition, serveUrl, output, frame, inputProps: props, imageFormat: "png", port });
  console.log(`${name}: frame ${frame} -> ${output}`);
}
