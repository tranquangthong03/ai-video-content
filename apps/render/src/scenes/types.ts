import type { Scene } from "../generated";
import type { SceneAssets } from "../props";

export type SceneType = Scene["type"];
export type SceneOf<T extends SceneType> = Extract<Scene, { type: T }>;

export type SceneProps<T extends SceneType = SceneType> = {
  scene: SceneOf<T>;
  assets: SceneAssets;
  durationInFrames: number;
};
