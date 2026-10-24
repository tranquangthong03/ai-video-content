"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { CheckCircle2, Circle, Download, Loader2 } from "lucide-react";
import { api, absoluteUrl, ApiError, fileUrl, type HistoryItem, type JobDetail } from "@/lib/api";
import { KIND_TITLE, SHOT_LABEL, STATUS_LABEL, seconds } from "@/lib/labels";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { ErrorNote, Section, type JobCtx } from "./shared";

/** Which step of the left-hand list is current: the pending question wins over state.step. */
export function currentStep(job: JobDetail): string {
  const kind = job.pending?.kind;
  if (job.state.status === "done") return "done";
  if (kind === "confirm_understanding") return "confirm";
  if (kind === "choose_concept") return "concept";
  if (kind === "outline_review" || kind === "clarify") return "outline";
  if (kind === "script_review") return "script";
  return job.state.step;
}

export function summarize(h: HistoryItem): string {
  if (h.kind === "choose_concept") {
    const a = h.answers ?? {};
    return h.action === "regenerate" ? "Đề xuất lại" : `Hướng «${String(a.concept_id ?? "")}»${a.notes ? ` · ${String(a.notes)}` : ""}`;
  }
  if (h.instruction) return `Sửa: ${h.instruction}`;
  const verbs: Record<string, string> = { approve: "Đã duyệt", answer: "Đã xác nhận", regenerate: "Tạo lại", revert: "Quay về bản cũ", edit: "Đã sửa" };
  return verbs[h.action] ?? h.action;
}

