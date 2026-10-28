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
import { CameraContext, FocusSceneView, GeometryContext, type Geometry } from "../DesktopFocus/FocusViews";
import { FRAME_CROSSFADE_FRAMES, MEDIA_FRAME, boundariesOf, frameCamerasOf } from "./cameras";
import { BULLET, CAPTIONS, HEADER_STYLE, MEDIA, OVERLAY } from "./layout";

const NO_ASSETS: SceneAssets = {};

const GEOMETRY: Geometry = { frame: MEDIA_FRAME, captionStrip: 0, overlay: OVERLAY, still: true };

const FadeIn: React.FC<{ frames: number; children: React.ReactNode }> = ({ frames, children }) => {
  const frame = useCurrentFrame();
  const opacity = frames > 0 ? interpolate(frame, [0, frames], [0, 1], { extrapolateRight: "clamp" }) : 1;
  return <AbsoluteFill style={{ opacity }}>{children}</AbsoluteFill>;
};

/** The 16:9 bordered frame: scenes hand over inside it, by a crossfade only while both cameras rest. */
const MediaStack: React.FC<{ script: Script; assets: InputProps["assets"] }> = ({ script, assets }) => {
  const frame = useCurrentFrame();
  const { primary } = useTheme();
  const ranges = sceneRanges(script, FPS);
  const cameras = useMemo(() => frameCamerasOf(script, assets), [script, assets]);
  const cuts = useMemo(() => boundariesOf(script, assets, cameras), [script, assets, cameras]);
  const appear = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: "clamp" });
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
        boxShadow: `0 0 52px ${primary}66`,
        overflow: "hidden",
        background: "#05070D",
        opacity: appear,
        boxSizing: "content-box",
      }}
    >
      <GeometryContext.Provider value={GEOMETRY}>
        <CameraContext.Provider value={cameras}>
          {ranges.map((r, i) => {
            const fadeOut = i < ranges.length - 1 && cuts[i].crossfade ? FRAME_CROSSFADE_FRAMES : 0;
            const fadeIn = i > 0 && cuts[i - 1].crossfade ? FRAME_CROSSFADE_FRAMES : 0;
            return (
              <Sequence key={r.scene.id} from={r.from} durationInFrames={r.frames + fadeOut}>
                <FadeIn frames={fadeIn}>
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
      </GeometryContext.Provider>
    </div>
  );
};

/** Karaoke captions under the frame: large, two lines at most. */
const CaptionBlock: React.FC<{ script: Script; assets: InputProps["assets"] }> = ({ script, assets }) => {
  const { captionStyle } = useTheme();
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: CAPTIONS.top, height: CAPTIONS.height }}>
      {sceneRanges(script, FPS).map((r) => {
        const a = assets[r.scene.id] ?? NO_ASSETS;
        const captions =
          a.captions ??
          captionsFromVoiceover(r.scene.voiceover, sceneDurationMs(r.scene), captionStyle === "karaoke" ? KARAOKE_WORDS : undefined);
        return (
          <Sequence key={`c-${r.scene.id}`} from={r.from} durationInFrames={r.frames}>
            <Captions captions={captions} paddingBottom={0} fontSize={CAPTIONS.fontSize} />
          </Sequence>
        );
      })}
    </div>
  );
};

/** desktop_frame: headline, a 16:9 frame with a still camera, large captions, two key points. */
export const DesktopFrameVideo: React.FC<InputProps> = ({ script, assets, music_url }) => {
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
      <CaptionBlock script={script} assets={assets} />
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
