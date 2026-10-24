import React from "react";
import { AbsoluteFill, Img, useCurrentFrame } from "remotion";
import { resolveAsset } from "../assets";
import { useTheme } from "../theme/context";
import { BigText, GradientBackdrop, usePop } from "./common";
import type { SceneProps } from "./types";

export const CtaButtonPulse: React.FC<SceneProps<"cta">> = ({ scene }) => {
  const frame = useCurrentFrame();
  const { logo, accent, fontFamily } = useTheme();
  const pop = usePop(10);
  const pulse = 1 + 0.07 * Math.sin(frame / 4);
  return (
    <GradientBackdrop>
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", gap: 90 }}>
        {logo && <Img src={resolveAsset(logo)} style={{ width: 240, height: 240, objectFit: "contain" }} />}
        <BigText text={scene.voiceover} size={76} />
        <div
          style={{
            fontFamily,
            fontWeight: 900,
            fontSize: 74,
            color: "#111",
            background: accent,
            padding: "36px 90px",
            borderRadius: 999,
            transform: `scale(${pop * pulse})`,
            boxShadow: `0 0 ${40 + 30 * Math.sin(frame / 4) ** 2}px ${accent}aa`,
          }}
        >
          {scene.on_screen_text ?? "Bắt đầu ngay"}
        </div>
      </AbsoluteFill>
    </GradientBackdrop>
  );
};
