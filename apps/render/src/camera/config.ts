/**
 * The knobs of the focus-first camera, all in one place.
 *
 * Zoom is measured in "cover" units: 1.0 is the clip scaled to just fill the media frame
 * (object-fit: cover, the whole clip height visible), larger values zoom in. The clip is only
 * 1440 px wide, so the maximum is kept low (1.4) to limit how much it is magnified.
 */
export type FocusKind = "click" | "dblclick" | "type" | "hover" | "highlight" | "section" | "scroll";

export const CAMERA_CONFIG = {
  minZoom: 1.0, // never below cover after the establishing shot
  maxZoom: 1.4,
  padding: 0.15, // each side of the target box, as a share of its size
  /** Share of the view width the (padded) target should fill, by what is being shown. */
  share: {
    click: 0.7,
    dblclick: 0.7,
    type: 0.7,
    highlight: 0.75,
    section: 0.8,
    hover: 0.55, // hover and scroll never zoom harder than a click
    scroll: 0.5,
  } as Record<FocusKind, number>,
  establishingMs: 1000, // whole page (fit to width) at the start of every clip
  transitionMs: 600, // upper bound for the move from the establishing shot to the first target
  leadMs: 300, // the camera starts moving to a target this long before it happens
  minSegmentMs: 150, // targets closer together than this are merged into one move
  // critically damped, arrives in about 0.5 s
  spring: { damping: 25, stiffness: 156, mass: 1 },
  /** Settled enough: the spring counts as arrived at this share of the way. */
  arrived: 0.98,
  /** Size of the box assumed around a click when only click_log exists (clip pixels). */
  fallbackBox: { w: 280, h: 140 },
  /** Establishing shot backdrop: the clip itself, enlarged, blurred and dimmed. */
  backdrop: { blurPx: 24, brightness: 0.6 },
} as const;

export type CameraConfig = typeof CAMERA_CONFIG;
