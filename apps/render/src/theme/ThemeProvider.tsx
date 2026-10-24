import { getAvailableFonts } from "@remotion/google-fonts";
import React, { useEffect, useMemo, useState } from "react";
import { cancelRender, continueRender, delayRender } from "remotion";
import type { Theme } from "../generated";
import { FALLBACK_FONT, ThemeContext, type ThemeValue } from "./context";
import { MOTION } from "./motion";

type Loader = (
  style: string,
  options: { weights: string[]; subsets: string[] },
) => { fontFamily: string; waitUntilDone: () => Promise<unknown> };

/** Loads a Google Font by family name; falls back to Inter when unsupported or loading fails. */
async function loadFontFamily(name: string): Promise<string> {
  const fonts = getAvailableFonts();
  const find = (n: string) => fonts.find((f) => f.fontFamily.toLowerCase() === n.toLowerCase());
  for (const candidate of [find(name), find(FALLBACK_FONT)]) {
    if (!candidate) continue;
    try {
      const mod = await candidate.load();
      const { fontFamily, waitUntilDone } = (mod.loadFont as unknown as Loader)("normal", {
        weights: ["400", "700", "900"],
        subsets: ["latin", "latin-ext", "vietnamese"],
      });
      await waitUntilDone();
      return fontFamily;
    } catch {
      // try the next candidate
    }
  }
  return FALLBACK_FONT;
}

export const ThemeProvider: React.FC<{ theme: Theme; children: React.ReactNode }> = ({
  theme,
  children,
}) => {
  const [handle] = useState(() => delayRender(`font ${theme.font}`));
  const [fontFamily, setFontFamily] = useState(FALLBACK_FONT);

  useEffect(() => {
    loadFontFamily(theme.font)
      .then(setFontFamily)
      .then(() => continueRender(handle))
      .catch((e) => cancelRender(e));
  }, [theme.font, handle]);

  const value = useMemo<ThemeValue>(
    () => ({
      primary: theme.primary,
      accent: theme.accent,
      fontFamily: `${fontFamily}, sans-serif`,
      logo: theme.logo_asset ?? null,
      captionStyle: theme.caption_style,
      motion: MOTION[theme.motion_preset],
    }),
    [theme, fontFamily],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
};
