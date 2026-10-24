import React from "react";
import { AbsoluteFill } from "remotion";
import { HEIGHT, WIDTH } from "../timing";
import { BigText, GradientBackdrop, usePop } from "./common";
import { SceneMedia, hasMedia } from "./Media";
import type { SceneProps } from "./types";

const EMOJI = /\p{Extended_Pictographic}(?:‍\p{Extended_Pictographic}|️)*/u;

/** Splits the first emoji off the text; defaults to a sparkle when there is none. */
export function splitEmoji(text: string): { emoji: string; rest: string } {
  const match = EMOJI.exec(text);
  if (!match) return { emoji: "✨", rest: text };
  return { emoji: match[0], rest: text.replace(match[0], "").replace(/\s+/g, " ").trim() };
}

export const HookEmoji: React.FC<SceneProps<"hook">> = ({ scene, assets, durationInFrames }) => {
  const { emoji, rest } = splitEmoji(scene.on_screen_text ?? scene.voiceover);
  const pop = usePop();
  return (
    <GradientBackdrop>
      {hasMedia(assets) && (
        <AbsoluteFill style={{ filter: "blur(28px) brightness(0.5)", transform: "scale(1.15)" }}>
          <SceneMedia assets={assets} width={WIDTH} height={HEIGHT} durationInFrames={durationInFrames} />
        </AbsoluteFill>
      )}
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", gap: 40 }}>
        <div style={{ fontSize: 340, lineHeight: 1, transform: `scale(${pop}) rotate(${(1 - pop) * -25}deg)` }}>
          {emoji}
        </div>
        <BigText text={rest || scene.voiceover} size={92} />
      </AbsoluteFill>
    </GradientBackdrop>
  );
};
