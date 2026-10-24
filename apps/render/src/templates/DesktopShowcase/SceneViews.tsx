import React from "react";
import { AbsoluteFill, Freeze, Img, OffthreadVideo, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { resolveAsset } from "../../assets";
import { cameraAt, cursorAt, project } from "../../camera";
import type { Scene } from "../../generated";
import type { SceneAssets } from "../../props";
import { useTheme } from "../../theme/context";
import { clipPlayback } from "./playback";
import { MEDIA } from "./layout";

const FRAME = { w: MEDIA.w, h: MEDIA.h };

export type ViewProps = { scene: Scene; assets: SceneAssets; durationInFrames: number; productName: string };

export const hasClip = (a: SceneAssets) => Boolean(a.clip_url);
export const hasShot = (a: SceneAssets) => Boolean(a.screenshot_url);

/** White arrow with a black outline; the tip is at (0,0) of the returned box. */
export const Arrow: React.FC<{ press: number }> = ({ press }) => (
  <svg
    width={34}
    height={48}
    viewBox="0 0 20 28"
    style={{ display: "block", transform: `scale(${1 - 0.2 * press})`, transformOrigin: "3.4px 3.4px", overflow: "visible" }}
  >
    <path
      d="M2 2 L2 22 L7 17.5 L10.6 25.5 L13.8 24.1 L10.3 16.4 L17 16 Z"
      fill="#fff"
      stroke="#000"
      strokeWidth={1.6}
      strokeLinejoin="round"
    />
  </svg>
);

/** The recorded clip, seen through the virtual camera, with the drawn cursor and click ripples. */
const ClipView: React.FC<{ assets: SceneAssets; durationInFrames: number }> = ({ assets, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { motion, highlight } = useTheme();
  const clip = { w: assets.clip_width ?? 1920, h: assets.clip_height ?? 1080 };
  const { startMs, rate, lastFrame } = clipPlayback(assets, fps, durationInFrames);
  const clicks = assets.click_log ?? [];
  // the video holds its last frame once past the end (freeze_last_frame, and the crossfade overrun)
  const shown = lastFrame === null ? frame : Math.min(frame, lastFrame);
  const tMs = startMs + (shown / fps) * 1000 * rate; // click_log is in clip time
  const cam = cameraAt(tMs, clicks, clip, FRAME, { spring: motion.spring, clickZoom: motion.clickZoom });
  const cursor = cursorAt(tMs, clicks, clip, FRAME);
  const tip = project(cursor, cam);

  return (
    <AbsoluteFill style={{ overflow: "hidden", background: "#000" }}>
      <div
        style={{
          width: FRAME.w,
          height: FRAME.h,
          transformOrigin: "0 0",
          transform: `translate(${-cam.left * cam.scale}px, ${-cam.top * cam.scale}px) scale(${cam.scale})`,
        }}
      >
        <Freeze frame={shown}>
          <OffthreadVideo
            src={resolveAsset(assets.clip_url!)}
            startFrom={Math.round((startMs / 1000) * fps)}
            playbackRate={rate}
            muted
            style={{ width: FRAME.w, height: FRAME.h, objectFit: "cover", display: "block" }}
          />
        </Freeze>
      </div>
      {cursor.ripples.map((r, i) => {
        const p = project(r, cam);
        const size = 24 + r.age * 110;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: p.x - size / 2,
              top: p.y - size / 2,
              width: size,
              height: size,
              borderRadius: "50%",
              border: `4px solid ${highlight}`,
              opacity: (1 - r.age) * 0.85,
            }}
          />
        );
      })}
      <div style={{ position: "absolute", left: tip.x - 3.4, top: tip.y - 3.4, opacity: cursor.opacity }}>
        <Arrow press={cursor.press} />
      </div>
    </AbsoluteFill>
  );
};

/** Screenshot with a slow Ken Burns drift. */
const ShotView: React.FC<{ assets: SceneAssets; durationInFrames: number; blur?: boolean }> = ({
  assets,
  durationInFrames,
  blur,
}) => {
  const frame = useCurrentFrame();
  const { motion } = useTheme();
  const progress = interpolate(frame, [0, durationInFrames], [0, 1], { extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ overflow: "hidden", background: "#000" }}>
      <Img
        src={resolveAsset(assets.screenshot_url!)}
        style={{
          width: FRAME.w,
          height: FRAME.h,
          objectFit: "cover",
          transform: `scale(${1.04 + motion.kenBurns * progress})`,
          filter: blur ? "blur(14px) brightness(0.5)" : undefined,
        }}
      />
    </AbsoluteFill>
  );
};

