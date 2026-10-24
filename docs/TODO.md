# TODO

## Render (apps/render) — deferred

State: `pnpm --filter render render:sample` produces `out/sample.mp4` (1080x1920, h264, 18.4s, ~171s total).
Root cause of the earlier failure: Remotion's internal server defaulted to port 3000, which the `web`
container publishes; fixed by `freePort()` in `src/renderer.ts`.

- [ ] **Pixel format**: `ffprobe` reports `yuvj420p` (full range) instead of `yuv420p`.
  Try `renderMedia({ pixelFormat: "yuv420p", colorSpace: "bt709" })`. If ffprobe still reports `yuvj420p`,
  add an ffmpeg post-process: `ffmpeg -i in.mp4 -vf "scale=out_range=tv" -pix_fmt yuv420p -c:a copy out.mp4`.
- [ ] **Bundle time (~126s)**: `getAvailableFonts()` pulls every Google font module into the bundle.
  Load only the needed weights/subsets (latin, vietnamese) from specific `@remotion/google-fonts/<Font>`
  imports, and cache the bundle between runs.
- [ ] **Stills**: run `pnpm --filter render stills` (script exists: `scripts/render-stills.ts`) and check the 4 PNGs in `out/stills/`.
- [ ] Remotion warns that it expects `zod` 4.5.4 (we have 3.25.x). Non-blocking so far; revisit before using the `schema` prop.
- [ ] `server.ts` `/render` and the docker image were not re-verified after the Remotion work.
