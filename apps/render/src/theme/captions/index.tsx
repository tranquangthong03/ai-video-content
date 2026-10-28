import React from "react";
import type { Caption } from "../../props";
import { useTheme } from "../context";
import { Karaoke } from "./Karaoke";
import { Minimal } from "./Minimal";
import { TikTokBounce } from "./TikTokBounce";

/** Picks the caption renderer from theme.caption_style. */
export const Captions: React.FC<{ captions: Caption[]; paddingBottom?: number; fontSize?: number }> = ({ captions, paddingBottom, fontSize }) => {
  const { captionStyle } = useTheme();
  if (captionStyle === "tiktok_bounce") return <TikTokBounce captions={captions} paddingBottom={paddingBottom} />;
  if (captionStyle === "karaoke") return <Karaoke captions={captions} paddingBottom={paddingBottom} fontSize={fontSize} />;
  return <Minimal captions={captions} paddingBottom={paddingBottom} />;
};
