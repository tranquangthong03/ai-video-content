import { describe, expect, it } from "vitest";
import { TEMPLATE_BG, contrastRatio, highlightColor, hexToRgb, rgbToHsl } from "./color";

const hue = (hex: string) => rgbToHsl(hexToRgb(hex))[0];

describe("highlightColor", () => {
  it("keeps a color that already reads well on the template background", () => {
    expect(contrastRatio("#fbbf24", TEMPLATE_BG)).toBeGreaterThanOrEqual(4.5);
    expect(highlightColor("#FBBF24")).toBe("#fbbf24");
  });

  it.each(["#1E3A8A", "#4F46E5"])("lightens %s to at least 4.5:1 without changing its hue", (primary) => {
    expect(contrastRatio(primary, TEMPLATE_BG)).toBeLessThan(4.5);
    const out = highlightColor(primary);
    expect(contrastRatio(out, TEMPLATE_BG)).toBeGreaterThanOrEqual(4.5);
    expect(Math.abs(hue(out) - hue(primary))).toBeLessThan(3);
    expect(out).not.toBe(primary.toLowerCase());
  });

  it("changes as little as possible (it stops at the first lightness that passes)", () => {
    for (const primary of ["#1E3A8A", "#4F46E5"]) {
      expect(contrastRatio(highlightColor(primary), TEMPLATE_BG)).toBeLessThan(5.2);
    }
  });

  it("falls back to white for a color that cannot be lightened enough", () => {
    expect(highlightColor("#000000", "#ffffff", 21.5)).toBe("#ffffff");
    expect(contrastRatio(highlightColor("#000000"), TEMPLATE_BG)).toBeGreaterThanOrEqual(4.5);
  });

  it("matches known values (also asserted by the Python mirror)", () => {
    const expected: Record<string, string> = {
      "#1E3A8A": "#5779db",
      "#4F46E5": "#756eeb",
      "#FBBF24": "#fbbf24",
      "#0F766E": "#128d83",
      "#B91C1C": "#e34444",
      "#111827": "#637fbb",
    };
    for (const [primary, out] of Object.entries(expected)) expect(highlightColor(primary)).toBe(out);
  });
});
