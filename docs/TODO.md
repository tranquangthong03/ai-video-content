# TODO

## Render (apps/render)

State: `pnpm --filter render render:sample` renders `out/sample_desktop.mp4` (desktop_showcase) and
`out/sample_phone.mp4` (phone_showcase), both 1080x1920, h264, yuv420p (limited range).
Earlier root cause of the failed render: Remotion's internal server defaulted to port 3000, which the `web`
container publishes; fixed by `freePort()` in `src/renderer.ts`.

- [x] **Pixel format**: Remotion's h264 output is still tagged `yuvj420p` even with `pixelFormat: "yuv420p"`.
  `src/pixelFormat.ts` (`ensureYuv420p`) probes the result and re-encodes with
  `-vf scale=out_range=tv -pix_fmt yuv420p -c:a copy` when needed; called at the end of `renderVideo()`.
  Needs `ffmpeg`/`ffprobe` on PATH (a missing binary is reported as a warning, not fatal).
- [x] **Bundle time (~126s)**: `getAvailableFonts()` pulled every Google font into the bundle. Replaced with a direct
  `@remotion/google-fonts/BeVietnamPro` import (subsets latin + vietnamese, weights 500/700/800), and the bundle is
  cached in `.bundle-cache/<hash of src/ + public/>` so it is rebuilt only when sources change.
  Measured: ~29s on the first ever bundle, ~3s for a rebuild with a warm webpack cache, 0s on a cache hit.
- [x] **Stills**: `pnpm --filter render stills` writes the desktop stills to `out/stills/desktop/` (checked by eye).
- [ ] Remotion warns that it expects `zod` 4.5.4 (we have 3.25.x). Non-blocking so far; revisit before using the `schema` prop.
- [ ] `server.ts` `/render` and the docker image were not re-verified after the Remotion work. The image also needs
  `ffmpeg` for the pixel-format fix, and a writable `.bundle-cache` directory.
- [ ] `OffthreadVideo` past the end of a clip (a scene that outlasts its clip by the 10-frame crossfade) was not
  exercised; the sample clip is longer than its scene. The producer should set a freeze-last-frame option.
- [ ] Karaoke/headline highlight use the theme `primary` as text color; a dark primary (e.g. #4F46E5 on #070B14)
  has low contrast. Consider lightening the color used for text only.
