// desktop_frame metrics of a produced job: tsx frame-metrics.ts <render_props.json>
// Needs produce/inventory/<scene>.json next to the props. While the camera is zoomed on a shot (held,
// after its move in), the UI block the action works in - the smallest card / row / dialog that holds the
// shot's item and is not the whole page - must be whole in the view:
//   container_cut_frames   frames in which that block is cut by the view's edge
//   container_cut_spans    the first cut spans (scene, time, text of the block)
//   zoom_events            zoom-ins planned (shots of all scenes)
// Prints one JSON object.
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { InputPropsSchema } from "../src/props";
import { clipPlayback } from "../src/templates/DesktopShowcase/playback";
import { frameCamerasOf } from "../src/templates/DesktopFrame/cameras";
import { FPS, sceneRanges } from "../src/timing";

type Box = { x: number; y: number; w: number; h: number };
type Item = { id: string; kind: string; text: string; bbox: Box; region: string };
type Snapshot = { t_ms: number; items: Item[] };

const BLOCK_KINDS = new Set(["card", "list_item", "dialog"]);
const MAX_BLOCK_SHARE = 0.75; // a bigger container is the page, not a block
const EPS = 1.5;

const props = InputPropsSchema.parse(JSON.parse(readFileSync(process.argv[2], "utf8")));
const produceDir = dirname(process.argv[2]);
const cameras = frameCamerasOf(props.script, props.assets);

const inside = (outer: Box, inner: Box) =>
  outer.x - EPS <= inner.x && outer.y - EPS <= inner.y && outer.x + outer.w + EPS >= inner.x + inner.w && outer.y + outer.h + EPS >= inner.y + inner.h;

let cutFrames = 0;
let events = 0;
const spans: { scene: string; from_ms: number; to_ms: number; text: string }[] = [];
for (const r of sceneRanges(props.script, FPS)) {
  const a = props.assets[r.scene.id];
  const shots = a?.zoom_shots ?? [];
  const file = join(produceDir, "inventory", `${r.scene.id}.json`);
  if (!a?.clip_url || !shots.length || !existsSync(file)) continue;
  events += shots.length;
  const snaps: Snapshot[] = JSON.parse(readFileSync(file, "utf8")).inventory;
  const clip = { w: a.clip_width ?? 1280, h: a.clip_height ?? 720 };
  const { startMs, rate } = clipPlayback(a, FPS, r.frames);
  for (const s of shots) {
    const snap = snaps.length ? snaps.reduce((b, x) => (Math.abs(x.t_ms - s.in_end_ms) < Math.abs(b.t_ms - s.in_end_ms) ? x : b)) : null;
    const item = snap?.items.find((i) => i.id === s.item_id);
    if (!snap || !item) continue;
    const holders = snap.items.filter(
      (i) => BLOCK_KINDS.has(i.kind) && i.id !== item.id && inside(i.bbox, item.bbox) && i.bbox.w * i.bbox.h <= MAX_BLOCK_SHARE * clip.w * clip.h,
    );
    if (!holders.length) continue;
    const block = holders.reduce((b, x) => (x.bbox.w * x.bbox.h < b.bbox.w * b.bbox.h ? x : b));
    let from = -1;
    for (let f = 0; f < r.frames; f++) {
      const t = startMs + (f / FPS) * 1000 * rate;
      const held = t >= s.in_end_ms && t <= s.out_start_ms;
      const view = cameras[r.scene.id].at(t).view;
      const cut = held && !inside(view, block.bbox);
      if (cut) {
        cutFrames++;
        if (from < 0) from = t;
      } else if (from >= 0) {
        spans.push({ scene: r.scene.id, from_ms: Math.round(from), to_ms: Math.round(t), text: block.text.slice(0, 40) });
        from = -1;
      }
    }
  }
}
console.log(JSON.stringify({ container_cut_frames: cutFrames, container_cut_spans: spans.slice(0, 5), zoom_events: events }));
