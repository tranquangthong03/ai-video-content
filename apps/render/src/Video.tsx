import React from "react";
import { AbsoluteFill, Audio, Series, interpolate, useCurrentFrame } from "remotion";
import { resolveAsset } from "./assets";
import { InputPropsSchema, type InputPropsInput, type SceneAssets } from "./props";
import { resolveScene } from "./scenes";
import { Captions } from "./theme/captions";
import { useTheme } from "./theme/context";
import { ThemeProvider } from "./theme/ThemeProvider";
import { FPS, captionsFromVoiceover, musicVolume, sceneDurationMs, sceneFrames, sceneRanges } from "./timing";
import type { Scene } from "./generated";

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

export const Video: React.FC<InputPropsInput> = (raw) => {
  const { script, assets, music_url } = InputPropsSchema.parse(raw);
  const ranges = sceneRanges(script, FPS);
  const voiceRanges = ranges.filter((r) => assets[r.scene.id]?.audio_url);

  return (
    <ThemeProvider theme={script.theme}>
      <AbsoluteFill style={{ background: "#000" }}>
        <Series>
          {script.scenes.map((scene) => (
            <Series.Sequence key={scene.id} durationInFrames={sceneFrames(scene, FPS)}>
              <SceneShell
                scene={scene}
                assets={assets[scene.id] ?? NO_ASSETS}
                frames={sceneFrames(scene, FPS)}
              />
            </Series.Sequence>
          ))}
        </Series>
        {music_url && <Audio src={resolveAsset(music_url)} volume={(f) => musicVolume(f, voiceRanges)} loop />}
      </AbsoluteFill>
    </ThemeProvider>
  );
};
