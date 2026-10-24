import React from "react";
import { AbsoluteFill } from "remotion";
import { useTheme } from "../theme/context";
import { usePop } from "./common";
import type { SceneProps } from "./types";

/** Top half = "before" (muted), bottom half = "after" (brand colors) sliding in. */
export const BeforeAfterSplit: React.FC<SceneProps<"before_after">> = ({ scene }) => {
  const { primary, accent, fontFamily } = useTheme();
  const before = usePop();
  const after = usePop(18);
  const text = (size: number): React.CSSProperties => ({
    fontFamily,
    fontWeight: 900,
    fontSize: size,
    lineHeight: 1.12,
    textAlign: "center",
    padding: "0 90px",
    color: "#fff",
    textShadow: "0 8px 30px rgba(0,0,0,0.4)",
  });
  const tag: React.CSSProperties = {
    fontFamily,
    fontWeight: 800,
    fontSize: 46,
    letterSpacing: 6,
    padding: "10px 36px",
    borderRadius: 999,
    marginBottom: 28,
  };
  return (
    <AbsoluteFill>
      <AbsoluteFill
        style={{
          height: "50%",
          background: "linear-gradient(180deg, #3b3b46, #24242c)",
          justifyContent: "center",
          alignItems: "center",
          opacity: Math.min(1, before * 2),
        }}
      >
        <div style={{ ...tag, background: "#ef4444", color: "#fff" }}>TRƯỚC</div>
        <div style={{ ...text(72), transform: `scale(${0.8 + 0.2 * before})` }}>{scene.before_text}</div>
      </AbsoluteFill>
      <AbsoluteFill
        style={{
          top: "50%",
          height: "50%",
          background: `linear-gradient(180deg, ${primary}, ${primary}bb)`,
          justifyContent: "center",
          alignItems: "center",
          transform: `translateY(${(1 - after) * 300}px)`,
          opacity: Math.min(1, after * 2),
        }}
      >
        <div style={{ ...tag, background: accent, color: "#111" }}>SAU</div>
        <div style={{ ...text(78), transform: `scale(${0.8 + 0.2 * after})` }}>{scene.after_text}</div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
