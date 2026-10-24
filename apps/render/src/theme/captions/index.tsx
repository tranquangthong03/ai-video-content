import React from "react";
import type { Caption } from "../../props";
import { useTheme } from "../context";
import { Karaoke } from "./Karaoke";
import { Minimal } from "./Minimal";
import { TikTokBounce } from "./TikTokBounce";

/** Picks the caption renderer from theme.caption_style. */
export const Captions: React.FC<{ captions: Caption[] }> = ({ captions }) => {
  const { captionStyle } = useTheme();
  if (captionStyle === "tiktok_bounce") return <TikTokBounce captions={captions} />;
  if (captionStyle === "karaoke") return <Karaoke captions={captions} />;
  return <Minimal captions={captions} />;
};
