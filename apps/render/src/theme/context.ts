import { createContext, useContext } from "react";
import { highlightColor } from "../color";
import type { Theme } from "../generated";
import { MOTION, type MotionPreset } from "./motion";

export type ThemeValue = {
  primary: string;
  /** primary lightened to be readable on the template background (text, icons, ripples) */
  highlight: string;
  accent: string;
  fontFamily: string;
  logo: string | null;
  captionStyle: Theme["caption_style"];
  motion: MotionPreset;
};

export const FALLBACK_FONT = "Be Vietnam Pro";

export const ThemeContext = createContext<ThemeValue>({
  primary: "#4F46E5",
  highlight: highlightColor("#4F46E5"),
  accent: "#F59E0B",
  fontFamily: FALLBACK_FONT,
  logo: null,
  captionStyle: "minimal",
  motion: MOTION.calm,
});

export const useTheme = () => useContext(ThemeContext);
