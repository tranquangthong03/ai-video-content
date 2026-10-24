import React from "react";
import type { Scene } from "../generated";

/** The icon names scenes may use (generated from scene.json). */
export type IconName = NonNullable<Scene["icon"]>;

/** Simple 24x24 line icons, stroke 2, drawn here so no icon font or network is needed. */
export const ICON_PATHS: Record<IconName, string[]> = {
  check: ["M5 12.5l4.5 4.5L19.5 7"],
  globe: ["M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18z", "M3 12h18", "M12 3c3.2 3.4 3.2 14.6 0 18", "M12 3c-3.2 3.4-3.2 14.6 0 18"],
  bolt: ["M13 2L4 14h7l-1 8 9-12h-7z"],
  link: ["M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1", "M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"],
  star: ["M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"],
  users: [
    "M9 4.5a3.5 3.5 0 1 0 0 7a3.5 3.5 0 0 0 0-7z",
    "M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6",
    "M17 6.5a2.7 2.7 0 1 1 0 5.4",
    "M18 14.2c2.4.5 4 2.3 4 5.3",
  ],
  chart: ["M3 21h18", "M6 21v-6", "M12 21V5", "M18 21V11"],
  lock: ["M7 11h10a2 2 0 0 1 2 2v7a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-7a2 2 0 0 1 2-2z", "M8 11V8a4 4 0 0 1 8 0v3"],
  sparkles: [
    "M11 3l1.8 5.2L18 10l-5.2 1.8L11 17l-1.8-5.2L4 10l5.2-1.8z",
    "M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z",
  ],
  code: ["M8 7l-5 5 5 5", "M16 7l5 5-5 5", "M14 4l-4 16"],
  image: ["M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z", "M9 8a1.8 1.8 0 1 0 0 3.6A1.8 1.8 0 0 0 9 8z", "M21 16l-5-5-8 9"],
  edit: ["M12 20h9", "M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"],
  filter: ["M3 5h18l-7 8v6l-4 2v-8z"],
  upload: ["M12 16V4", "M7 9l5-5 5 5", "M4 20h16"],
};

export const ICON_NAMES = Object.keys(ICON_PATHS) as IconName[];

export const Icon: React.FC<{ name: IconName; size?: number; color?: string }> = ({
  name,
  size = 32,
  color = "currentColor",
}) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke={color}
    strokeWidth={2}
    strokeLinecap="round"
    strokeLinejoin="round"
    style={{ display: "block", flexShrink: 0 }}
  >
    {ICON_PATHS[name].map((d, i) => (
      <path key={i} d={d} />
    ))}
  </svg>
);
