import { buildSceneCameras, type CameraPath, type SceneCameraInput } from "../../camera";
import type { Script } from "../../generated";
import type { InputProps } from "../../props";
import { FPS, sceneRanges } from "../../timing";
import { clipPlayback } from "../DesktopShowcase/playback";
import { MEDIA } from "./layout";

export const MEDIA_FRAME = { w: MEDIA.w, h: MEDIA.h };

/**
 * The planned camera of every recorded scene of a video. The renderer, the metrics scripts and the
 * preview all call this, so they always see the same path.
 */
export function camerasOf(script: Script, assets: InputProps["assets"]): Record<string, CameraPath> {
  const inputs: SceneCameraInput[] = [];
  for (const r of sceneRanges(script, FPS)) {
    const a = assets[r.scene.id];
    if (!a?.clip_url) continue;
    const { startMs, rate } = clipPlayback(a, FPS, r.frames);
    inputs.push({
      id: r.scene.id,
      type: r.scene.type,
      assets: a,
      clip: { w: a.clip_width ?? 1440, h: a.clip_height ?? 900 },
      endMs: startMs + ((r.frames - 1) / FPS) * 1000 * rate, // the camera's clock runs to the scene's end
    });
  }
  return buildSceneCameras(inputs, MEDIA_FRAME);
}
