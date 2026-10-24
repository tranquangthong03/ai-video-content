import { createContext, useContext } from "react";
import type { Theme } from "../generated";
import { MOTION, type MotionPreset } from "./motion";

export type ThemeValue = {
  primary: string;
  accent: string;
  fontFamily: string;
  logo: string | null;
  captionStyle: Theme["caption_style"];
  motion: MotionPreset;
};

export const FALLBACK_FONT = "Inter";

export const ThemeContext = createContext<ThemeValue>({
  primary: "#4F46E5",
  accent: "#F59E0B",
  fontFamily: FALLBACK_FONT,
  logo: null,
  captionStyle: "minimal",
  motion: MOTION.calm,
});

export const useTheme = () => useContext(ThemeContext);
