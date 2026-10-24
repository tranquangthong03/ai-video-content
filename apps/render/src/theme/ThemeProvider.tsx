import { loadFont as loadBeVietnamPro } from "@remotion/google-fonts/BeVietnamPro";
import React, { useEffect, useMemo, useState } from "react";
import { cancelRender, continueRender, delayRender } from "remotion";
import type { Theme } from "../generated";
import { FALLBACK_FONT, ThemeContext, type ThemeValue } from "./context";
import { MOTION } from "./motion";

/**
 * Fonts the renderer can load. Each is imported from its own module (not getAvailableFonts(), which
 * pulls every Google font into the bundle). Only the subsets and weights the templates use are fetched,
 * and "vietnamese" is required so diacritics render. A theme font not listed here uses FALLBACK_FONT.
 */
const FONT_OPTIONS: { weights: ("500" | "700" | "800")[]; subsets: ("latin" | "vietnamese")[] } = {
  weights: ["500", "700", "800"],
  subsets: ["latin", "vietnamese"],
};
const FONTS: Record<string, () => { fontFamily: string; waitUntilDone: () => Promise<unknown> }> = {
  "be vietnam pro": () => loadBeVietnamPro("normal", FONT_OPTIONS),
};

/** Loads the theme font (or the fallback) and returns its CSS family name. */
export async function loadThemeFont(name: string): Promise<string> {
  const load = FONTS[name.toLowerCase()] ?? FONTS[FALLBACK_FONT.toLowerCase()];
  const { fontFamily, waitUntilDone } = load();
  await waitUntilDone();
  return fontFamily;
}

export const ThemeProvider: React.FC<{ theme: Theme; children: React.ReactNode }> = ({
  theme,
  children,
}) => {
  const [handle] = useState(() => delayRender(`font ${theme.font}`));
  const [fontFamily, setFontFamily] = useState(FALLBACK_FONT);

  useEffect(() => {
    loadThemeFont(theme.font)
      .then(setFontFamily)
      .then(() => continueRender(handle))
      .catch((e) => cancelRender(e));
  }, [theme.font, handle]);

  const value = useMemo<ThemeValue>(
    () => ({
      primary: theme.primary,
      accent: theme.accent,
      fontFamily: `"${fontFamily}", sans-serif`,
      logo: theme.logo_asset ?? null,
      captionStyle: theme.caption_style,
      motion: MOTION[theme.motion_preset],
    }),
    [theme, fontFamily],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
};
