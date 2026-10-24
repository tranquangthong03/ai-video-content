import { bundle } from "@remotion/bundler";
import { ensureBrowser, renderMedia, selectComposition } from "@remotion/renderer";
import { randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";
import { createServer } from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { COMPOSITION_ID } from "./compositionId";
import type { InputProps } from "./props";
import { webpackOverride } from "./webpackOverride";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const OUT_DIR = path.join(root, "out");

let bundlePromise: Promise<string> | null = null;

/** Bundles the Remotion project once; later renders reuse the same serve URL. */
export function getBundle(): Promise<string> {
  bundlePromise ??= bundle({
    entryPoint: path.join(root, "src", "index.ts"),
    publicDir: path.join(root, "public"),
    webpackOverride,
    onProgress: (p) => {
      if (p % 25 === 0) console.log(`[bundle] ${p}%`);
    },
  }).catch((e) => {
    bundlePromise = null; // allow a retry after a failed bundle
    throw e;
  });
  return bundlePromise;
}

/**
 * Remotion serves the bundle on a local port starting at 3000. That port is often taken by another
 * app (e.g. the web container), and the browser then loads the wrong page. Ask the OS for a free one.
 */
export function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, () => {
      const { port } = server.address() as { port: number };
      server.close(() => resolve(port));
    });
  });
}

export type RenderResult = { file: string; durationMs: number; renderMs: number };

export type RenderOptions = {
  logLevel?: "verbose" | "info" | "warn" | "error";
  /** Called when a pipeline stage starts: browser, bundle, composition, frames. */
  onStage?: (stage: string) => void;
};

export async function renderVideo(
  props: InputProps,
  outFile?: string,
  { logLevel = "info", onStage = () => {} }: RenderOptions = {},
): Promise<RenderResult> {
  const started = Date.now();
  mkdirSync(OUT_DIR, { recursive: true });
  const file = outFile ?? path.join(OUT_DIR, `${randomUUID()}.mp4`);

  onStage("browser");
  await ensureBrowser({ logLevel });
  onStage("bundle");
  const serveUrl = await getBundle();
  onStage("composition");
  const port = await freePort();
  const composition = await selectComposition({
    serveUrl,
    id: COMPOSITION_ID,
    inputProps: props,
    logLevel,
    port,
  });
  onStage("frames");

  let lastLogged = -1;
  await renderMedia({
    composition,
    serveUrl,
    codec: "h264",
    pixelFormat: "yuv420p",
    outputLocation: file,
    inputProps: props,
    logLevel,
    port,
    onProgress: ({ progress }) => {
      const pct = Math.floor(progress * 100);
      if (pct % 10 === 0 && pct !== lastLogged) {
        lastLogged = pct;
        console.log(`[render] ${pct}%`);
      }
    },
  });

  return {
    file,
    durationMs: Math.round((composition.durationInFrames / composition.fps) * 1000),
    renderMs: Date.now() - started,
  };
}
