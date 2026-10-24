import React from "react";
import { AbsoluteFill, Freeze, Img, OffthreadVideo, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { resolveAsset } from "../../assets";
import {
  CAMERA_CONFIG,
  cursorAt,
  focusCameraAt,
  focusFromClicks,
  insideClip,
  lerpView,
  targetView,
  viewTransform,
  type FocusLike,
} from "../../camera";
import type { SceneAssets } from "../../props";
import { useTheme } from "../../theme/context";
import { clipPlayback } from "../DesktopShowcase/playback";
import { Arrow, BeforeAfterView, Backdrop, BigLine, FeatureCard, hasClip, hasShot, type ViewProps } from "../DesktopShowcase/SceneViews";
import { MEDIA, OVERLAY } from "./layout";

const FRAME = { w: MEDIA.w, h: MEDIA.h };
const DEFAULT_CLIP = { w: 1440, h: 900 };

const clipSize = (a: SceneAssets) => ({ w: a.clip_width ?? DEFAULT_CLIP.w, h: a.clip_height ?? DEFAULT_CLIP.h });
const focusOf = (a: SceneAssets): FocusLike[] =>
  a.focus_log?.length ? a.focus_log : focusFromClicks(a.click_log ?? []);

/** The recorded clip seen through the focus camera, with the drawn cursor and click ripples. */
export const FocusClip: React.FC<{ assets: SceneAssets; durationInFrames: number }> = ({ assets, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { highlight } = useTheme();
  const clip = clipSize(assets);
  const { startMs, rate, lastFrame } = clipPlayback(assets, fps, durationInFrames);
  const shown = lastFrame === null ? frame : Math.min(frame, lastFrame);
  const tMs = startMs + (shown / fps) * 1000 * rate; // the logs are in clip time
  const cam = focusCameraAt(tMs, focusOf(assets), clip, FRAME);
  const { scale, translateX, translateY } = viewTransform(cam.view, FRAME);
  // cursor and ripples in clip pixels (frame = clip: identity mapping), then through the camera
  const clicks = assets.click_log ?? [];
  const cursor = cursorAt(tMs, clicks, clip, clip);
  const toScreen = (p: { x: number; y: number }) => ({ x: (p.x - cam.view.x) * scale, y: (p.y - cam.view.y) * scale });
  const tip = toScreen(cursor);
  const src = resolveAsset(assets.clip_url!);
  const startFrom = Math.round((startMs / 1000) * fps);

  return (
    <AbsoluteFill style={{ overflow: "hidden", background: "#000" }}>
      {cam.establishing > 0.001 && (
        // the establishing shot is shorter than the frame is tall: the clip itself, enlarged, blurred and dimmed fills the rest
        <Freeze frame={shown}>
          <OffthreadVideo
            src={src}
            startFrom={startFrom}
            playbackRate={rate}
            muted
            style={{
              width: FRAME.w,
              height: FRAME.h,
              objectFit: "cover",
              transform: "scale(1.12)",
              filter: `blur(${CAMERA_CONFIG.backdrop.blurPx}px) brightness(${CAMERA_CONFIG.backdrop.brightness})`,
            }}
          />
        </Freeze>
      )}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          width: clip.w,
          height: clip.h,
          transformOrigin: "0 0",
          transform: `translate(${translateX}px, ${translateY}px) scale(${scale})`,
        }}
      >
        <Freeze frame={shown}>
          <OffthreadVideo
            src={src}
            startFrom={startFrom}
            playbackRate={rate}
            muted
            style={{ width: clip.w, height: clip.h, display: "block" }}
          />
        </Freeze>
      </div>
      {cursor.ripples.map((r, i) => {
        const p = toScreen(r);
        const size = 30 + r.age * 130;
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
              border: `5px solid ${highlight}`,
              opacity: (1 - r.age) * 0.85,
            }}
          />
        );
      })}
      <div style={{ position: "absolute", left: tip.x - 4, top: tip.y - 4, opacity: cursor.opacity, transform: "scale(1.25)", transformOrigin: "4px 4px" }}>
        <Arrow press={cursor.press} />
      </div>
    </AbsoluteFill>
  );
};

/** A screenshot with a slow Ken Burns move toward the focus box (or a gentle drift without one). */
export const FocusShot: React.FC<{ assets: SceneAssets; durationInFrames: number }> = ({ assets, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { motion } = useTheme();
  const clip = clipSize(assets);
  const progress = interpolate(frame, [0, durationInFrames], [0, 1], { extrapolateRight: "clamp" });
  const reach = 1 + 4 * motion.kenBurns; // how far in it may go (cover units)
  const start = insideClip(clip.w / 2, clip.h / 2, 1, clip, FRAME);
  const first = focusOf(assets)[0];
  const end = first
    ? targetView(first, clip, FRAME, { ...CAMERA_CONFIG, maxZoom: Math.min(CAMERA_CONFIG.maxZoom, reach) })
    : insideClip(clip.w / 2, clip.h / 2, 1 + 2 * motion.kenBurns, clip, FRAME);
  const ease = progress * progress * (3 - 2 * progress);
  const { scale, translateX, translateY } = viewTransform(lerpView(start, end, ease), FRAME);
  return (
    <AbsoluteFill style={{ overflow: "hidden", background: "#000" }}>
      <Img
        src={resolveAsset(assets.screenshot_url!)}
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          width: clip.w,
          height: clip.h,
          transformOrigin: "0 0",
          transform: `translate(${translateX}px, ${translateY}px) scale(${scale})`,
        }}
      />
    </AbsoluteFill>
  );
};

