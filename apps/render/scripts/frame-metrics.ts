// desktop_frame (Action Zoom) metrics of a produced job: tsx frame-metrics.ts <render_props.json>
// For every zoom shot of every scene, once the camera has arrived (after its move in) until its move out:
//   action_zoom_clipped_frames   frames in which the operated element + its label (the shot's `target`)
//                                is not whole inside the view (the clip's own border does not count)
//   clipped_spans                the first spans, with the action and its label
//   typing_text_px_min           smallest height, on the final frame, of the text typed in a field:
//                                the field's estimated text height (shot.text_px) * the frame's
//                                width / the view's width (the composition's media frame is 1040 px wide)
//   zoom_events                  number of shots
// Prints one JSON object.
import { readFileSync } from "node:fs";
import { InputPropsSchema } from "../src/props";
import { clipPlayback } from "../src/templates/DesktopShowcase/playback";
import { frameCamerasOf, MEDIA_FRAME } from "../src/templates/DesktopFrame/cameras";
import { FPS, sceneRanges } from "../src/timing";

type Box = { x: number; y: number; w: number; h: number };
const EPS = 1.5;

const props = InputPropsSchema.parse(JSON.parse(readFileSync(process.argv[2], "utf8")));
const cameras = frameCamerasOf(props.script, props.assets);

/** `inner` is whole inside `outer` (a view bigger than the clip only has to hold what is inside the clip). */
const inside = (outer: Box, inner: Box) =>
  outer.x - EPS <= inner.x && outer.y - EPS <= inner.y && outer.x + outer.w + EPS >= inner.x + inner.w && outer.y + outer.h + EPS >= inner.y + inner.h;

let clippedFrames = 0;
let events = 0;
let typingMin: number | null = null;
const spans: { scene: string; from_ms: number; to_ms: number; action: string | null; label: string | null }[] = [];
for (const r of sceneRanges(props.script, FPS)) {
  const a = props.assets[r.scene.id];
  const shots = a?.zoom_shots ?? [];
  if (!a?.clip_url || !shots.length) continue;
  events += shots.length;
  const { startMs, rate } = clipPlayback(a, FPS, r.frames);
  for (const [k, s] of shots.entries()) {
    const target = s.target;
    if (!target) continue;
    // a chained shot is held until the next one pans away; the last move out of the chain ends it
    const next = shots[k + 1];
    const heldTo = next?.chain_prev ? next.in_start_ms : s.out_start_ms;
    let from = -1;
    for (let f = 0; f < r.frames; f++) {
      const t = startMs + (f / FPS) * 1000 * rate;
      const held = t >= s.in_end_ms && t <= heldTo;
      const view = cameras[r.scene.id].at(t).view;
      const cut = held && !inside(view, target);
      if (cut) {
        clippedFrames++;
        if (from < 0) from = t;
      } else if (from >= 0) {
        spans.push({ scene: r.scene.id, from_ms: Math.round(from), to_ms: Math.round(t), action: s.action ?? null, label: s.label ?? null });
        from = -1;
      }
    }
    if (s.action === "type" && s.text_px) {
      const view = cameras[r.scene.id].at(s.in_end_ms + 1).view;
      const px = (s.text_px * MEDIA_FRAME.w) / view.w;
      typingMin = typingMin === null ? px : Math.min(typingMin, px);
    }
  }
}
console.log(
  JSON.stringify({
    action_zoom_clipped_frames: clippedFrames,
    clipped_spans: spans.slice(0, 5),
    typing_text_px_min: typingMin === null ? null : +typingMin.toFixed(1),
    zoom_events: events,
  }),
);
