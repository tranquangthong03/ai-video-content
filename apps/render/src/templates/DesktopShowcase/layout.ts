/** Geometry of the 1080x1920 desktop_showcase canvas (all values in composition pixels). */
export const CANVAS = { w: 1080, h: 1920 };

/** 16:9 media frame, 92% of the canvas width, starting at ~27% of its height. */
export const MEDIA = (() => {
  const w = Math.round(CANVAS.w * 0.92);
  return { left: Math.round((CANVAS.w - w) / 2), top: Math.round(CANVAS.h * 0.27), w, h: Math.round((w * 9) / 16) };
})();

/** Badge + headline are centered in this band above the media frame. */
export const HEADER = { top: 200, height: 290 };

export const BULLET = { top: MEDIA.top + MEDIA.h + 32, pill: 64, gap: 10, maxLines: 4, slideFrames: 12 };
export const BULLET_AREA_HEIGHT = BULLET.maxLines * BULLET.pill + (BULLET.maxLines - 1) * BULLET.gap;

/** Frames over which one scene fades in on top of the previous one. */
export const CROSSFADE_FRAMES = 10;

/** Splits a headline around its highlighted phrase; the phrase is null when absent or not found. */
export function splitHeadline(headline: string, highlight: string | null | undefined) {
  const at = highlight ? headline.indexOf(highlight) : -1;
  if (!highlight || at < 0) return { before: headline, mark: null as string | null, after: "" };
  return { before: headline.slice(0, at), mark: highlight, after: headline.slice(at + highlight.length) };
}

export type BulletPlacement = { index: number; slot: number; opacity: number; enter: number };

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const ease = (u: number) => u * u * (3 - 2 * u);

/**
 * Where each key_point pill sits at `frame`. `starts` are the frames the bullets appear on.
 * New pills fade/slide in; once more than `maxLines` exist the list scrolls up by one slot and the
 * oldest pill fades out as it leaves.
 */
export function placeBullets(
  starts: number[],
  frame: number,
  maxLines = BULLET.maxLines,
  slideFrames = BULLET.slideFrames,
): BulletPlacement[] {
  let base = 0;
  starts.forEach((s, k) => {
    if (k >= maxLines && frame >= s) base += ease(clamp01((frame - s) / slideFrames));
  });
  const out: BulletPlacement[] = [];
  starts.forEach((s, index) => {
    if (frame < s) return;
    const slot = index - base;
    const opacity = clamp01(1 + slot) * clamp01((frame - s) / slideFrames + 0.001);
    if (opacity > 0) out.push({ index, slot, opacity, enter: ease(clamp01((frame - s) / slideFrames)) });
  });
  return out;
}