export function Sidebar({ job }: { job: JobDetail }) {
  const current = currentStep(job);
  const index = job.steps.findIndex((s) => s.id === current);
  const failed = job.state.status === "failed" || job.state.status === "cancelled";
  return (
    <aside className="space-y-6">
      <ol className="space-y-2" aria-label="Các bước">
        {job.steps.map((s, i) => {
          const done = i < index || job.state.status === "done";
          const active = i === index && !done;
          return (
            <li key={s.id} className={`flex items-center gap-2 text-sm ${active ? "font-semibold" : done ? "" : "text-muted-foreground"}`}>
              {done ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-600" />
              ) : active && job.state.status === "running" ? (
                <Loader2 className="h-4 w-4 animate-spin text-primary" />
              ) : (
                <Circle className={`h-4 w-4 ${active ? (failed ? "text-destructive" : "text-primary") : ""}`} />
              )}
              {s.label}
            </li>
          );
        })}
      </ol>
      {job.history.length > 0 && (
        <Section title="Bạn đã chọn">
          <ul className="space-y-2">
            {job.history.map((h, i) => (
              <li key={i} className="text-xs">
                <span className="font-medium">{KIND_TITLE[h.kind] ?? h.kind}</span>
                <br />
                <span className="text-muted-foreground">{summarize(h)}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </aside>
  );
}

/** Running / queued: progress text and bar, the latest page screenshot (refreshed as it changes). */
export function RunningPanel({ job }: { job: JobDetail }) {
  const s = job.state;
  const queued = s.status === "queued";
  const shot = s.latest_screenshot ? `${fileUrl(s.job_id, s.latest_screenshot)}?v=${encodeURIComponent(s.updated_at)}` : null;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
        <h2 className="text-lg font-semibold">{queued ? "Đang xếp hàng" : s.progress_text || "Đang xử lý..."}</h2>
      </div>
      {queued ? (
        <p className="text-sm text-muted-foreground">
          {job.queue_position ? `Bạn ở vị trí ${job.queue_position} trong hàng chờ.` : "Sắp đến lượt."} Mỗi lần chỉ chạy một công việc, trang sẽ tự cập nhật.
        </p>
      ) : (
        <>
          <Progress value={s.progress_pct} />
          <p className="text-xs text-muted-foreground">{s.progress_pct}%</p>
        </>
      )}
      {shot && (
        <Card className="overflow-hidden">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={shot} alt="Trang vừa phân tích" className="max-h-[420px] w-full object-contain object-top" />
        </Card>
      )}
    </div>
  );
}

export function FailedPanel({ ctx }: { ctx: JobCtx }) {
  const router = useRouter();
  const { job } = ctx;
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const cancelled = job.state.status === "cancelled";

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Có lỗi không mong đợi");
    }
    setBusy(false);
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">{cancelled ? "Công việc đã hủy" : "Công việc gặp lỗi"}</h2>
      {job.state.error && <ErrorNote text={job.state.error} />}
      <p className="text-sm text-muted-foreground">
        Những gì đã làm xong được giữ lại. Bấm “Chạy tiếp” để làm tiếp từ chỗ dừng, hoặc tạo lại từ đầu.
      </p>
      <ErrorNote text={error} />
      <div className="flex flex-wrap gap-2">
        <Button disabled={busy || !job.can_resume} onClick={() => run(async () => { await api.resume(job.state.job_id); await ctx.refresh(); })}>
          Chạy tiếp
        </Button>
        <Button variant="outline" disabled={busy} onClick={() => run(async () => { const n = await api.createJob(job.state.url); router.push(`/jobs/${n.state.job_id}`); })}>
          Tạo lại
        </Button>
      </div>
    </div>
  );
}

export function VideoPanel({ ctx }: { ctx: JobCtx }) {
  const { job } = ctx;
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const report = job.report;
  const src = job.video_url ? absoluteUrl(job.video_url) : null;

  useEffect(() => setError(null), [job.state.updated_at]);

  async function redo() {
    setBusy(true);
    try {
      await api.resume(job.state.job_id, true);
      await ctx.refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Có lỗi không mong đợi");
    }
    setBusy(false);
  }

  return (
    <div className="grid gap-6 md:grid-cols-[280px_1fr]">
      <div className="space-y-3">
        {src && (
          <video src={src} controls playsInline className="aspect-[9/16] w-full max-w-[280px] rounded-lg bg-black" />
        )}
        {src && (
          <Button asChild className="w-full max-w-[280px]">
            <a href={`${src}?download=1`} download="video.mp4">
              <Download className="h-4 w-4" /> Tải MP4
            </a>
          </Button>
        )}
      </div>
      <div className="space-y-4">
        <h2 className="text-xl font-bold">{report?.headline ?? "Video đã sẵn sàng"}</h2>
        {report && (
          <>
            <div className="flex flex-wrap gap-2 text-sm">
              <Badge tone="muted">Mục tiêu {seconds(report.target_ms)}</Badge>
              <Badge tone="muted">Thực tế {seconds(report.actual_ms)}</Badge>
              {report.footage_ratio !== null && <Badge tone="success">Cảnh quay thật {Math.round(report.footage_ratio * 100)}%</Badge>}
            </div>
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-left text-sm">
                <thead className="bg-muted text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2">Cảnh</th>
                    <th className="px-3 py-2">Loại</th>
                    <th className="px-3 py-2">Cảnh quay</th>
                    <th className="px-3 py-2">Thời lượng</th>
                    <th className="px-3 py-2">Cảnh báo</th>
                  </tr>
                </thead>
                <tbody>
                  {report.scenes.map((s) => (
                    <tr key={s.id} className="border-t border-border">
                      <td className="px-3 py-2">{s.id}</td>
                      <td className="px-3 py-2">{s.type}</td>
                      <td className="px-3 py-2">{SHOT_LABEL[s.kind] ?? s.kind}</td>
                      <td className="px-3 py-2">{seconds(s.final_ms)}</td>
                      <td className="px-3 py-2 text-xs text-amber-800">{s.warnings.length ? `${s.warnings.length} cảnh báo` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {report.warnings.length > 0 && (
              <details className="text-xs text-muted-foreground">
                <summary className="cursor-pointer">Chi tiết cảnh báo ({report.warnings.length})</summary>
                <ul className="mt-2 list-disc space-y-1 pl-5">
                  {report.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </details>
            )}
          </>
        )}
        <ErrorNote text={error} />
        <Button variant="outline" disabled={busy} onClick={redo}>
          Sửa kịch bản và làm lại
        </Button>
      </div>
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const tone = status === "done" ? "success" : status === "failed" ? "danger" : status === "waiting" ? "warning" : "muted";
  return <Badge tone={tone}>{STATUS_LABEL[status] ?? status}</Badge>;
}
