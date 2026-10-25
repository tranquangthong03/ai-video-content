import { focusFromClicks, type FocusLike } from "./focus";

type FocusAssets = {
  focus_track?: FocusLike[];
  focus_log?: FocusLike[];
  click_log?: { t_ms: number; x: number; y: number; type?: string }[];
};

/** What the camera follows: the producer's focus_track, else the recorder's focus_log, else the clicks. */
export function pickFocus(a: FocusAssets): FocusLike[] {
  if (a.focus_track?.length) return a.focus_track;
  if (a.focus_log?.length) return a.focus_log;
  return focusFromClicks(a.click_log ?? []);
}
