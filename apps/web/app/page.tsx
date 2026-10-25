"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronDown } from "lucide-react";
import { api, ApiError, type JobState } from "@/lib/api";
import { SAMPLE_URLS } from "@/lib/sample-urls";
import { STATUS_LABEL, timeAgo } from "@/lib/labels";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/field";

type Row = JobState & { queue_position: number | null };

const TONE: Record<string, "success" | "warning" | "danger" | "muted" | "default"> = {
  done: "success",
  waiting: "warning",
  failed: "danger",
  cancelled: "muted",
  running: "default",
  queued: "muted",
};

export default function Home() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [behindLogin, setBehindLogin] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<Row[]>([]);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .listJobs()
        .then((rows) => alive && setJobs(rows))
        .catch(() => undefined);
    void load();
    const t = setInterval(load, 3000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const job = await api.createJob(url.trim(), file, behindLogin);
      router.push(`/jobs/${job.state.job_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Không tạo được công việc");
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl space-y-8 px-4 py-10">
      <section className="space-y-4">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Tạo video giới thiệu từ một địa chỉ website</h1>
        <p className="text-muted-foreground">
          Dán địa chỉ website. Hệ thống sẽ khám phá, hỏi bạn vài câu, viết kịch bản, tự quay màn hình và xuất video MP4
          dọc cho TikTok / YouTube Shorts.
        </p>
        <form onSubmit={submit} className="space-y-3">
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input
              type="url"
              required
              placeholder="https://ten-mien-cua-ban.com"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              aria-label="Địa chỉ website"
            />
            <Button type="submit" disabled={busy || !url.trim()} className="sm:w-36">
              {busy ? "Đang tạo..." : "Tạo video"}
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted-foreground">Dùng URL mẫu:</span>
            {SAMPLE_URLS.map((s) => (
              <Button key={s.url} type="button" variant="outline" size="sm" onClick={() => setUrl(s.url)}>
                {s.label}
              </Button>
            ))}
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" checked={behindLogin} onChange={(e) => setBehindLogin(e.target.checked)} className="mt-0.5" />
            <span>
              Tính năng chính nằm sau đăng nhập
              <span className="block text-xs text-muted-foreground">
                Hoặc cứ nhập URL — hệ thống sẽ hỏi khi cần đăng nhập.
              </span>
            </span>
          </label>
          <details className="group rounded-lg border border-border bg-card p-3 text-sm">
            <summary className="flex cursor-pointer list-none items-center justify-between font-medium">
              Website cần đăng nhập?
              <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
            </summary>
            <div className="mt-3 space-y-2 text-muted-foreground">
              <p>
                Tạo file đăng nhập bằng lệnh sau, đăng nhập thủ công trong cửa sổ trình duyệt hiện ra, rồi đóng lại:
              </p>
              <code className="block overflow-x-auto rounded-md bg-muted px-3 py-2 text-xs text-foreground">
                uv run playwright codegen --save-storage=auth.json {url.trim() || "<url>"}
              </code>
              <label className="block">
                <span className="mb-1 block text-foreground">Tải file auth.json lên</span>
                <input
                  type="file"
                  accept="application/json,.json"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-accent file:px-3 file:py-1.5 file:text-accent-foreground"
                />
              </label>
              <p className="text-xs">Chỉ dùng tài khoản demo. File đăng nhập chỉ nằm trên máy chủ của job này.</p>
            </div>
          </details>
        </form>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Công việc gần đây</h2>
        {jobs.length === 0 ? (
          <p className="text-sm text-muted-foreground">Chưa có công việc nào.</p>
        ) : (
          <div className="space-y-2">
            {jobs.map((j) => (
              <a key={j.job_id} href={`/jobs/${j.job_id}`} className="block">
                <Card className="transition-colors hover:bg-muted/50">
                  <CardHeader className="flex-row items-center justify-between gap-3 pb-4">
                    <div className="min-w-0">
                      <CardTitle className="truncate text-sm">{j.url}</CardTitle>
                      <p className="text-xs text-muted-foreground">
                        {timeAgo(j.created_at)}
                        {j.status === "queued" && j.queue_position ? ` · vị trí hàng chờ ${j.queue_position}` : ""}
                      </p>
                    </div>
                    <Badge tone={TONE[j.status] ?? "muted"}>{STATUS_LABEL[j.status] ?? j.status}</Badge>
                  </CardHeader>
                  <CardContent className="hidden" />
                </Card>
              </a>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
