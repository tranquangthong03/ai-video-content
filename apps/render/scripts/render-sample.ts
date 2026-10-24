// Renders the sample script twice with the dev assets: out/sample_desktop.mp4 (desktop_showcase)
// and out/sample_phone.mp4 (phone_showcase). Run `pnpm assets:dev` first.
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildSampleProps, desktopSampleScript, phoneSampleScript } from "../src/dev/sampleProps";
import { ScriptSchema } from "../src/generated";
import { InputPropsSchema } from "../src/props";
import { OUT_DIR, renderVideo } from "../src/renderer";

const here = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.resolve(here, "../public");
const samplePath = path.resolve(here, "../../../packages/script-schema/examples/sample_script.json");
const HANG_MS = 3 * 60 * 1000;

const t0 = Date.now();
const log = (msg: string) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s] ${msg}`);

const base = ScriptSchema.parse(JSON.parse(readFileSync(samplePath, "utf8")));
const variants = [
  { name: "desktop", script: desktopSampleScript(base), file: "sample_desktop.mp4" },
  { name: "phone", script: phoneSampleScript(base), file: "sample_phone.mp4" },
];

// Watchdog: report the stage if nothing advances for 3 minutes
let stage = "start";
let lastProgress = Date.now();
const watchdog = setInterval(() => {
  if (Date.now() - lastProgress > HANG_MS) {
    console.error(`HANG: no progress for 3 min during stage "${stage}"`);
    process.exit(2);
  }
}, 5000);

for (const v of variants) {
  // Parse props and check assets before touching the browser
  const parsed = InputPropsSchema.safeParse(buildSampleProps(v.script));
  if (!parsed.success) {
    console.error(`${v.name}: props invalid:`, JSON.stringify(parsed.error.issues, null, 2));
    process.exit(1);
  }
  const props = parsed.data;
  const local = Object.values(props.assets).flatMap((a) =>
    [a.clip_url, a.screenshot_url, a.audio_url].filter((u): u is string => Boolean(u) && !/^(https?:|data:|\/)/.test(u!)),
  );
  const missing = local.filter((u) => !existsSync(path.join(publicDir, u)));
  if (missing.length) {
    console.error("missing assets (run `pnpm assets:dev`):", missing);
    process.exit(1);
  }
  log(`${v.name}: props ok (${props.script.scenes.length} scenes, ${local.length} assets)`);

  const started = Date.now();
  const result = await renderVideo(props, path.join(OUT_DIR, v.file), {
    logLevel: "info",
    onStage: (s) => {
      stage = s;
      lastProgress = Date.now();
      log(`${v.name} stage: ${s}`);
    },
  });
  log(`${v.name}: ${result.file} (${result.durationMs}ms video, ${((Date.now() - started) / 1000).toFixed(1)}s total)`);
}
clearInterval(watchdog);
