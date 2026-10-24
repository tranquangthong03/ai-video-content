"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type JobDetail } from "./api";

export const POLL_MS = 1500;

/** Polls a job while it runs or is queued; stops on waiting / done / failed / cancelled. */
export function shouldPoll(status: string | undefined): boolean {
  return status === undefined || status === "running" || status === "queued";
}

export function useJob(id: string) {
  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const alive = useRef(true);
  const answered = useRef<string | null>(null);

  const load = useCallback(async () => {
    try {
      const next = await api.getJob(id);
      if (!alive.current) return;
      setJob(next);
      setError(null);
      // the server may still show the question we just answered for a moment: keep polling then
      const stale = next.state.status === "waiting" && next.pending?.interaction_id === answered.current;
      if (shouldPoll(next.state.status) || stale) timer.current = setTimeout(load, POLL_MS);
    } catch (e) {
      if (!alive.current) return;
      setError(e instanceof ApiError ? e.message : "Có lỗi không mong đợi");
      timer.current = setTimeout(load, POLL_MS * 2);
    }
  }, [id]);

  /** Call after any action: fetch now and restart polling if the job runs again. */
  const refresh = useCallback(async () => {
    if (timer.current) clearTimeout(timer.current);
    await load();
  }, [load]);

  useEffect(() => {
    alive.current = true;
    void load();
    return () => {
      alive.current = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [load]);

  const markAnswered = useCallback((interactionId: string) => {
    answered.current = interactionId;
  }, []);

  return { job, error, refresh, setJob, markAnswered };
}
