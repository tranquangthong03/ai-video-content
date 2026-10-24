/**
 * Geometry of the 1080x1920 desktop_focus canvas (composition pixels), as shares of the height:
 *   header   6% - 17%   badge + a two-line headline
 *   media   19% - 84%   4:5 frame (1000 x 1250) the camera crops the clip into; captions sit on its bottom edge
 *   bullets 86% - 95%   at most two key points
 */
import { CANVAS } from "../DesktopShowcase/layout";

export { CANVAS };
const at = (share: number) => Math.round(CANVAS.h * share);

export const HEADER = { top: at(0.06), height: at(0.17) - at(0.06) };
export const HEADER_STYLE = { band: HEADER, headlineSize: 54, badgeSize: 22, gap: 14 };

export const MEDIA = { left: 40, top: at(0.19), w: 1000, h: 1250 };

export const BULLET = { top: at(0.86), pill: 76, gap: 10, maxLines: 2, fontSize: 32, iconSize: 36 };
export const BULLET_AREA_HEIGHT = BULLET.maxLines * BULLET.pill + (BULLET.maxLines - 1) * BULLET.gap;

/** Dark gradient behind the karaoke captions, along the bottom edge of the media frame. */
export const CAPTION_STRIP = { height: 340, paddingBottom: 44 };

/** Text laid over the top of the media frame (hook), and the CTA button near its bottom third. */
export const OVERLAY = { topGradient: 300, textTop: 56, ctaBottom: 330 };
