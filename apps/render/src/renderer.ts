import { bundle } from "@remotion/bundler";
import { ensureBrowser, renderMedia, selectComposition } from "@remotion/renderer";
import { createHash, randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { COMPOSITION_ID } from "./compositionId";
import { finalizeVideo } from "./pixelFormat";
import type { InputProps } from "./props";
import { webpackOverride } from "./webpackOverride";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const OUT_DIR = path.join(root, "out");

let bundlePromise: Promise<string> | null = null;

export const BUNDLE_CACHE_DIR = path.join(root, ".bundle-cache");

function walk(dir: string): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true })
    .flatMap((e) => (e.isDirectory() ? walk(path.join(dir, e.name)) : [path.join(dir, e.name)]))
    .sort();
}

/** Hash of everything the bundle is built from: src/, public/ and the files that configure it. */
export function sourceHash(): string {
  const hash = createHash("sha1");
  const files = [...walk(path.join(root, "src")), ...walk(path.join(root, "public"))];
  for (const extra of ["package.json", "remotion.config.ts", "tsconfig.json"]) {
    files.push(path.join(root, extra));
  }
  for (const file of files) {
    hash.update(path.relative(root, file).replaceAll("\\", "/"));
    hash.update(readFileSync(file));
  }
  return hash.digest("hex").slice(0, 16);
}

/**
 * Bundles the Remotion project, or reuses the bundle built from identical sources: it is stored in
 * .bundle-cache/<hash> and rebuilt only when something in src/ or public/ changes. Within one process
 * the result is also memoized.
 */
export function getBundle(): Promise<string> {
  bundlePromise ??= (async () => {
    const outDir = path.join(BUNDLE_CACHE_DIR, sourceHash());
    if (existsSync(path.join(outDir, "index.html"))) {
      console.log(`[bundle] cache hit ${path.basename(outDir)}`);
      return outDir;
    }
    console.log(`[bundle] cache miss, bundling to ${path.basename(outDir)}`);
    rmSync(outDir, { recursive: true, force: true });
    await bundle({
      entryPoint: path.join(root, "src", "index.ts"),
      publicDir: path.join(root, "public"),
      outDir,
      webpackOverride,
      onProgress: (p) => {
        if (p % 25 === 0) console.log(`[bundle] ${p}%`);
      },
    });
    for (const old of readdirSync(BUNDLE_CACHE_DIR)) {
      if (old !== path.basename(outDir)) rmSync(path.join(BUNDLE_CACHE_DIR, old), { recursive: true, force: true });
    }
    return outDir;
  })().catch((e) => {
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

  onStage("pixel_format");
  const pixelFormat = finalizeVideo(file);
  console.log(`[render] pixel format: ${pixelFormat ?? "unknown (ffprobe not found)"}`);

  return {
    file,
    durationMs: Math.round((composition.durationInFrames / composition.fps) * 1000),
    renderMs: Date.now() - started,
  };
}
