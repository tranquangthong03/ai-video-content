import React from "react";
import { AbsoluteFill, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { useTheme } from "../theme/context";

/** 0 -> 1 spring using the theme's motion preset. */
export function usePop(delayFrames = 0): number {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { motion } = useTheme();
  return spring({ frame: frame - delayFrames, fps, config: motion.spring });
}

export const GradientBackdrop: React.FC<{ children?: React.ReactNode }> = ({ children }) => {
  const { primary } = useTheme();
  return (
    <AbsoluteFill style={{ background: `linear-gradient(165deg, ${primary} 0%, ${primary}cc 45%, #0b0b1a 100%)` }}>
      {children}
    </AbsoluteFill>
  );
};

export const BigText: React.FC<{ text: string; size?: number; color?: string }> = ({
  text,
  size = 104,
  color = "#fff",
}) => {
  const { fontFamily } = useTheme();
  const pop = usePop();
  return (
    <div
      style={{
        fontFamily,
        fontWeight: 900,
        fontSize: size,
        lineHeight: 1.12,
        color,
        textAlign: "center",
        padding: "0 80px",
        transform: `scale(${0.7 + 0.3 * pop})`,
        opacity: Math.min(1, pop * 2),
        textShadow: "0 10px 40px rgba(0,0,0,0.45)",
      }}
    >
      {text}
    </div>
  );
};

/** Small label on top of demo scenes. */
export const TopLabel: React.FC<{ text: string | null | undefined }> = ({ text }) => {
  const { fontFamily, accent } = useTheme();
  const pop = usePop(4);
  if (!text) return null;
  return (
    <AbsoluteFill style={{ alignItems: "center", paddingTop: 110 }}>
      <div
        style={{
          fontFamily,
          fontWeight: 800,
          fontSize: 58,
          color: "#111",
          background: accent,
          padding: "16px 44px",
          borderRadius: 999,
          transform: `translateY(${(1 - pop) * -60}px)`,
          opacity: Math.min(1, pop * 2),
          boxShadow: "0 12px 40px rgba(0,0,0,0.35)",
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
};
