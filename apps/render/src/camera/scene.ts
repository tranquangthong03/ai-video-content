import { CAMERA_CONFIG, type CameraConfig } from "./config";
import { focusCameraAt, type FocusCamera } from "./focus";
import { pickFocus } from "./pick";

type SceneFocus = Parameters<typeof pickFocus>[0];

/**
 * The camera of one scene as a function of clip time. One seam for everything that needs the
 * camera (the renderer, the metrics and the preview script), so they cannot disagree.
 */
export function cameraForScene(
  assets: SceneFocus,
  clip: { w: number; h: number },
  frame: { w: number; h: number },
  closeOpening = false,
  cfg: CameraConfig = CAMERA_CONFIG,
): (tMs: number) => FocusCamera {
  const focus = pickFocus(assets);
  return (tMs) => focusCameraAt(tMs, focus, clip, frame, cfg, closeOpening);
}
