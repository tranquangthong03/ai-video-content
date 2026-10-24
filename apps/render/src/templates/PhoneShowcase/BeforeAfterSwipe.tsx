import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { useTheme } from "../../theme/context";
import type { SceneProps } from "./types";

/** "Before" fills the screen, then a wipe from the right reveals "after". */
export const BeforeAfterSwipe: React.FC<SceneProps<"before_after">> = ({ scene, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { primary, accent, fontFamily } = useTheme();
  const start = durationInFrames * 0.42;
  const wipe = interpolate(frame, [start, start + 18], [100, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const panel = (bg: string, label: string, text: string | null, labelBg: string, labelFg: string) => (
    <AbsoluteFill style={{ background: bg, justifyContent: "center", alignItems: "center" }}>
      <div
        style={{
          fontFamily,
          fontWeight: 800,
          fontSize: 48,
          letterSpacing: 6,
          background: labelBg,
          color: labelFg,
          padding: "10px 36px",
          borderRadius: 999,
          marginBottom: 36,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily,
          fontWeight: 900,
          fontSize: 92,
          lineHeight: 1.12,
          textAlign: "center",
          padding: "0 90px",
          color: "#fff",
          textShadow: "0 8px 30px rgba(0,0,0,0.4)",
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
  return (
    <AbsoluteFill>
      {panel("linear-gradient(180deg, #3b3b46, #1e1e25)", "TRƯỚC", scene.before_text, "#ef4444", "#fff")}
      <AbsoluteFill style={{ clipPath: `inset(0 0 0 ${wipe}%)` }}>
        {panel(`linear-gradient(165deg, ${primary}, #0b0b1a)`, "SAU", scene.after_text, accent, "#111")}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
