import React from "react";
import { AbsoluteFill } from "remotion";
import { HEIGHT, WIDTH } from "../../timing";
import { BigText, GradientBackdrop } from "./common";
import { SceneMedia, hasMedia } from "./Media";
import type { SceneProps } from "./types";

export const HookBigText: React.FC<SceneProps<"hook">> = ({ scene, assets, durationInFrames }) => (
  <GradientBackdrop>
    {hasMedia(assets) && (
      <AbsoluteFill style={{ filter: "blur(28px) brightness(0.55)", transform: "scale(1.15)" }}>
        <SceneMedia assets={assets} width={WIDTH} height={HEIGHT} durationInFrames={durationInFrames} />
      </AbsoluteFill>
    )}
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
      <BigText text={scene.on_screen_text ?? scene.voiceover} />
    </AbsoluteFill>
  </GradientBackdrop>
);
