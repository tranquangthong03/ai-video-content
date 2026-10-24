import React from "react";
import { AbsoluteFill, Audio, Series, interpolate, useCurrentFrame } from "remotion";
import { resolveAsset } from "../../assets";
import type { Scene, Script } from "../../generated";
import type { InputProps, SceneAssets } from "../../props";
import { Captions } from "../../theme/captions";
import { useTheme } from "../../theme/context";
import { FPS, captionsFromVoiceover, musicVolume, sceneDurationMs, sceneFrames, sceneRanges } from "../../timing";
import { resolveScene } from "./index";

const NO_ASSETS: SceneAssets = {};

/** One scene: component picked from SCENES, fade-in, voiceover audio and captions. */
const SceneShell: React.FC<{ scene: Scene; assets: SceneAssets; frames: number }> = ({
  scene,
  assets,
  frames,
}) => {
  const frame = useCurrentFrame();
  const { motion, primary } = useTheme();
  const SceneComponent = resolveScene(scene.type, scene.layout);
  const captions = assets.captions ?? captionsFromVoiceover(scene.voiceover, sceneDurationMs(scene));
  const fadeIn = interpolate(frame, [0, motion.transitionFrames], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ background: primary }}>
      <AbsoluteFill style={{ opacity: fadeIn }}>
        <SceneComponent scene={scene} assets={assets} durationInFrames={frames} />
        <Captions captions={captions} />
      </AbsoluteFill>
      {assets.audio_url && <Audio src={resolveAsset(assets.audio_url)} />}
    </AbsoluteFill>
  );
};

/** phone_showcase: full-bleed scenes (hook, demo on a phone or full screen, before/after, CTA). */
export const PhoneVideo: React.FC<InputProps> = ({ script, assets, music_url }) => {
  const ranges = sceneRanges(script as Pick<Script, "scenes">, FPS);
  const voiceRanges = ranges.filter((r) => assets[r.scene.id]?.audio_url);

  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <Series>
        {script.scenes.map((scene) => (
          <Series.Sequence key={scene.id} durationInFrames={sceneFrames(scene, FPS)}>
            <SceneShell scene={scene} assets={assets[scene.id] ?? NO_ASSETS} frames={sceneFrames(scene, FPS)} />
          </Series.Sequence>
        ))}
      </Series>
      {music_url && <Audio src={resolveAsset(music_url)} volume={(f) => musicVolume(f, voiceRanges)} loop />}
    </AbsoluteFill>
  );
};
