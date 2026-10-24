// Renders the middle frame of every scene of the sample script to out/stills/scene-<n>-<type>.png.
import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { renderStill, selectComposition } from "@remotion/renderer";
import { COMPOSITION_ID } from "../src/compositionId";
import { buildSampleProps } from "../src/dev/sampleProps";
import { ScriptSchema } from "../src/generated";
import { InputPropsSchema } from "../src/props";
import { OUT_DIR, freePort, getBundle } from "../src/renderer";
import { sceneRanges } from "../src/timing";

const here = path.dirname(fileURLToPath(import.meta.url));
const script = ScriptSchema.parse(
  JSON.parse(readFileSync(path.resolve(here, "../../../packages/script-schema/examples/sample_script.json"), "utf8")),
);
const props = InputPropsSchema.parse(buildSampleProps(script));
const outDir = path.join(OUT_DIR, "stills");
mkdirSync(outDir, { recursive: true });

const serveUrl = await getBundle();
const port = await freePort();
const composition = await selectComposition({ serveUrl, id: COMPOSITION_ID, inputProps: props, port });

for (const [i, r] of sceneRanges(props.script).entries()) {
  const frame = r.from + Math.floor(r.frames / 2);
  const output = path.join(outDir, `scene-${i + 1}-${r.scene.type}.png`);
  await renderStill({ composition, serveUrl, output, frame, inputProps: props, imageFormat: "png", port });
  console.log(`still ${i + 1}: frame ${frame} -> ${output}`);
}
