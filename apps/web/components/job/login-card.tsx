"use client";

import { useEffect, useRef, useState } from "react";
import { AppWindow, KeyRound, Upload } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { InteractionRequest } from "@/lib/generated";
import { LOGIN_REASONS, failureText, looksLikeAuthJson, normalizeLoginUrl, tabsFor, type LoginTab } from "@/lib/login";
import { buildResponse, loginCredentialsFields, loginDoneFields, loginUrlFields } from "@/lib/responses";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/field";
import { ErrorNote, Section, useSend, type JobCtx } from "./shared";

type Pending = InteractionRequest;

const ICONS: Record<LoginTab, React.ReactNode> = {
  window: <AppWindow className="h-4 w-4" />,
  credentials: <KeyRound className="h-4 w-4" />,
  upload: <Upload className="h-4 w-4" />,
};

/** login_required: three ways to sign in - a window on this computer, a demo account, an auth.json. */
export function LoginCard({ ctx, pending }: { ctx: JobCtx; pending: Pending }) {
  const login = pending.login!;
  const jobId = ctx.job.state.job_id;
  const tabs = tabsFor(login.methods);
  const { send, busy, error } = useSend(ctx);
  const [tab, setTab] = useState<LoginTab>(tabs[0]?.id ?? "window");
  const [typedUrl, setTypedUrl] = useState("");
  const [windowOpen, setWindowOpen] = useState(false);
  const [opening, setOpening] = useState(false);
  const [local, setLocal] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [uploaded, setUploaded] = useState<string | null>(null);
  const loginUrl = login.login_url ?? null;
  const failure = failureText(login.failure);
  const polling = useRef<ReturnType<typeof setInterval> | null>(null);

  // while the window is open, notice when the server closed it (10 minutes without an answer)
  useEffect(() => {
    if (!windowOpen) return;
    polling.current = setInterval(() => {
      api
        .loginBrowserStatus(jobId)
        .then((s) => {
          if (s.status !== "browser_open") {
            setWindowOpen(false);
            if (s.status === "timeout") setLocal("Cửa sổ đăng nhập đã đóng vì quá 10 phút. Hãy mở lại.");
          }
        })
        .catch(() => undefined);
    }, 3000);
    return () => {
      if (polling.current) clearInterval(polling.current);
    };
  }, [windowOpen, jobId]);

  async function openWindow() {
    setLocal(null);
    setOpening(true);
    try {
      await api.openLoginBrowser(jobId, loginUrl ?? normalizeLoginUrl(typedUrl));
      setWindowOpen(true);
    } catch (e) {
      setLocal(e instanceof ApiError ? e.message : "Không mở được cửa sổ đăng nhập");
    } finally {
      setOpening(false);
    }
  }

  async function submitCredentials() {
    setLocal(null);
    try {
      await api.saveLoginCredentials(jobId, username, password);
    } catch (e) {
      setLocal(e instanceof ApiError ? e.message : "Không gửi được tài khoản");
      return;
    }
    setPassword(""); // the browser keeps nothing: the server has it, encrypted
    await send(() => buildResponse(pending, "answer", loginCredentialsFields(loginUrl ?? normalizeLoginUrl(typedUrl))));
  }

  async function upload(file: File | undefined) {
    setLocal(null);
    setUploaded(null);
    if (!file) return;
    const text = await file.text();
    if (!looksLikeAuthJson(text)) {
      setLocal("File đăng nhập phải là JSON (auth.json) hợp lệ.");
      return;
    }
    try {
      await api.uploadLoginState(jobId, file);
      setUploaded(file.name);
    } catch (e) {
      setLocal(e instanceof ApiError ? e.message : "Không tải được file");
    }
  }

  const needsUrl = login.can_enter_url && !loginUrl;
  const typed = normalizeLoginUrl(typedUrl);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-bold">Cần đăng nhập</h2>
        <p className="text-sm text-muted-foreground">{LOGIN_REASONS[login.reason] ?? pending.message}</p>
        {loginUrl && <p className="mt-1 truncate text-xs text-muted-foreground">Trang đăng nhập: {loginUrl}</p>}
      </div>

      {needsUrl && (
        <Section title="Địa chỉ trang đăng nhập">
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input value={typedUrl} onChange={(e) => setTypedUrl(e.target.value)} placeholder="https://app.example.com/login" aria-label="Địa chỉ trang đăng nhập" />
            <Button
              variant="outline"
              disabled={busy || !typed}
              onClick={() => send(() => buildResponse(pending, "answer", loginUrlFields(typed!)))}
            >
              Dùng địa chỉ này
            </Button>
          </div>
        </Section>
      )}

      {(failure || local) && (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">
          {local ?? failure}
        </p>
      )}

      <div role="tablist" className="flex flex-wrap gap-2">
        {tabs.map((t) => (
          <Button key={t.id} role="tab" aria-selected={tab === t.id} variant={tab === t.id ? "default" : "outline"} size="sm" onClick={() => setTab(t.id)}>
            <span className="mr-1.5">{ICONS[t.id]}</span>
            {t.label}
            {t.id === "window" && <span className="ml-1.5 text-[10px] opacity-80">(khuyến nghị)</span>}
          </Button>
        ))}
      </div>

      {tab === "window" && (
        <Section title="Đăng nhập trong cửa sổ trình duyệt">
          <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
            <li>Bấm «Mở cửa sổ đăng nhập»: một cửa sổ Chromium hiện ra trên máy chạy hệ thống.</li>
            <li>Đăng nhập như bình thường (kể cả mã 2FA hoặc «Đăng nhập với Google»).</li>
            <li>Quay lại đây và bấm «Tôi đã đăng nhập xong».</li>
          </ol>
          <p className="text-xs text-muted-foreground">Chỉ dùng được khi hệ thống chạy cùng máy với bạn (bản demo local).</p>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" disabled={opening || (needsUrl && !typed)} onClick={openWindow}>
              {opening ? "Đang mở..." : windowOpen ? "Mở lại cửa sổ" : "Mở cửa sổ đăng nhập"}
            </Button>
            <Button disabled={busy || !windowOpen} onClick={() => send(() => buildResponse(pending, "login_done", loginDoneFields()))}>
              {busy ? "Đang kiểm tra..." : "Tôi đã đăng nhập xong"}
            </Button>
          </div>
          <p className="text-sm" aria-live="polite">
            {busy ? "Đang kiểm tra phiên đăng nhập..." : windowOpen ? "Cửa sổ đăng nhập đang mở." : ""}
          </p>
        </Section>
      )}

      {tab === "credentials" && (
        <Section title="Đăng nhập bằng tài khoản demo">
          <p className="text-sm text-muted-foreground">
            Chỉ dùng tài khoản demo, không dùng tài khoản thật có dữ liệu quan trọng. Thông tin được mã hóa trên máy chủ và xóa ngay khi công việc kết thúc.
          </p>
          <label className="block space-y-1 text-sm">
            <span>Email / tên đăng nhập</span>
            <Input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
          </label>
          <label className="block space-y-1 text-sm">
            <span>Mật khẩu</span>
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
          </label>
          <Button disabled={busy || !username.trim() || !password || (needsUrl && !typed)} onClick={submitCredentials}>
            {busy ? "Đang đăng nhập..." : "Đăng nhập"}
          </Button>
        </Section>
      )}

      {tab === "upload" && (
        <Section title="Tải file phiên đăng nhập (auth.json)">
          <p className="text-sm text-muted-foreground">Tạo file bằng lệnh sau, đăng nhập thủ công trong cửa sổ hiện ra rồi đóng lại:</p>
          <code className="block overflow-x-auto rounded-md bg-muted px-3 py-2 text-xs text-foreground">
            uv run playwright codegen --save-storage=auth.json {loginUrl ?? "<url đăng nhập>"}
          </code>
          <input
            type="file"
            accept="application/json,.json"
            aria-label="Tải file auth.json"
            onChange={(e) => void upload(e.target.files?.[0])}
            className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-accent file:px-3 file:py-1.5 file:text-accent-foreground"
          />
          {uploaded && <p className="text-sm text-green-700">Đã tải lên {uploaded}.</p>}
          <Button disabled={busy || !uploaded} onClick={() => send(() => buildResponse(pending, "login_done", loginDoneFields()))}>
            {busy ? "Đang kiểm tra..." : "Dùng file này"}
          </Button>
        </Section>
      )}

      <ErrorNote text={error} />
      {login.hint && <p className="text-xs text-muted-foreground">{login.hint}</p>}
    </div>
  );
}
