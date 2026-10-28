// The camera path of a produced job, frame by frame, without rendering: tsx camera-path.ts <render_props.json>
// Prints one JSON object {fps, template, frame:{w,h}, scenes:[{id, from, frames, clip, start_ms, rate, full_w, views:[[x,y,w],...]}], boundaries}
// (views are in clip pixels, one per scene frame; the height follows from the frame's aspect ratio).
// full_w: the width of the view that shows the whole page (the full view). boundaries (desktop_frame): how each
// scene hands over to the next, and how many of the blended frames of a crossfade had a camera moving.
import { readFileSync } from "node:fs";
import { fullView } from "../src/camera";
import { InputPropsSchema } from "../src/props";
import { clipPlayback } from "../src/templates/DesktopShowcase/playback";
import { camerasOf, MEDIA_FRAME } from "../src/templates/DesktopFocus/cameras";
import { boundariesOf, FRAME_CROSSFADE_FRAMES, frameCamerasOf, MEDIA_FRAME as FRAME_TEMPLATE_FRAME } from "../src/templates/DesktopFrame/cameras";
import { FPS, sceneRanges } from "../src/timing";

const props = InputPropsSchema.parse(JSON.parse(readFileSync(process.argv[2], "utf8")));
const still = props.script.template === "desktop_frame";
const FRAME = still ? FRAME_TEMPLATE_FRAME : MEDIA_FRAME;
const cameras = still ? frameCamerasOf(props.script, props.assets) : camerasOf(props.script, props.assets);
const scenes: Record<string, unknown>[] = [];
const ranges = sceneRanges(props.script, FPS);
const tCam = (i: number, f: number) => {
  const a = props.assets[ranges[i].scene.id];
  const { startMs, rate } = clipPlayback(a, FPS, ranges[i].frames);
  return startMs + (f / FPS) * 1000 * rate;
};
for (const r of ranges) {
  const a = props.assets[r.scene.id];
  if (!a?.clip_url) continue;
  const clip = { w: a.clip_width ?? 1440, h: a.clip_height ?? 900 };
  const { startMs, rate } = clipPlayback(a, FPS, r.frames);
  const views: number[][] = [];
  const cam = (t: number) => cameras[r.scene.id].at(t);
  for (let f = 0; f < r.frames; f++) {
    const v = cam(startMs + (f / FPS) * 1000 * rate).view; // the camera's own clock runs on past a frozen frame
    views.push([+v.x.toFixed(1), +v.y.toFixed(1), +v.w.toFixed(1)]);
  }
  const fullW = still ? fullView(clip, FRAME).w : clip.w;
  scenes.push({ id: r.scene.id, type: r.scene.type, from: r.from, frames: r.frames, clip: a.clip_url, start_ms: startMs, rate, clip_w: clip.w, clip_h: clip.h, full_w: +fullW.toFixed(1), views });
}

// desktop_frame: the hand-over of every pair of scenes; a crossfade over a moving camera is a ghost image
const boundaries: Record<string, unknown>[] = [];
if (still) {
  const moved = (i: number, from: number, to: number) => {
    const id = ranges[i].scene.id;
    if (!cameras[id]) return 0;
    let n = 0;
    let prev = cameras[id].at(tCam(i, from)).view;
    for (let f = from + 1; f <= to; f++) {
      const v = cameras[id].at(tCam(i, f)).view;
      if (Math.abs(v.w / prev.w - 1) > 1e-4 || Math.hypot(v.x - prev.x, v.y - prev.y) / prev.w > 1e-4) n++;
      prev = v;
    }
    return n;
  };
  for (const b of boundariesOf(props.script, props.assets, cameras)) {
    const out: Record<string, unknown> = { ...b };
    if (b.crossfade) {
      const a = ranges[b.index];
      // scene i runs on for the overlap, scene i+1 plays its first frames: both are on screen blended
      out.moving_frames = moved(b.index, a.frames - 1, a.frames - 1 + FRAME_CROSSFADE_FRAMES) + moved(b.index + 1, 0, FRAME_CROSSFADE_FRAMES);
    }
    boundaries.push(out);
  }
}
console.log(JSON.stringify({ fps: FPS, template: props.script.template, frame: FRAME, scenes, boundaries }));
