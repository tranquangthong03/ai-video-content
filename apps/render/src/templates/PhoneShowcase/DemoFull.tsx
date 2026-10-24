import React from "react";
import { AbsoluteFill } from "remotion";
import { HEIGHT, WIDTH } from "../../timing";
import { TopLabel } from "./common";
import { FallbackScene } from "./FallbackScene";
import { SceneMedia, hasMedia, wantsZoom } from "./Media";
import type { SceneProps } from "./types";

export const DemoFull: React.FC<SceneProps<"feature_demo">> = ({ scene, assets, durationInFrames }) => {
  if (!hasMedia(assets)) return <FallbackScene scene={scene} />;
  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <SceneMedia
        assets={assets}
        width={WIDTH}
        height={HEIGHT}
        durationInFrames={durationInFrames}
        zoomEnabled={wantsZoom(scene.visual)}
      />
      <TopLabel text={scene.on_screen_text ?? scene.feature} />
    </AbsoluteFill>
  );
};
