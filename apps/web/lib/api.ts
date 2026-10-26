import type { InteractionRequest, UserResponse } from "./generated";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type JobStatus = "queued" | "running" | "waiting" | "done" | "failed" | "cancelled";

export interface JobState {
  job_id: string;
  url: string;
  status: JobStatus;
  step: string;
  progress_text: string;
  progress_pct: number;
  latest_screenshot: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface SceneView {
  id: string;
  type: string;
  shot: string;
  feature: string | null;
  key_point: string | null;
  voiceover: string | null;
  on_screen_text: string | null;
  estimated_ms: number;
}

export interface ScriptExtra {
  version: number;
  versions: number[];
  title: string | null;
  headline: string | null;
  headline_highlight: string | null;
  badge: string | null;
  theme: { primary?: string; accent?: string } | null;
  target_duration_s: number;
  scenes: SceneView[];
  estimated_ms: number;
  footage_ratio: number | null;
  footage_min: number | null;
  recommended_duration_s: number | null;
  warnings: string[];
  critic?: CriticReport | null;
  hook_options?: HookOption[];
  hook_scene_id?: string | null;
  /** 1-based number of the hook option the hook scene shows. */
  chosen_hook?: number | null;
}

export interface HookOption {
  kind: string;
  voiceover: string;
  on_screen_text: string | null;
}

export interface CriticScore {
  score: number | null;
  reason: string;
}

export interface CriticView {
  scores: Record<string, CriticScore>;
  weak_scenes: { scene_id: string; problem: string; suggestion: string }[];
  issues: string[];
  summary: string;
}

export interface CriticReport {
  threshold: number;
  before?: CriticView;
  after?: CriticView | null;
  final?: CriticView;
  kept_rewrite?: boolean;
  rewritten?: string[];
  passed?: boolean;
  /** The user edited the script after it was scored: the bars are the last scored version. */
  edited?: boolean;
  error?: string;
}

export interface HistoryItem {
  kind: string;
  interaction_id: string;
  action: string;
  answers: Record<string, string | string[]> | null;
  instruction: string | null;
}

export interface ReportScene {
  id: string;
  type: string;
  kind: string;
  speech_ms: number;
  final_ms: number;
  idle_max_ms: number | null;
  warnings: string[];
}

export interface ReportSummary {
  headline: string | null;
  target_ms: number;
  estimated_ms: number;
  actual_ms: number;
  footage_ratio: number | null;
  idle_ok: boolean;
  warnings: string[];
  scenes: ReportScene[];
  features: { id: string; name: string }[];
}

export interface JobDetail {
  state: JobState;
  steps: { id: string; label: string }[];
  queue_position: number | null;
  pending: InteractionRequest | null;
  pending_extra: ScriptExtra | null;
  history: HistoryItem[];
  video_url: string | null;
  report: ReportSummary | null;
  can_resume: boolean;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ApiError(0, "Không kết nối được máy chủ. Hãy kiểm tra API đã chạy chưa.");
  }
  if (!res.ok) {
    let message = `Lỗi ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(res.status, message);
  }
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  createJob(url: string, storageState?: File | null, requiresLogin = false): Promise<JobDetail> {
    const form = new FormData();
    form.set("url", url);
    if (storageState) form.set("storage_state", storageState);
    if (requiresLogin) form.set("requires_login", "true");
    return request("/api/jobs", { method: "POST", body: form });
  },
  listJobs: () => request<(JobState & { queue_position: number | null })[]>("/api/jobs"),
  getJob: (id: string) => request<JobDetail>(`/api/jobs/${id}`),
  respond: (id: string, body: UserResponse) => request<{ ok: boolean }>(`/api/jobs/${id}/respond`, json(body)),
  /** Way A: opens a Chromium window on the computer that runs the API (local demo). */
  openLoginBrowser: (id: string, loginUrl?: string | null) =>
    request<{ status: string; login_url: string }>(`/api/jobs/${id}/login/browser`, json({ login_url: loginUrl ?? null })),
  loginBrowserStatus: (id: string) => request<{ status: string }>(`/api/jobs/${id}/login/browser`),
  /** Way B: the demo account is encrypted by the server; it is never sent back. */
  saveLoginCredentials: (id: string, username: string, password: string) =>
    request<{ status: string }>(`/api/jobs/${id}/login/credentials`, json({ username, password })),
  /** Way C: an auth.json made with playwright codegen. */
  uploadLoginState(id: string, file: File): Promise<{ status: string }> {
    const form = new FormData();
    form.set("storage_state", file);
    return request(`/api/jobs/${id}/login/state`, { method: "POST", body: form });
  },
  cancel: (id: string) => request<JobDetail>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  resume: (id: string, redoScript = false) =>
    request<JobDetail>(`/api/jobs/${id}/resume?redo_script=${redoScript}`, { method: "POST" }),
};

/** URL of a file inside a job dir (screenshots, thumbnails, the video). */
export function fileUrl(jobId: string, relative: string): string {
  return `${API_URL}/api/jobs/${jobId}/files/${relative.replace(/^\/+/, "")}`;
}

export function absoluteUrl(path: string): string {
  return path.startsWith("http") ? path : `${API_URL}${path}`;
}
