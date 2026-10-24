// Renders stills of the desktop sample into out/stills/desktop/: start of the video (Vietnamese headline),
// hook, demo between two zooms, demo zoomed in with the cursor, before/after and CTA.
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
const outDir = path.join(OUT_DIR, "stills", "desktop");
mkdirSync(outDir, { recursive: true });

const [hook, demo, beforeAfter, cta] = sceneRanges(props.script);
const at = (from: number, seconds: number) => from + Math.round(seconds * FPS);
const stills: [string, number][] = [
  ["01-start", at(0, 1.0)],
  ["02-hook", at(hook.from, 1.5)],
  ["03-demo-between-zooms", at(demo.from, 3.1)],
  ["04-demo-zoomed", at(demo.from, 4.3)],
  ["05-before-after", at(beforeAfter.from, 2.0)],
  ["06-cta", at(cta.from, 1.5)],
];

const serveUrl = await getBundle();
const port = await freePort();
const composition = await selectComposition({ serveUrl, id: COMPOSITION_ID, inputProps: props, port });

for (const [name, frame] of stills) {
  const output = path.join(outDir, `${name}.png`);
  await renderStill({ composition, serveUrl, output, frame, inputProps: props, imageFormat: "png", port });
  console.log(`still ${name}: frame ${frame} -> ${output}`);
}

// Optional fields left empty: no badge, no highlighted phrase, a bullet without an icon
const bare = InputPropsSchema.parse({
  ...props,
  script: {
    ...props.script,
    badge: null,
    headline_highlight: null,
    scenes: props.script.scenes.map((s, i) => (i === 1 ? { ...s, icon: null } : s)),
  },
});
const output = path.join(outDir, "07-no-badge-no-highlight-no-icon.png");
const bareComposition = await selectComposition({ serveUrl, id: COMPOSITION_ID, inputProps: bare, port });
await renderStill({
  composition: bareComposition,
  serveUrl,
  output,
  frame: at(beforeAfter.from, 2.0),
  inputProps: bare,
  imageFormat: "png",
  port,
});
console.log(`still 07: ${output}`);
