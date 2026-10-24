import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { activeWordIndex, wordsOf } from "../../captionWords";
import type { Caption } from "../../props";
import { useTheme } from "../context";

/** Group of 3-5 words; the word being spoken is painted in the primary color. */
export const Karaoke: React.FC<{ captions: Caption[]; paddingBottom?: number }> = ({
  captions,
  paddingBottom = 300,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { fontFamily, highlight } = useTheme();

  const ms = (frame / fps) * 1000;
  const group = captions.find((c) => ms >= c.start_ms && ms < c.end_ms);
  if (!group) return null;
  const words = wordsOf(group);
  const active = activeWordIndex(words, ms);

  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom }}>
      <div
        style={{
          maxWidth: 960,
          textAlign: "center",
          fontFamily,
          fontWeight: 800,
          fontSize: 48,
          lineHeight: 1.25,
          color: "#fff",
          textShadow: "0 4px 18px rgba(0,0,0,0.85), 0 1px 3px rgba(0,0,0,0.9)",
        }}
      >
        {words.map((w, i) => (
          <span
            key={i}
            style={{
              color: i === active ? highlight : "#fff",
              display: "inline-block",
              transform: i === active ? "scale(1.08)" : "none",
              marginRight: i === words.length - 1 ? 0 : "0.28em",
            }}
          >
            {w.text}
          </span>
        ))}
      </div>
    </AbsoluteFill>
  );
};
