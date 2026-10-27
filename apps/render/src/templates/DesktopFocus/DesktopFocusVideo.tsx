import React, { useMemo } from "react";
import { AbsoluteFill, Audio, Sequence, interpolate, useCurrentFrame } from "remotion";
import { resolveAsset } from "../../assets";
import type { Script } from "../../generated";
import type { InputProps, SceneAssets } from "../../props";
import { Captions } from "../../theme/captions";
import { useTheme } from "../../theme/context";
import { FPS, KARAOKE_WORDS, captionsFromVoiceover, musicVolume, sceneDurationMs, sceneRanges } from "../../timing";
import { Background, Bullets, Header } from "../DesktopShowcase/Chrome";
import { productNameOf } from "../DesktopShowcase/DesktopVideo";
import { CROSSFADE_FRAMES } from "../DesktopShowcase/layout";
import { camerasOf } from "./cameras";
import { CameraContext, FocusSceneView } from "./FocusViews";
import { BULLET, CAPTION_STRIP, HEADER_STYLE, MEDIA } from "./layout";

const NO_ASSETS: SceneAssets = {};

const FadeIn: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, CROSSFADE_FRAMES], [0, 1], { extrapolateRight: "clamp" });
  return <AbsoluteFill style={{ opacity }}>{children}</AbsoluteFill>;
};

/** 4:5 bordered frame: scenes crossfade inside it and the karaoke captions sit on its bottom edge. */
const MediaStack: React.FC<{ script: Script; assets: InputProps["assets"] }> = ({ script, assets }) => {
  const frame = useCurrentFrame();
  const { primary, captionStyle } = useTheme();
  const ranges = sceneRanges(script, FPS);
  const cameras = useMemo(() => camerasOf(script, assets), [script, assets]);
  const appear = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: "clamp" });
  return (
    <div
      style={{
        position: "absolute",
        left: MEDIA.left,
        top: MEDIA.top,
        width: MEDIA.w,
        height: MEDIA.h,
        borderRadius: 28,
        border: `2px solid ${primary}99`,
        boxShadow: `0 0 52px ${primary}66`,
        overflow: "hidden",
        background: "#05070D",
        opacity: appear,
        boxSizing: "content-box",
      }}
    >
      <CameraContext.Provider value={cameras}>
      {ranges.map((r, i) => {
        const extra = i < ranges.length - 1 ? CROSSFADE_FRAMES : 0;
        return (
          <Sequence key={r.scene.id} from={r.from} durationInFrames={r.frames + extra}>
            <FadeIn>
              <FocusSceneView
                scene={r.scene}
                assets={assets[r.scene.id] ?? NO_ASSETS}
                durationInFrames={r.frames}
                productName={productNameOf(script.title)}
              />
            </FadeIn>
          </Sequence>
        );
      })}
      </CameraContext.Provider>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          height: CAPTION_STRIP.height,
          background: "linear-gradient(to top, rgba(5,7,13,0.9) 0%, rgba(5,7,13,0.55) 55%, rgba(5,7,13,0) 100%)",
        }}
      />
      {ranges.map((r) => {
        const a = assets[r.scene.id] ?? NO_ASSETS;
        const captions =
          a.captions ??
          captionsFromVoiceover(r.scene.voiceover, sceneDurationMs(r.scene), captionStyle === "karaoke" ? KARAOKE_WORDS : undefined);
        return (
          <Sequence key={`c-${r.scene.id}`} from={r.from} durationInFrames={r.frames}>
            <Captions captions={captions} paddingBottom={CAPTION_STRIP.paddingBottom} />
          </Sequence>
        );
      })}
    </div>
  );
};

/** desktop_focus: headline on top, a 4:5 frame the focus camera crops the clip into, two key points below. */
export const DesktopFocusVideo: React.FC<InputProps> = ({ script, assets, music_url }) => {
  const ranges = sceneRanges(script, FPS);
  const voiceRanges = ranges.filter((r) => assets[r.scene.id]?.audio_url);
  const bullets = ranges
    .filter((r) => r.scene.key_point)
    .map((r) => ({ start: r.from, text: r.scene.key_point as string, icon: r.scene.icon ?? null }));

  return (
    <AbsoluteFill style={{ background: "#070B14" }}>
      <Background />
      <Header badge={script.badge} headline={script.headline} highlight={script.headline_highlight} style={HEADER_STYLE} />
      <MediaStack script={script} assets={assets} />
      <Bullets items={bullets} style={BULLET} />
      {ranges.map((r) => {
        const a = assets[r.scene.id];
        return a?.audio_url ? (
          <Sequence key={`a-${r.scene.id}`} from={r.from} durationInFrames={r.frames}>
            <Audio src={resolveAsset(a.audio_url)} />
          </Sequence>
        ) : null;
      })}
      {music_url && <Audio src={resolveAsset(music_url)} volume={(f) => musicVolume(f, voiceRanges)} loop />}
    </AbsoluteFill>
  );
};
