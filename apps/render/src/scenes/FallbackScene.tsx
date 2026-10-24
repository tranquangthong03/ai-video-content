import React from "react";
import { AbsoluteFill } from "remotion";
import type { Scene } from "../generated";
import { BigText, GradientBackdrop } from "./common";

/** Text on the primary color: used for unknown layouts and for demo scenes without media. */
export const FallbackScene: React.FC<{ scene: Scene }> = ({ scene }) => (
  <GradientBackdrop>
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
      <BigText text={scene.on_screen_text ?? scene.voiceover} size={88} />
    </AbsoluteFill>
  </GradientBackdrop>
);
