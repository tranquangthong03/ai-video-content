// The camera path of a produced job, frame by frame, without rendering: tsx camera-path.ts <render_props.json>
// Prints one JSON object {fps, frame:{w,h}, scenes:[{id, from, frames, clip, start_ms, rate, views:[[x,y,w],...]}]}
// (views are in clip pixels, one per scene frame; the height follows from the frame's aspect ratio).
import { readFileSync } from "node:fs";
import { InputPropsSchema } from "../src/props";
import { clipPlayback } from "../src/templates/DesktopShowcase/playback";
import { camerasOf, MEDIA_FRAME } from "../src/templates/DesktopFocus/cameras";
import { FPS, sceneRanges } from "../src/timing";

const props = InputPropsSchema.parse(JSON.parse(readFileSync(process.argv[2], "utf8")));
const FRAME = MEDIA_FRAME;
const cameras = camerasOf(props.script, props.assets);
const scenes: Record<string, unknown>[] = [];
for (const r of sceneRanges(props.script, FPS)) {
  const a = props.assets[r.scene.id];
  if (!a?.clip_url) continue;
  const clip = { w: a.clip_width ?? 1440, h: a.clip_height ?? 900 };
  const { startMs, rate, lastFrame } = clipPlayback(a, FPS, r.frames);
  const views: number[][] = [];
  const cam = (t: number) => cameras[r.scene.id].at(t);
  for (let f = 0; f < r.frames; f++) {
    const shown = lastFrame === null ? f : Math.min(f, lastFrame);
    const t = startMs + (shown / FPS) * 1000 * rate;
    const v = cam(t).view;
    views.push([+v.x.toFixed(1), +v.y.toFixed(1), +v.w.toFixed(1)]);
  }
  scenes.push({ id: r.scene.id, type: r.scene.type, from: r.from, frames: r.frames, clip: a.clip_url, start_ms: startMs, rate, clip_w: clip.w, clip_h: clip.h, views });
}
console.log(JSON.stringify({ fps: FPS, frame: FRAME, scenes }));
