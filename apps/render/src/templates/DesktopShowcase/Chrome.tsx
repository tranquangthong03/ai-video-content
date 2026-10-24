import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { Icon, type IconName } from "../../icons";
import { useTheme } from "../../theme/context";
import { BULLET, BULLET_AREA_HEIGHT, HEADER, CANVAS, placeBullets, splitHeadline } from "./layout";

/** mulberry32: small seeded PRNG so the star field is identical on every render. */
function rng(seed: number) {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const STARS = (() => {
  const r = rng(20240607);
  return Array.from({ length: 64 }, () => ({
    x: r() * CANVAS.w,
    y: r() * CANVAS.h,
    r: 0.7 + r() * 1.5,
    speed: 3 + r() * 9, // px per second, downward
    phase: r() * Math.PI * 2,
    rate: 0.4 + r() * 0.9,
  }));
})();

/** Dark gradient, slowly drifting stars and a thin primary -> accent line along the top edge. */
export const Background: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { primary, accent } = useTheme();
  const t = frame / fps;
  return (
    <AbsoluteFill style={{ background: "linear-gradient(180deg, #070B14 0%, #0B1426 100%)" }}>
      <AbsoluteFill style={{ background: `radial-gradient(ellipse at 50% 18%, ${primary}2e 0%, transparent 62%)` }} />
      <svg width={CANVAS.w} height={CANVAS.h} style={{ position: "absolute", inset: 0 }}>
        {STARS.map((s, i) => (
          <circle
            key={i}
            cx={s.x}
            cy={(s.y + s.speed * t) % CANVAS.h}
            r={s.r}
            fill="#fff"
            opacity={0.2 + 0.45 * (0.5 + 0.5 * Math.sin(s.phase + t * s.rate))}
          />
        ))}
      </svg>
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 4,
          background: `linear-gradient(90deg, ${primary}, ${accent})`,
        }}
      />
    </AbsoluteFill>
  );
};

/** Badge pill (optional) over the headline; pinned for the whole video, fades/slides in once. */
export const Header: React.FC<{ badge: string | null; headline: string; highlight: string | null }> = ({
  badge,
  headline,
  highlight,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { primary, fontFamily } = useTheme();
  const appear = interpolate(frame, [0, Math.round(0.5 * fps)], [0, 1], { extrapolateRight: "clamp" });
  const { before, mark, after } = splitHeadline(headline, highlight);
  return (
    <div
      style={{
        position: "absolute",
        top: HEADER.top,
        height: HEADER.height,
        left: 0,
        right: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center", // no badge -> the headline settles in the middle of the band
        gap: 26,
        opacity: appear,
        transform: `translateY(${(1 - appear) * 12}px)`,
        fontFamily,
      }}
    >
      {badge && (
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 12,
            padding: "12px 28px",
            borderRadius: 999,
            border: `1.5px solid ${primary}`,
            background: `${primary}1f`,
            color: "#E6EAF5",
            fontSize: 26,
            fontWeight: 700,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
          }}
        >
          <Icon name="code" size={26} color={primary} />
          {badge}
        </div>
      )}
      <div
        style={{
          maxWidth: 940,
          textAlign: "center",
          color: "#fff",
          fontSize: 60,
          fontWeight: 800,
          lineHeight: 1.2,
          textWrap: "balance",
        }}
      >
        {before}
        {mark && <span style={{ color: primary }}>{mark}</span>}
        {after}
      </div>
    </div>
  );
};

/** key_point pills under the media frame: scenes so far, newest at the bottom, at most four. */
export const Bullets: React.FC<{ items: { start: number; text: string; icon: IconName | null }[] }> = ({
  items,
}) => {
  const frame = useCurrentFrame();
  const { primary, fontFamily } = useTheme();
  const placed = placeBullets(
    items.map((i) => i.start),
    frame,
  );
  return (
    <div
      style={{
        position: "absolute",
        left: 60,
        right: 60,
        top: BULLET.top,
        height: BULLET_AREA_HEIGHT,
        overflow: "hidden",
      }}
    >
      {placed.map((p) => {
        const item = items[p.index];
        return (
          <div
            key={p.index}
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              top: 0,
              height: BULLET.pill,
              transform: `translateY(${p.slot * (BULLET.pill + BULLET.gap) + (1 - p.enter) * 28}px)`,
              opacity: p.opacity,
              display: "flex",
              alignItems: "center",
              gap: 18,
              padding: "0 26px",
              borderRadius: 16,
              background: "rgba(255,255,255,0.06)",
              border: "1px solid rgba(255,255,255,0.12)",
              color: "#fff",
              fontFamily,
              fontSize: 30,
              fontWeight: 500,
              whiteSpace: "nowrap",
            }}
          >
            {item.icon ? (
              <Icon name={item.icon} size={34} color={primary} />
            ) : (
              // no icon: a small dot keeps the text aligned with the other rows
              <div style={{ width: 34, height: 34, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <div style={{ width: 12, height: 12, borderRadius: 6, background: primary }} />
              </div>
            )}
            {item.text}
          </div>
        );
      })}
    </div>
  );
};
