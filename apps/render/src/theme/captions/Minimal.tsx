import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { Caption } from "../../props";
import { useTheme } from "../context";

/** Plain white caption with a soft fade, outlined and shadowed for readability. */
export const Minimal: React.FC<{ captions: Caption[]; paddingBottom?: number }> = ({ captions, paddingBottom = 300 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { fontFamily } = useTheme();

  const ms = (frame / fps) * 1000;
  const active = captions.find((c) => ms >= c.start_ms && ms < c.end_ms);
  if (!active) return null;

  const start = (active.start_ms / 1000) * fps;
  const end = (active.end_ms / 1000) * fps;
  const opacity = interpolate(frame, [start, start + 6, end - 6, end], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom }}>
      <div
        style={{
          opacity,
          maxWidth: 900,
          textAlign: "center",
          fontFamily,
          fontWeight: 700,
          fontSize: 56,
          lineHeight: 1.2,
          color: "#fff",
          WebkitTextStroke: "8px rgba(0,0,0,0.85)",
          paintOrder: "stroke fill",
          textShadow: "0 4px 18px rgba(0,0,0,0.7)",
        }}
      >
        {active.text}
      </div>
    </AbsoluteFill>
  );
};
