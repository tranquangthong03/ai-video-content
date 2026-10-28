/**
 * Geometry of the 1080x1920 desktop_frame canvas (composition pixels):
 *   header    ~11% - 21%   badge + a two-line headline
 *   media     ~24%         16:9 frame, 96% of the width, right under the header
 *   captions  below it     karaoke, large, two lines at most
 *   bullets   below those  at most two key points
 */
import { CANVAS } from "../DesktopShowcase/layout";

export { CANVAS };
const at = (share: number) => Math.round(CANVAS.h * share);

export const HEADER = { top: at(0.11), height: at(0.215) - at(0.11) };
export const HEADER_STYLE = { band: HEADER, headlineSize: 54, badgeSize: 22, gap: 14 };

/** 1040 x 585 is exactly 16:9, so a 16:9 clip fills it with no bars. */
export const MEDIA = { left: 20, top: at(0.245), w: 1040, h: 585 };

export const CAPTIONS = { top: MEDIA.top + MEDIA.h + 36, height: 250, fontSize: 64 };

export const BULLET = { top: CAPTIONS.top + CAPTIONS.height + 24, pill: 76, gap: 10, maxLines: 2, fontSize: 32, iconSize: 36 };

/** Text laid over the media frame (hook / CTA): small, on a short gradient, away from the middle. */
export const OVERLAY = { topGradient: 150, textTop: 18, textSize: 40, ctaBottom: 34 };