export const Backdrop: React.FC<{ children?: React.ReactNode }> = ({ children }) => {
  const { primary } = useTheme();
  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(ellipse at 50% 30%, ${primary}55 0%, #0B1426 75%)`,
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      {children}
    </AbsoluteFill>
  );
};

export const usePop = (delay = 0) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { motion } = useTheme();
  return spring({ frame: frame - delay, fps, config: motion.spring, durationInFrames: 18 });
};

export const BigLine: React.FC<{ text: string; size?: number }> = ({ text, size = 58 }) => {
  const { fontFamily } = useTheme();
  const pop = usePop();
  return (
    <div
      style={{
        fontFamily,
        fontWeight: 800,
        fontSize: size,
        lineHeight: 1.2,
        color: "#fff",
        textAlign: "center",
        padding: "0 56px",
        transform: `scale(${0.8 + 0.2 * pop})`,
        opacity: Math.min(1, pop * 2),
        textShadow: "0 6px 28px rgba(0,0,0,0.5)",
      }}
    >
      {text}
    </div>
  );
};

const HookView: React.FC<ViewProps> = ({ scene, assets, durationInFrames }) => (
  <AbsoluteFill>
    {hasShot(assets) ? <ShotView assets={assets} durationInFrames={durationInFrames} blur /> : <Backdrop />}
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
      <BigLine text={scene.on_screen_text ?? scene.voiceover} size={64} />
    </AbsoluteFill>
  </AbsoluteFill>
);

const CtaView: React.FC<ViewProps> = ({ scene, productName }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { accent, fontFamily } = useTheme();
  const pulse = 1 + 0.045 * Math.sin((frame / fps) * Math.PI * 2 * 1.4);
  const glow = 0.45 + 0.35 * (0.5 + 0.5 * Math.sin((frame / fps) * Math.PI * 2 * 1.4));
  return (
    <Backdrop>
      <BigLine text={productName} size={70} />
      <div
        style={{
          marginTop: 38,
          padding: "20px 56px",
          borderRadius: 999,
          background: accent,
          color: "#111",
          fontFamily,
          fontWeight: 800,
          fontSize: 38,
          transform: `scale(${pulse})`,
          boxShadow: `0 0 ${34 * glow}px ${accent}`,
        }}
      >
        {scene.on_screen_text ?? "Dùng thử ngay"}
      </div>
    </Backdrop>
  );
};

export const BeforeAfterView: React.FC<ViewProps> = ({ scene }) => {
  const { primary, fontFamily } = useTheme();
  const pop = usePop(4);
  if (scene.type !== "before_after") return null;
  const side = (label: string, text: string, after: boolean): React.ReactNode => (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 18,
        padding: "0 34px",
        fontFamily,
        textAlign: "center",
        background: after ? `linear-gradient(160deg, ${primary}, ${primary}99)` : "#161B26",
        color: after ? "#fff" : "#9AA3B5",
        boxShadow: after ? `inset 0 0 60px ${primary}` : undefined,
      }}
    >
      <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: "0.14em", opacity: 0.85 }}>{label}</div>
      <div style={{ fontSize: after ? 44 : 38, fontWeight: after ? 800 : 500, lineHeight: 1.25 }}>{text}</div>
    </div>
  );
  return (
    <AbsoluteFill style={{ display: "flex", flexDirection: "row", opacity: Math.min(1, pop * 2) }}>
      {side("TRƯỚC", scene.before_text, false)}
      {side("SAU", scene.after_text, true)}
    </AbsoluteFill>
  );
};

export const FeatureCard: React.FC<ViewProps> = ({ scene }) => (
  <Backdrop>
    <BigLine text={scene.on_screen_text ?? (scene.type === "feature_demo" ? scene.feature : scene.voiceover)} />
  </Backdrop>
);

/** Content of the media frame for one scene. before_after and CTA are drawn; others show footage. */
export const SceneView: React.FC<ViewProps> = (props) => {
  const { scene, assets, durationInFrames } = props;
  if (scene.type === "before_after") return <BeforeAfterView {...props} />;
  if (scene.type === "cta") return <CtaView {...props} />;
  if (scene.type === "hook") return <HookView {...props} />;
  if (hasClip(assets)) return <ClipView assets={assets} durationInFrames={durationInFrames} />;
  if (hasShot(assets)) return <ShotView assets={assets} durationInFrames={durationInFrames} />;
  return <FeatureCard {...props} />;
};
