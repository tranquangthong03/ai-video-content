"use client";

import { useState } from "react";
import { ZodError } from "zod";
import { api, ApiError, type JobDetail } from "@/lib/api";
import type { UserResponse } from "@/lib/generated";

export interface JobCtx {
  job: JobDetail;
  /** Reload the job now (and keep polling while it runs). */
  refresh: () => Promise<void>;
  markAnswered: (interactionId: string) => void;
}

/** Sends a validated UserResponse for the pending question; tracks busy and error state. */
export function useSend(ctx: JobCtx) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send(make: () => UserResponse) {
    setError(null);
    setBusy(true);
    try {
      const response = make();
      await api.respond(response.job_id, response);
      ctx.markAnswered(response.interaction_id);
      await ctx.refresh();
    } catch (e) {
      if (e instanceof ZodError) setError("Dữ liệu chưa hợp lệ: " + e.issues.map((i) => i.message).join("; "));
      else setError(e instanceof ApiError ? e.message : "Không gửi được phản hồi");
      await ctx.refresh().catch(() => undefined);
    } finally {
      setBusy(false);
    }
  }
  return { send, busy, error };
}

export function ErrorNote({ text }: { text: string | null }) {
  if (!text) return null;
  return (
    <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">
      {text}
    </p>
  );
}

/** Notice lines the pipeline puts before its standard message (rejected edits, warnings). */
export function Notices({ message }: { message: string }) {
  const lines = message.split("\n").filter((l) => l.trim());
  const notices = lines.slice(0, -1);
  if (notices.length === 0) return null;
  return (
    <ul className="space-y-1">
      {notices.map((n, i) => (
        <li
          key={i}
          className={
            n.startsWith("Bị từ chối") || n.startsWith("Không áp dụng")
              ? "rounded-md bg-red-50 px-3 py-2 text-sm text-red-800"
              : "rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900"
          }
        >
          {n}
        </li>
      ))}
    </ul>
  );
}

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}
