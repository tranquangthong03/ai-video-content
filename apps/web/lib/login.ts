/** Pure helpers of the login_required card (tested in login.test.ts). */

export type LoginTab = "window" | "credentials" | "upload";

export const LOGIN_TABS: { id: LoginTab; label: string; method: string }[] = [
  { id: "window", label: "Mở cửa sổ đăng nhập", method: "browser_window" },
  { id: "credentials", label: "Tài khoản demo", method: "credentials" },
  { id: "upload", label: "Tải file phiên đăng nhập", method: "upload_state" },
];

/** The tabs the pipeline offers, in the order of the card (the window first: it is recommended). */
export function tabsFor(methods: string[]) {
  return LOGIN_TABS.filter((t) => methods.includes(t.method));
}

/** auth.json from `playwright codegen --save-storage`: a JSON object (cookies / origins). */
export function looksLikeAuthJson(text: string): boolean {
  try {
    const data: unknown = JSON.parse(text);
    return typeof data === "object" && data !== null && !Array.isArray(data);
  } catch {
    return false;
  }
}

/** The address the user typed, with https:// when the scheme is missing; null when it cannot be one. */
export function normalizeLoginUrl(text: string): string | null {
  const t = text.trim();
  if (!t || /\s/.test(t)) return null;
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(t) ? t : `https://${t}`;
  try {
    const u = new URL(withScheme);
    return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : null;
  } catch {
    return null;
  }
}

export const LOGIN_REASONS: Record<string, string> = {
  redirect: "Trang này yêu cầu đăng nhập.",
  password_field: "Trang này yêu cầu đăng nhập.",
  http_status: "Trang này trả về lỗi 401/403 (cần đăng nhập).",
  session_expired: "Phiên đăng nhập đã hết hạn.",
  requested: "Bạn đã báo tính năng chính nằm sau đăng nhập.",
};

/** The failure line to show, with the way-A hint when another way is more likely to work. */
export function failureText(failure: string | null | undefined): string | null {
  return failure && failure.trim() ? failure.trim() : null;
}
