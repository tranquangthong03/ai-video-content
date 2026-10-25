/**
 * The knobs of the focus-first camera, all in one place.
 *
 * Zoom is measured in "cover" units: 1.0 is the clip scaled to just fill the media frame
 * (object-fit: cover, the whole clip height visible), larger values zoom in. The clip is only
 * 1440 px wide, so the maximum is kept low (1.4) to limit how much it is magnified.
 */
export type FocusKind = "click" | "dblclick" | "type" | "hover" | "highlight" | "section" | "scroll";
/** How the focus track wants a target framed (see producer/focus_rules.py). */
export type Framing = "establish" | "tight" | "medium" | "wide";

export interface CameraConfig {
  minZoom: number; // never below cover after the establishing shot
  maxZoom: number;
  padding: number; // each side of the target box, as a share of its size
  /** Share of the view width the padded box fills, per framing of a focus_track entry. */
  framingShare: Record<Framing, number>;
  /** Share of the view width the (padded) target should fill, by what is being shown. */
  share: Record<FocusKind, number>;
  establishingMs: number; // whole page (fit to width) at the start of every clip
  transitionMs: number; // upper bound for the move from the establishing shot to the first target
  leadMs: number; // the camera starts moving to a target this long before it happens
  minSegmentMs: number; // targets closer together than this are merged into one move
  spring: { damping: number; stiffness: number; mass: number };
  /** Settled enough: the spring counts as arrived at this share of the way. */
  arrived: number;
  /** Size of the box assumed around a click when only click_log exists (clip pixels). */
  fallbackBox: { w: number; h: number };
  /** Establishing shot backdrop: the clip itself, enlarged, blurred and dimmed. */
  backdrop: { blurPx: number; brightness: number };
}

export const CAMERA_CONFIG: CameraConfig = {
  minZoom: 1.0,
  maxZoom: 1.4,
  padding: 0.12,
  framingShare: { establish: 1, tight: 0.7, medium: 0.5, wide: 1 },
  share: {
    click: 0.7,
    dblclick: 0.7,
    type: 0.7,
    highlight: 0.75,
    section: 0.8,
    hover: 0.55, // hover and scroll never zoom harder than a click
    scroll: 0.5,
  },
  establishingMs: 1000,
  transitionMs: 600,
  leadMs: 300,
  minSegmentMs: 150,
  spring: { damping: 25, stiffness: 156, mass: 1 }, // critically damped, arrives in about 0.5 s
  arrived: 0.98,
  fallbackBox: { w: 280, h: 140 },
  backdrop: { blurPx: 24, brightness: 0.6 },
};
