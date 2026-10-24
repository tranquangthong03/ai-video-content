import React from "react";
import { AbsoluteFill, Audio, Sequence, interpolate, useCurrentFrame } from "remotion";
import { resolveAsset } from "../../assets";
import type { Script } from "../../generated";
import type { InputProps, SceneAssets } from "../../props";
import { Captions } from "../../theme/captions";
import { useTheme } from "../../theme/context";
import {
  FPS,
  KARAOKE_WORDS,
  captionsFromVoiceover,
  musicVolume,
  sceneDurationMs,
  sceneRanges,
} from "../../timing";
import { Background, Bullets, Header } from "./Chrome";
import { CROSSFADE_FRAMES, MEDIA } from "./layout";
import { SceneView } from "./SceneViews";

const NO_ASSETS: SceneAssets = {};

/** "TaskFlow - Quản lý..." -> "TaskFlow": the product name shown on the CTA. */
export const productNameOf = (title: string) => title.split(/\s[-–—:|]\s/)[0].trim() || title;

/** Fades its children in over the first CROSSFADE_FRAMES of the sequence it sits in. */
const FadeIn: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, CROSSFADE_FRAMES], [0, 1], { extrapolateRight: "clamp" });
  return <AbsoluteFill style={{ opacity }}>{children}</AbsoluteFill>;
};

/** Bordered 16:9 frame; scenes crossfade inside it while the rest of the canvas stays put. */
const MediaStack: React.FC<{ script: Script; assets: InputProps["assets"] }> = ({ script, assets }) => {
  const frame = useCurrentFrame();
  const { primary } = useTheme();
  const ranges = sceneRanges(script, FPS);
  const appear = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: "clamp" });
  const title = script.title;
  return (
    <div
      style={{
        position: "absolute",
        left: MEDIA.left,
        top: MEDIA.top,
        width: MEDIA.w,
        height: MEDIA.h,
        borderRadius: 24,
        border: `2px solid ${primary}99`,
        boxShadow: `0 0 48px ${primary}66`,
        overflow: "hidden",
        background: "#05070D",
        opacity: appear,
        boxSizing: "content-box",
      }}
    >
      {ranges.map((r, i) => {
        // each scene runs a little past its end so the next one can fade in on top of it
        const extra = i < ranges.length - 1 ? CROSSFADE_FRAMES : 0;
        return (
          <Sequence key={r.scene.id} from={r.from} durationInFrames={r.frames + extra}>
            <FadeIn>
              <SceneView
                scene={r.scene}
                assets={assets[r.scene.id] ?? NO_ASSETS}
                durationInFrames={r.frames}
                productName={productNameOf(title)}
              />
            </FadeIn>
          </Sequence>
        );
      })}
    </div>
  );
};

/** desktop_showcase: pinned headline, a 16:9 browser frame with camera and cursor, key points, captions. */
export const DesktopVideo: React.FC<InputProps> = ({ script, assets, music_url }) => {
  const { captionStyle } = useTheme();
  const ranges = sceneRanges(script, FPS);
  const voiceRanges = ranges.filter((r) => assets[r.scene.id]?.audio_url);
  const bullets = ranges
    .filter((r) => r.scene.key_point)
    .map((r) => ({ start: r.from, text: r.scene.key_point as string, icon: r.scene.icon ?? null }));

  return (
    <AbsoluteFill style={{ background: "#070B14" }}>
      <Background />
      <Header badge={script.badge} headline={script.headline} highlight={script.headline_highlight} />
      <MediaStack script={script} assets={assets} />
      <Bullets items={bullets} />
      {ranges.map((r) => {
        const a = assets[r.scene.id] ?? NO_ASSETS;
        const captions =
          a.captions ??
          captionsFromVoiceover(
            r.scene.voiceover,
            sceneDurationMs(r.scene),
            captionStyle === "karaoke" ? KARAOKE_WORDS : undefined,
          );
        return (
          <Sequence key={r.scene.id} from={r.from} durationInFrames={r.frames}>
            <Captions captions={captions} />
            {a.audio_url && <Audio src={resolveAsset(a.audio_url)} />}
          </Sequence>
        );
      })}
      {music_url && <Audio src={resolveAsset(music_url)} volume={(f) => musicVolume(f, voiceRanges)} loop />}
    </AbsoluteFill>
  );
};
