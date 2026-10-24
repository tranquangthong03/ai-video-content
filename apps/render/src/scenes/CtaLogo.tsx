import React from "react";
import { AbsoluteFill, Img } from "remotion";
import { resolveAsset } from "../assets";
import { useTheme } from "../theme/context";
import { BigText, GradientBackdrop, usePop } from "./common";
import type { SceneProps } from "./types";

export const CtaLogo: React.FC<SceneProps<"cta">> = ({ scene }) => {
  const { logo, accent } = useTheme();
  const pop = usePop();
  return (
    <GradientBackdrop>
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", gap: 60 }}>
        {logo && (
          <Img
            src={resolveAsset(logo)}
            style={{ width: 360, height: 360, objectFit: "contain", transform: `scale(${pop})` }}
          />
        )}
        <BigText text={scene.on_screen_text ?? scene.voiceover} size={96} />
        <div
          style={{ width: 220, height: 10, borderRadius: 5, background: accent, transform: `scaleX(${pop})` }}
        />
      </AbsoluteFill>
    </GradientBackdrop>
  );
};
