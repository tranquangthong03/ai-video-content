import React from "react";
import {
  Img,
  OffthreadVideo,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { resolveAsset } from "../assets";
import { mapClipPoint, type Box } from "../geometry";
import type { SceneAssets } from "../props";
import { useTheme } from "../theme/context";

export const hasMedia = (a: SceneAssets | undefined): a is SceneAssets =>
  Boolean(a?.clip_url || a?.screenshot_url);

/** A scene asks for click zoom when any of its browser actions has zoom=true. */
export const wantsZoom = (visual: { actions: { zoom: boolean }[] }) =>
  visual.actions.some((a) => a.zoom);

const HOLD_SECONDS = 1.2;
const CURSOR_SIZE = 56;

/** 0 -> 1 -> 0 envelope: smooth zoom in at the click, hold ~1.2s, smooth zoom out. */
function clickEnvelope(
  frame: number,
  clickFrame: number,
  fps: number,
  config: { damping: number; stiffness: number; mass: number },
): number {
  const rel = frame - clickFrame;
  if (rel < 0) return 0;
  const zoomIn = spring({ frame: rel, fps, config, durationInFrames: 14 });
  const zoomOut = spring({
    frame: rel - Math.round(HOLD_SECONDS * fps),
    fps,
    config,
    durationInFrames: 14,
  });
  return Math.max(0, zoomIn - zoomOut);
}

type Props = {
  assets: SceneAssets;
  width: number;
  height: number;
  durationInFrames: number;
  /** Zoom to logged clicks (scene has an action with zoom=true). */
  zoomEnabled?: boolean;
  style?: React.CSSProperties;
};

/**
 * Clip (preferred) or screenshot filling a width x height box with object-fit: cover.
 * Clips get click zoom + cursor; screenshots get a Ken Burns drift.
 */
export const SceneMedia: React.FC<Props> = ({
  assets,
  width,
  height,
  durationInFrames,
  zoomEnabled = false,
  style,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { motion, accent } = useTheme();

  const box: Box = { x: 0, y: 0, w: width, h: height };
  const base: React.CSSProperties = { width, height, objectFit: "cover", display: "block" };

  if (assets.clip_url) {
    const offsetMs = assets.start_offset_ms ?? 0;
    const src = { w: assets.clip_width ?? width, h: assets.clip_height ?? height };
    const clicks = zoomEnabled
      ? (assets.click_log ?? []).map((c) => ({
          ...mapClipPoint({ x: c.x, y: c.y }, src, box),
          frame: Math.round(((c.t_ms - offsetMs) / 1000) * fps),
        }))
      : [];

    let best = { env: 0, x: width / 2, y: height / 2 };
    for (const c of clicks) {
      const env = clickEnvelope(frame, c.frame, fps, motion.spring);
      if (env > best.env) best = { env, x: c.x, y: c.y };
    }
    const scale = 1 + (motion.clickZoom - 1) * best.env;

    return (
      <div style={{ width, height, overflow: "hidden", position: "relative", ...style }}>
        <div
          style={{
            width,
            height,
            position: "relative",
            transform: `scale(${scale})`,
            transformOrigin: `${best.x}px ${best.y}px`,
          }}
        >
          <OffthreadVideo
            src={resolveAsset(assets.clip_url)}
            startFrom={Math.round((offsetMs / 1000) * fps)}
            muted
            style={base}
          />
          {clicks.map((c, i) => {
            const rel = frame - c.frame;
            if (rel < -3 || rel > Math.round(HOLD_SECONDS * fps) + 10) return null;
            const appear = interpolate(rel, [-3, 3], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            const ripple = interpolate(rel, [0, 18], [0.6, 2], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            const rippleOpacity = interpolate(rel, [0, 18], [0.7, 0], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            return (
              <React.Fragment key={i}>
                <div
                  style={{
                    position: "absolute",
                    left: c.x - CURSOR_SIZE / 2,
                    top: c.y - CURSOR_SIZE / 2,
                    width: CURSOR_SIZE,
                    height: CURSOR_SIZE,
                    borderRadius: "50%",
                    background: "rgba(255,255,255,0.4)",
                    border: `4px solid ${accent}`,
                    opacity: appear,
                  }}
                />
                <div
                  style={{
                    position: "absolute",
                    left: c.x - CURSOR_SIZE / 2,
                    top: c.y - CURSOR_SIZE / 2,
                    width: CURSOR_SIZE,
                    height: CURSOR_SIZE,
                    borderRadius: "50%",
                    border: `4px solid ${accent}`,
                    transform: `scale(${ripple})`,
                    opacity: rippleOpacity,
                  }}
                />
              </React.Fragment>
            );
          })}
        </div>
      </div>
    );
  }

  if (assets.screenshot_url) {
    const progress = interpolate(frame, [0, durationInFrames], [0, 1], {
      extrapolateRight: "clamp",
    });
    const scale = 1.04 + motion.kenBurns * progress;
    return (
      <div style={{ width, height, overflow: "hidden", ...style }}>
        <Img
          src={resolveAsset(assets.screenshot_url)}
          style={{
            ...base,
            transform: `scale(${scale}) translateY(${(-progress * 2).toFixed(2)}%)`,
          }}
        />
      </div>
    );
  }

  return null;
};
