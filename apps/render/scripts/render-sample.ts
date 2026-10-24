// Renders packages/script-schema/examples/sample_script.json with the dev assets to out/sample.mp4.
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildSampleProps } from "../src/dev/sampleProps";
import { ScriptSchema } from "../src/generated";
import { InputPropsSchema } from "../src/props";
import { OUT_DIR, renderVideo } from "../src/renderer";

const here = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.resolve(here, "../public");
const samplePath = path.resolve(here, "../../../packages/script-schema/examples/sample_script.json");
const HANG_MS = 3 * 60 * 1000;

const t0 = Date.now();
const log = (msg: string) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s] ${msg}`);

// 1. Props: parse before touching the browser
const parsed = InputPropsSchema.safeParse(
  buildSampleProps(ScriptSchema.parse(JSON.parse(readFileSync(samplePath, "utf8")))),
);
if (!parsed.success) {
  console.error("props invalid:", JSON.stringify(parsed.error.issues, null, 2));
  process.exit(1);
}
const props = parsed.data;
log(`props ok: ${props.script.scenes.length} scenes`);

// 2. Assets: every local path referenced by props must exist in public/
const local = Object.values(props.assets).flatMap((a) =>
  [a.clip_url, a.screenshot_url, a.audio_url].filter((u): u is string => Boolean(u) && !/^(https?:|data:|\/)/.test(u!)),
);
const missing = local.filter((u) => !existsSync(path.join(publicDir, u)));
if (missing.length) {
  console.error("missing assets (run `pnpm assets:dev`):", missing);
  process.exit(1);
}
log(`assets ok: ${local.length} files`);

// 3. Watchdog: report the stage if nothing advances for 3 minutes
let stage = "start";
let lastProgress = Date.now();
const watchdog = setInterval(() => {
  if (Date.now() - lastProgress > HANG_MS) {
    console.error(`HANG: no progress for 3 min during stage "${stage}"`);
    process.exit(2);
  }
}, 5000);

const result = await renderVideo(props, path.join(OUT_DIR, "sample.mp4"), {
  logLevel: "verbose",
  onStage: (s) => {
    stage = s;
    lastProgress = Date.now();
    log(`stage: ${s}`);
  },
}).finally(() => clearInterval(watchdog));
log(`done: ${result.file} (${result.durationMs}ms video, rendered in ${result.renderMs}ms)`);
