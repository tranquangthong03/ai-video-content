import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { InputPropsSchema } from "./props";
import { renderVideo } from "./renderer";
import { s3ConfigFromEnv, uploadVideo } from "./storage";

const app = express();
app.use(express.json({ limit: "10mb" }));

// Dev only: lets render-request.json point at http://localhost:<port>/dev-assets/...
if (process.env.NODE_ENV !== "production") {
  const publicDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "public");
  app.use("/dev-assets", express.static(path.join(publicDir, "dev-assets")));
}

app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

app.post("/render", async (req, res) => {
  const parsed = InputPropsSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(422).json({ error: "invalid_request", issues: parsed.error.issues });
    return;
  }

  try {
    console.log(`[render] start: ${parsed.data.script.title}`);
    const result = await renderVideo(parsed.data);
    const s3 = s3ConfigFromEnv();
    let videoKey = result.file;
    let url = result.file; // local path when no object storage is configured
    if (s3) {
      videoKey = `renders/${path.basename(result.file)}`;
      url = await uploadVideo(s3, result.file, videoKey);
    }
    console.log(`[render] done in ${result.renderMs}ms -> ${videoKey}`);
    res.json({ video_key: videoKey, url, duration_ms: result.durationMs, render_ms: result.renderMs });
  } catch (e) {
    console.error("[render] failed", e);
    res.status(500).json({ error: "render_failed", message: e instanceof Error ? e.message : String(e) });
  }
});

const port = Number(process.env.PORT ?? 3001);
app.listen(port, "0.0.0.0", () => {
  console.log(`render service listening on ${port}`);
});
