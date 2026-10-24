// Camera metrics of a produced job: node camera-metrics.ts <render_props.json>
// For every recorded scene, how long the focus camera is at or above cover (zoom >= 1.0), not counting the
// establishing shot at the start of each clip. Prints one JSON object.
import { readFileSync } from "node:fs";
import { CAMERA_CONFIG, establishingEndMs, focusCameraAt, focusFromClicks } from "../src/camera";
import { InputPropsSchema } from "../src/props";
import { clipPlayback } from "../src/templates/DesktopShowcase/playback";
import { FPS, sceneRanges } from "../src/timing";
import { MEDIA } from "../src/templates/DesktopFocus/layout";

const props = InputPropsSchema.parse(JSON.parse(readFileSync(process.argv[2], "utf8")));
const FRAME = { w: MEDIA.w, h: MEDIA.h };
const scenes: Record<string, unknown>[] = [];
let framesTotal = 0;
let framesCover = 0;
let zoomSum = 0;
for (const r of sceneRanges(props.script, FPS)) {
  const a = props.assets[r.scene.id];
  if (!a?.clip_url) continue;
  const clip = { w: a.clip_width ?? 1440, h: a.clip_height ?? 900 };
  const focus = a.focus_log?.length ? a.focus_log : focusFromClicks(a.click_log ?? []);
  const { startMs, rate, lastFrame } = clipPlayback(a, FPS, r.frames);
  let total = 0;
  let cover = 0;
  let zoom = 0;
  for (let f = 0; f < r.frames; f++) {
    const shown = lastFrame === null ? f : Math.min(f, lastFrame);
    const t = (shown / FPS) * 1000 * rate; // clip time after the shown start
    const cam = focusCameraAt(startMs + t, focus, clip, FRAME);
    if (t < establishingEndMs()) continue; // establishing shot and the move out of it
    total++;
    zoom += cam.zoom;
    if (cam.zoom >= CAMERA_CONFIG.minZoom - 1e-6) cover++;
  }
  framesTotal += total;
  framesCover += cover;
  zoomSum += zoom;
  scenes.push({ id: r.scene.id, seconds: +(total / FPS).toFixed(2), cover_share: total ? +(cover / total).toFixed(3) : null, mean_zoom: total ? +(zoom / total).toFixed(3) : null });
}
console.log(
  JSON.stringify({
    cover_share: framesTotal ? +(framesCover / framesTotal).toFixed(3) : null,
    mean_zoom: framesTotal ? +(zoomSum / framesTotal).toFixed(3) : null,
    footage_seconds: +(framesTotal / FPS).toFixed(1),
    scenes,
  }),
);
