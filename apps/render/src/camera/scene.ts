import { CAMERA_CONFIG, type CameraConfig } from "./config";
import type { FocusCamera, View } from "./focus";
import { buildCameraPath, FPS, type CameraPath } from "./path";
import { pickFocus } from "./pick";

type SceneFocus = Parameters<typeof pickFocus>[0];
type Size = { w: number; h: number };

/** The camera path of one scene. `startView`: the scene continues the previous one on the same page. */
export function pathForScene(
  assets: SceneFocus,
  clip: Size,
  frame: Size,
  opts: { closeOpening?: boolean; startView?: View | null; endMs?: number } = {},
  cfg: CameraConfig = CAMERA_CONFIG,
): CameraPath {
  return buildCameraPath(pickFocus(assets), clip, frame, opts, cfg, FPS);
}

/**
 * The camera of one scene as a function of clip time. One seam for everything that needs the
 * camera (the renderer, the metrics and the preview script), so they cannot disagree.
 */
export function cameraForScene(
  assets: SceneFocus,
  clip: Size,
  frame: Size,
  closeOpening = false,
  cfg: CameraConfig = CAMERA_CONFIG,
): (tMs: number) => FocusCamera {
  const path = pathForScene(assets, clip, frame, { closeOpening }, cfg);
  return (tMs) => path.at(tMs);
}

export interface SceneCameraInput {
  id: string;
  type: string;
  assets: SceneFocus & { same_page?: boolean };
  clip: Size;
  /** clip time of the last shown frame of the scene (where the next scene may pick up) */
  endMs: number;
}

/**
 * One path per recorded scene, in order. A scene on the same page as the one before starts where
 * that one ended (no second establishing shot); a hook opens close on its first target.
 */
export function buildSceneCameras(
  scenes: SceneCameraInput[],
  frame: Size,
  cfg: CameraConfig = CAMERA_CONFIG,
): Record<string, CameraPath> {
  const out: Record<string, CameraPath> = {};
  let previous: CameraPath | null = null;
  for (const s of scenes) {
    const startView = s.assets.same_page && previous ? previous.endView() : null;
    const path = pathForScene(s.assets, s.clip, frame, { closeOpening: s.type === "hook", startView, endMs: s.endMs }, cfg);
    out[s.id] = path;
    previous = path;
  }
  return out;
}
