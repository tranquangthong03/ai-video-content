// Focus metrics of a produced job: tsx focus-metrics.ts <render_props.json>
// Needs produce/inventory/<scene>.json next to the props (frame_inventory of every recorded scene).
// For every frame of a recorded scene, once the camera has arrived at the current focus_track target:
//   frames_text_clipped      the focus's own text (the chosen item and, for a field, its label) cut by the view's edge
//   clipped_spans            the 5 longest runs of such frames: scene, time, the text that was cut, the view
//   frames_any_text_clipped  any text item of the page cut by the view's edge (for reference)
//   image_zoom_inside        image/media focus targets whose whole image is NOT in the view (zoomed into it)
// Prints one JSON object.
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { focusCameraAt, pickFocus } from "../src/camera";
import { InputPropsSchema } from "../src/props";
import { clipPlayback } from "../src/templates/DesktopShowcase/playback";
import { FPS, sceneRanges } from "../src/timing";
import { camerasOf } from "../src/templates/DesktopFocus/cameras";
import { MEDIA } from "../src/templates/DesktopFocus/layout";

type Box = { x: number; y: number; w: number; h: number };
type Item = { id: string; kind: string; text: string; bbox: Box };
type Span = { scene: string; from_ms: number; to_ms: number; text: string; item: string; view: number[]; box: number[] };
type Snapshot = { t_ms: number; items: Item[] };

const ARRIVED_MS = 700; // the move to a new target is over this long after its entry starts
const TEXT_KINDS = new Set(["heading", "paragraph", "list_item", "button", "input"]);
const EPS = 1.5;

const props = InputPropsSchema.parse(JSON.parse(readFileSync(process.argv[2], "utf8")));
const produceDir = dirname(process.argv[2]);
const FRAME = { w: MEDIA.w, h: MEDIA.h };
const cameras = camerasOf(props.script, props.assets);

const intersects = (a: Box, b: Box) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const inside = (outer: Box, inner: Box) =>
  outer.x - EPS <= inner.x && outer.y - EPS <= inner.y && outer.x + outer.w + EPS >= inner.x + inner.w && outer.y + outer.h + EPS >= inner.y + inner.h;
/** Cut by the view: it touches the view but is not fully inside it (edges of the clip itself do not count). */
const cut = (view: Box, clip: { w: number; h: number }, b: Box) => {
  if (!intersects(view, b) || inside(view, b)) return false;
  const visible = {
    x: Math.max(view.x, 0), y: Math.max(view.y, 0),
    w: Math.min(view.x + view.w, clip.w) - Math.max(view.x, 0),
    h: Math.min(view.y + view.h, clip.h) - Math.max(view.y, 0),
  };
  return !inside(visible, b); // a box cut only by the clip's border is not the camera's doing
};

const nearest = (snaps: Snapshot[], t: number) =>
  snaps.length ? snaps.reduce((best, s) => (Math.abs(s.t_ms - t) < Math.abs(best.t_ms - t) ? s : best)) : null;

const scenes: Record<string, unknown>[] = [];
let framesTotal = 0;
let clipped = 0;
let anyClipped = 0;
let imageInside = 0;
const spans: Span[] = [];
for (const r of sceneRanges(props.script, FPS)) {
  const a = props.assets[r.scene.id];
  const track = a?.focus_track;
  const file = join(produceDir, "inventory", `${r.scene.id}.json`);
  if (!a?.clip_url || !track?.length || !existsSync(file)) continue;
  const snaps: Snapshot[] = JSON.parse(readFileSync(file, "utf8")).inventory;
  const clip = { w: a.clip_width ?? 1440, h: a.clip_height ?? 900 };
  const focus = pickFocus(a);
  const { startMs, rate, lastFrame } = clipPlayback(a, FPS, r.frames);
  let sceneFrames = 0;
  let sceneClipped = 0;
  let sceneAny = 0;
  const imageSeen = new Set<number>();
  for (let f = 0; f < r.frames; f++) {
    const shown = lastFrame === null ? f : Math.min(f, lastFrame);
    const t = startMs + (shown / FPS) * 1000 * rate;
    let idx = -1;
    track.forEach((e, i) => {
      if (e.t_ms <= t) idx = i;
    });
    if (idx < 0) continue;
    const entry = track[idx];
    if (entry.framing === "establish" || t < entry.t_ms + ARRIVED_MS) continue;
    const view = cameras[r.scene.id].at(startMs + (f / FPS) * 1000 * rate).view; // the camera's own clock
    const snap = nearest(snaps, t);
    if (!snap) continue;
    sceneFrames++;
    const texts = snap.items.filter((i) => TEXT_KINDS.has(i.kind) && i.text);
    if (texts.some((i) => cut(view, clip, i.bbox))) sceneAny++;
    // the focus's own text: the chosen item and, for a field, its label (inside the focus box). Neighbours that
    // happen to sit in the box are not the focus's text.
    const box = { x: entry.bbox.x - 6, y: entry.bbox.y - 6, w: entry.bbox.w + 12, h: entry.bbox.h + 12 };
    const chosen = texts.find((i) => i.id === entry.item_id);
    const own = chosen
      ? [chosen, ...(chosen.kind === "input" ? texts.filter((i) => i.id !== chosen.id && (i.kind === "heading" || i.kind === "paragraph") && inside(box, i.bbox)) : [])]
      : texts.filter((i) => inside(box, i.bbox)).slice(0, 2);
    const hit = own.find((i) => cut(view, clip, i.bbox));
    if (hit) {
      sceneClipped++;
      const tNow = (f / FPS) * 1000;
      const last = spans[spans.length - 1];
      if (last && last.scene === r.scene.id && last.item === hit.id && tNow - last.to_ms <= 80) last.to_ms = tNow;
      else spans.push({ scene: r.scene.id, from_ms: tNow, to_ms: tNow, text: hit.text.slice(0, 60), item: hit.id, view: [view.x, view.y, view.w, view.h].map(Math.round), box: [hit.bbox.x, hit.bbox.y, hit.bbox.w, hit.bbox.h].map(Math.round) });
    }
    if ((entry.item_kind === "image" || entry.item_kind === "media") && !inside(view, entry.bbox) && !imageSeen.has(idx)) {
      // the clip's own border may be the only thing cutting it
      const visible = { x: Math.max(view.x, 0), y: Math.max(view.y, 0), w: Math.min(view.x + view.w, clip.w) - Math.max(view.x, 0), h: Math.min(view.y + view.h, clip.h) - Math.max(view.y, 0) };
      if (!inside(visible, entry.bbox)) imageSeen.add(idx);
    }
  }
  framesTotal += sceneFrames;
  clipped += sceneClipped;
  anyClipped += sceneAny;
  imageInside += imageSeen.size;
  scenes.push({ id: r.scene.id, frames: sceneFrames, frames_text_clipped: sceneClipped, frames_any_text_clipped: sceneAny, image_zoom_inside: imageSeen.size });
}
console.log(
  JSON.stringify({
    frames_after_arrival: framesTotal,
    frames_text_clipped: clipped,
    frames_any_text_clipped: anyClipped,
    image_zoom_inside: imageInside,
    clipped_spans: spans.sort((a, b) => b.to_ms - b.from_ms - (a.to_ms - a.from_ms)).slice(0, 5),
    scenes,
  }),
);
