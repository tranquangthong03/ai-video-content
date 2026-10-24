import { spawnSync } from "node:child_process";
import { renameSync, rmSync } from "node:fs";

/** Pixel format reported by ffprobe for the first video stream, or null when ffprobe is unavailable. */
export function probePixelFormat(file: string): string | null {
  const r = spawnSync(
    "ffprobe",
    ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=pix_fmt", "-of", "default=nw=1:nk=1", file],
    { encoding: "utf8" },
  );
  return r.status === 0 ? r.stdout.trim() : null;
}

/**
 * Remotion's h264 output can be tagged yuvj420p (full range), which some players and platforms reject.
 * When ffprobe reports anything but yuv420p, re-encode to limited-range yuv420p, keeping audio as is.
 * Returns the pixel format after the call; a missing ffmpeg/ffprobe is reported but not fatal.
 */
export function ensureYuv420p(file: string): string | null {
  const before = probePixelFormat(file);
  if (before === null || before === "yuv420p") return before;
  const tmp = `${file}.tv.mp4`;
  const r = spawnSync(
    "ffmpeg",
    [
      "-y", "-v", "error", "-i", file,
      "-vf", "scale=out_range=tv", "-pix_fmt", "yuv420p", "-color_range", "tv",
      "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "copy",
      "-movflags", "+faststart", tmp,
    ],
    { encoding: "utf8" },
  );
  if (r.status !== 0) {
    rmSync(tmp, { force: true });
    console.warn(`[render] pixel format is ${before} and the ffmpeg fix failed: ${r.stderr?.slice(0, 200)}`);
    return before;
  }
  renameSync(tmp, file);
  return probePixelFormat(file);
}
