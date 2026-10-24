export type Size = { w: number; h: number };
export type Box = { x: number; y: number; w: number; h: number };
export type Point = { x: number; y: number };

/** object-fit: cover — scale so `src` fills `dst`, centered (overflow cropped). */
export function coverFit(src: Size, dst: Size) {
  const scale = Math.max(dst.w / src.w, dst.h / src.h);
  return { scale, offsetX: (dst.w - src.w * scale) / 2, offsetY: (dst.h - src.h * scale) / 2 };
}

/**
 * Maps a point in source-clip pixels to composition pixels, for a clip rendered with
 * object-fit: cover inside `frame` (the full canvas for DemoFull, the phone screen for DemoPhone).
 */
export function mapClipPoint(p: Point, src: Size, frame: Box): Point {
  const { scale, offsetX, offsetY } = coverFit(src, { w: frame.w, h: frame.h });
  return { x: frame.x + offsetX + p.x * scale, y: frame.y + offsetY + p.y * scale };
}
