/** Colors drawn on the dark template background must stay readable; the theme primary may not be. */

export const TEMPLATE_BG = "#0B1426";
export const MIN_CONTRAST = 4.5;

type Rgb = [number, number, number];
type Hsl = [number, number, number]; // h in degrees, s and l in 0..1

export function hexToRgb(hex: string): Rgb {
  const h = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as Rgb;
}

export const rgbToHex = ([r, g, b]: Rgb): string =>
  "#" + [r, g, b].map((v) => Math.round(Math.min(255, Math.max(0, v))).toString(16).padStart(2, "0")).join("");

/** WCAG relative luminance. */
export function luminance(hex: string): number {
  const lin = hexToRgb(hex).map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
}

export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

export function rgbToHsl([r, g, b]: Rgb): Hsl {
  const [rn, gn, bn] = [r / 255, g / 255, b / 255];
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h: number;
  if (max === rn) h = (gn - bn) / d + (gn < bn ? 6 : 0);
  else if (max === gn) h = (bn - rn) / d + 2;
  else h = (rn - gn) / d + 4;
  return [h * 60, s, l];
}

export function hslToRgb([h, s, l]: Hsl): Rgb {
  if (s === 0) return [l * 255, l * 255, l * 255];
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  const channel = (t0: number) => {
    let t = t0;
    if (t < 0) t += 1;
    if (t > 1) t -= 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };
  const hk = h / 360;
  return [channel(hk + 1 / 3) * 255, channel(hk) * 255, channel(hk - 1 / 3) * 255];
}

/**
 * The theme primary, lightened (same hue) until it reaches `minRatio` contrast against `bg`.
 * Used for text and small icons; borders and glows keep the original primary. Mirrored in
 * services/api/app/script/theme.py (highlight_color); keep the two in step.
 */
export function highlightColor(primary: string, bg = TEMPLATE_BG, minRatio = MIN_CONTRAST): string {
  const start = primary.toLowerCase();
  if (contrastRatio(start, bg) >= minRatio) return start;
  const [h, s, l] = rgbToHsl(hexToRgb(start));
  for (let step = 1; step <= 100; step++) {
    const lightness = Math.min(1, l + step * 0.01);
    const hex = rgbToHex(hslToRgb([h, s, lightness]));
    if (contrastRatio(hex, bg) >= minRatio) return hex;
    if (lightness >= 1) break;
  }
  return "#ffffff";
}
