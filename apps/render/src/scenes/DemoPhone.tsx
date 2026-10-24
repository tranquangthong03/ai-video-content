import React from "react";
import { AbsoluteFill } from "remotion";
import { useTheme } from "../theme/context";
import { TopLabel, usePop } from "./common";
import { FallbackScene } from "./FallbackScene";
import { SceneMedia, hasMedia, wantsZoom } from "./Media";
import type { SceneProps } from "./types";

// Phone body and screen size in composition pixels (aspect ~ a modern 780x1688 screen)
export const PHONE = { w: 640, h: 1380, bezel: 16, radius: 88 } as const;
export const PHONE_SCREEN = {
  w: PHONE.w - PHONE.bezel * 2,
  h: PHONE.h - PHONE.bezel * 2,
} as const;

export const DemoPhone: React.FC<SceneProps<"feature_demo">> = ({ scene, assets, durationInFrames }) => {
  const { primary, accent } = useTheme();
  const pop = usePop();
  if (!hasMedia(assets)) return <FallbackScene scene={scene} />;
  return (
    <AbsoluteFill style={{ background: `linear-gradient(160deg, ${primary}, #0b0b1a 70%, ${accent}55)` }}>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", paddingTop: 120 }}>
        <div
          style={{
            width: PHONE.w,
            height: PHONE.h,
            borderRadius: PHONE.radius,
            background: "#0d0d0f",
            padding: PHONE.bezel,
            boxShadow: "0 40px 120px rgba(0,0,0,0.6), inset 0 0 0 3px #3a3a3f",
            transform: `translateY(${(1 - pop) * 160}px) scale(${0.92 + 0.08 * pop})`,
            position: "relative",
          }}
        >
          <div style={{ borderRadius: PHONE.radius - PHONE.bezel, overflow: "hidden" }}>
            <SceneMedia
              assets={assets}
              width={PHONE_SCREEN.w}
              height={PHONE_SCREEN.h}
              durationInFrames={durationInFrames}
              zoomEnabled={wantsZoom(scene.visual)}
            />
          </div>
          <div
            style={{
              position: "absolute",
              top: PHONE.bezel + 18,
              left: "50%",
              width: 170,
              height: 44,
              marginLeft: -85,
              borderRadius: 30,
              background: "#000",
            }}
          />
        </div>
      </AbsoluteFill>
      <TopLabel text={scene.on_screen_text ?? scene.feature} />
    </AbsoluteFill>
  );
};