const Footage: React.FC<{ assets: SceneAssets; durationInFrames: number }> = ({ assets, durationInFrames }) =>
  hasClip(assets) ? (
    <FocusClip assets={assets} durationInFrames={durationInFrames} />
  ) : (
    <FocusShot assets={assets} durationInFrames={durationInFrames} />
  );

/** on_screen_text laid lightly over the top of the footage, on a fading dark gradient. */
const TopText: React.FC<{ text: string | null | undefined }> = ({ text }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { fontFamily, motion } = useTheme();
  if (!text) return null;
  const pop = spring({ frame: frame - 6, fps, config: motion.spring, durationInFrames: 18 });
  return (
    <>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: 0,
          height: OVERLAY.topGradient,
          background: "linear-gradient(to bottom, rgba(5,7,13,0.78), rgba(5,7,13,0))",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 48,
          right: 48,
          top: OVERLAY.textTop,
          textAlign: "center",
          fontFamily,
          fontWeight: 800,
          fontSize: 58,
          lineHeight: 1.2,
          color: "#fff",
          opacity: Math.min(1, pop * 2),
          transform: `translateY(${(1 - pop) * -16}px)`,
          textShadow: "0 4px 20px rgba(0,0,0,0.7)",
        }}
      >
        {text}
      </div>
    </>
  );
};

/** The CTA button: pulses, and only appears for the last third of the scene. */
const CtaButton: React.FC<{ text: string; durationInFrames: number }> = ({ text, durationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { accent, fontFamily, motion } = useTheme();
  const from = Math.round((durationInFrames * 2) / 3);
  if (frame < from) return null;
  const pop = spring({ frame: frame - from, fps, config: motion.spring, durationInFrames: 18 });
  const pulse = 1 + 0.045 * Math.sin((frame / fps) * Math.PI * 2 * 1.4);
  const glow = 0.45 + 0.35 * (0.5 + 0.5 * Math.sin((frame / fps) * Math.PI * 2 * 1.4));
  return (
    <div style={{ position: "absolute", left: 0, right: 0, bottom: OVERLAY.ctaBottom, display: "flex", justifyContent: "center", opacity: Math.min(1, pop * 2) }}>
      <div
        style={{
          padding: "22px 60px",
          borderRadius: 999,
          background: accent,
          color: "#111",
          fontFamily,
          fontWeight: 800,
          fontSize: 42,
          transform: `scale(${(0.8 + 0.2 * pop) * pulse})`,
          boxShadow: `0 0 ${38 * glow}px ${accent}`,
        }}
      >
        {text}
      </div>
    </div>
  );
};

const HookView: React.FC<ViewProps> = ({ scene, assets, durationInFrames }) => {
  if (!hasClip(assets) && !hasShot(assets)) {
    return (
      <Backdrop>
        <BigLine text={scene.on_screen_text ?? scene.voiceover} size={64} />
      </Backdrop>
    );
  }
  return (
    <AbsoluteFill>
      <Footage assets={assets} durationInFrames={durationInFrames} />
      <TopText text={scene.on_screen_text} />
    </AbsoluteFill>
  );
};

const CtaView: React.FC<ViewProps> = ({ scene, assets, durationInFrames, productName }) => {
  const label = scene.on_screen_text ?? "Dùng thử ngay";
  if (!hasClip(assets) && !hasShot(assets)) {
    return (
      <Backdrop>
        <BigLine text={productName} size={70} />
        <div style={{ marginTop: 38 }}>
          <CtaButtonStatic text={label} />
        </div>
      </Backdrop>
    );
  }
  return (
    <AbsoluteFill>
      <Footage assets={assets} durationInFrames={durationInFrames} />
      <TopText text={productName} />
      <CtaButton text={label} durationInFrames={durationInFrames} />
    </AbsoluteFill>
  );
};

const CtaButtonStatic: React.FC<{ text: string }> = ({ text }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { accent, fontFamily } = useTheme();
  const pulse = 1 + 0.045 * Math.sin((frame / fps) * Math.PI * 2 * 1.4);
  return (
    <div style={{ padding: "22px 60px", borderRadius: 999, background: accent, color: "#111", fontFamily, fontWeight: 800, fontSize: 42, transform: `scale(${pulse})` }}>
      {text}
    </div>
  );
};

/** Content of the 4:5 media frame for one scene. */
export const FocusSceneView: React.FC<ViewProps> = (props) => {
  const { scene, assets, durationInFrames } = props;
  if (scene.type === "before_after") return <BeforeAfterView {...props} />;
  if (scene.type === "cta") return <CtaView {...props} />;
  if (scene.type === "hook") return <HookView {...props} />;
  if (hasClip(assets) || hasShot(assets)) return <Footage assets={assets} durationInFrames={durationInFrames} />;
  return <FeatureCard {...props} />;
};
