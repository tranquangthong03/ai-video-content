import { staticFile } from "remotion";

/** Absolute URLs pass through; anything else is a path inside the bundle's public dir. */
export function resolveAsset(url: string): string {
  return /^(https?:|data:|blob:|\/)/.test(url) ? url : staticFile(url);
}
