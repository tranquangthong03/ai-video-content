export const DEMO_KIND_LABEL: Record<string, string> = {
  interaction: "Thao tác",
  navigation: "Chuyển trang",
  showcase: "Giới thiệu",
  failed: "Chưa kiểm chứng",
};

export function demoKindLabel(kind: string | null | undefined): string {
  return kind ? (DEMO_KIND_LABEL[kind] ?? kind) : "Chưa kiểm chứng";
}

export function demoKindTone(kind: string | null | undefined): "success" | "default" | "warning" | "muted" {
  if (kind === "interaction") return "success";
  if (kind === "navigation" || kind === "showcase") return "default";
  return "warning";
}

export const STATUS_LABEL: Record<string, string> = {
  queued: "Đang xếp hàng",
  running: "Đang chạy",
  waiting: "Chờ bạn",
  done: "Hoàn tất",
  failed: "Lỗi",
  cancelled: "Đã hủy",
};

export const KIND_TITLE: Record<string, string> = {
  confirm_understanding: "Xác nhận hiểu biết về sản phẩm",
  login_required: "Cần đăng nhập",
  select_features: "Chọn tính năng để review",
  select_flow: "Chọn luồng chính để quay",
  flow_storyboard_review: "Duyệt storyboard luồng",
  marketing_brief: "Bổ sung brief cho video",
  choose_concept: "Chọn hướng video",
  outline_review: "Duyệt dàn ý",
  script_review: "Duyệt kịch bản",
  clarify: "Cần làm rõ một chút",
};

export const SHOT_LABEL: Record<string, string> = {
  "thao tác": "Quay thao tác",
  "cuộn-highlight": "Cuộn và tô sáng",
  "chỉ vị trí": "Chỉ vị trí",
  ảnh: "Ảnh trang",
  chữ: "Chỉ có chữ",
};

export function seconds(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

/** Splits text around the first occurrence of `highlight` (for the coloured part of a headline). */
export function splitHighlight(text: string, highlight: string | null): [string, string, string] {
  if (!highlight) return [text, "", ""];
  const i = text.indexOf(highlight);
  if (i < 0) return [text, "", ""];
  return [text.slice(0, i), highlight, text.slice(i + highlight.length)];
}

export function timeAgo(iso: string, now: number = Date.now()): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return "vừa xong";
  if (s < 3600) return `${Math.floor(s / 60)} phút trước`;
  if (s < 86400) return `${Math.floor(s / 3600)} giờ trước`;
  return `${Math.floor(s / 86400)} ngày trước`;
}
