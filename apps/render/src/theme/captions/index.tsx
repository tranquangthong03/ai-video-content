import React from "react";
import type { Caption } from "../../props";
import { useTheme } from "../context";
import { Minimal } from "./Minimal";
import { TikTokBounce } from "./TikTokBounce";

/** Picks the caption renderer from theme.caption_style. */
export const Captions: React.FC<{ captions: Caption[] }> = ({ captions }) => {
  const { captionStyle } = useTheme();
  return captionStyle === "tiktok_bounce" ? (
    <TikTokBounce captions={captions} />
  ) : (
    <Minimal captions={captions} />
  );
};
