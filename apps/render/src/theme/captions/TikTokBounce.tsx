import React from "react";
import { AbsoluteFill, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { Caption } from "../../props";
import { useTheme } from "../context";

/** Active caption pops in with a spring bounce. Sits in the lower third, outlined for any background. */
export const TikTokBounce: React.FC<{ captions: Caption[]; paddingBottom?: number }> = ({
  captions,
  paddingBottom = 300,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { fontFamily, accent, motion } = useTheme();

  const ms = (frame / fps) * 1000;
  const active = captions.find((c) => ms >= c.start_ms && ms < c.end_ms);
  if (!active) return null;

  const local = frame - Math.floor((active.start_ms / 1000) * fps);
  const pop = spring({ frame: local, fps, config: motion.spring, durationInFrames: 14 });

  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom }}>
      <div
        style={{
          transform: `scale(${0.6 + 0.4 * pop})`,
          opacity: Math.min(1, pop * 2),
          maxWidth: 940,
          textAlign: "center",
          fontFamily,
          fontWeight: 900,
          fontSize: 88,
          lineHeight: 1.1,
          textTransform: "uppercase",
          color: accent,
          WebkitTextStroke: "14px #000",
          paintOrder: "stroke fill",
          textShadow: "0 8px 24px rgba(0,0,0,0.6)",
        }}
      >
        {active.text}
      </div>
    </AbsoluteFill>
  );
};
