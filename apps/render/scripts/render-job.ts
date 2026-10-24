// Renders one job: node render-job.ts <props.json> <out.mp4>
// props.json is InputProps whose asset urls may be absolute local file paths; they are served from a
// throwaway static http server on 127.0.0.1 so no object storage is needed. Prints one JSON line.
import { createReadStream, existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import { InputPropsSchema } from "../src/props";
import { renderVideo } from "../src/renderer";

const [propsFile, outFile] = process.argv.slice(2);
if (!propsFile || !outFile) {
  console.error("usage: render-job.ts <props.json> <out.mp4>");
  process.exit(2);
}

const raw = JSON.parse(readFileSync(propsFile, "utf8"));
const isLocal = (u: unknown): u is string =>
  typeof u === "string" && !/^(https?:|data:|blob:)/.test(u) && path.isAbsolute(u) && existsSync(u);

const served = new Map<string, string>(); // url path -> file
const server = createServer((req, res) => {
  const file = served.get(decodeURIComponent((req.url ?? "").split("?")[0]));
  if (!file) {
    res.writeHead(404).end();
    return;
  }
  const size = statSync(file).size;
  const type = file.endsWith(".mp4") ? "video/mp4" : file.endsWith(".png") ? "image/png" : "application/octet-stream";
  const range = req.headers.range;
  if (range) {
    const [s, e] = range.replace("bytes=", "").split("-");
    const start = Number(s);
    const end = e ? Number(e) : size - 1;
    res.writeHead(206, {
      "Content-Type": type,
      "Content-Range": `bytes ${start}-${end}/${size}`,
      "Accept-Ranges": "bytes",
      "Content-Length": end - start + 1,
    });
    createReadStream(file, { start, end }).pipe(res);
  } else {
    res.writeHead(200, { "Content-Type": type, "Content-Length": size, "Accept-Ranges": "bytes" });
    createReadStream(file).pipe(res);
  }
});
await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${(server.address() as { port: number }).port}`;

let n = 0;
const publish = (file: string) => {
  const key = `/f${n++}/${path.basename(file)}`;
  served.set(key, file);
  return base + encodeURI(key);
};
for (const assets of Object.values<Record<string, unknown>>(raw.assets ?? {})) {
  for (const k of ["clip_url", "screenshot_url", "audio_url"]) {
    if (isLocal(assets[k])) assets[k] = publish(assets[k] as string);
  }
}
if (isLocal(raw.music_url)) raw.music_url = publish(raw.music_url);

const props = InputPropsSchema.parse(raw);
try {
  const result = await renderVideo(props, path.resolve(outFile), { logLevel: "warn" });
  const line = JSON.stringify({ ok: true, file: result.file, duration_ms: result.durationMs, render_ms: result.renderMs });
  writeFileSync(`${outFile}.json`, line);
  console.log(`RESULT ${line}`);
} finally {
  server.close();
}
