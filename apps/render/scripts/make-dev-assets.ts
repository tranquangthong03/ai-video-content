// Generates fake mobile screenshots (sharp + SVG) and a 6s test clip (ffmpeg) into public/dev-assets.
import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const W = 780;
const H = 1688;
const out = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../public/dev-assets");
mkdirSync(out, { recursive: true });

const FONT = "font-family=\"Arial, Helvetica, sans-serif\"";
const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");

const header = (title: string) => `
  <rect width="${W}" height="${H}" fill="#f4f5fb"/>
  <rect width="${W}" height="190" fill="#4F46E5"/>
  <text x="48" y="130" ${FONT} font-size="54" font-weight="700" fill="#fff">${esc(title)}</text>`;

const card = (y: number, h: number, title: string, sub: string, color: string) => `
  <rect x="40" y="${y}" width="${W - 80}" height="${h}" rx="28" fill="#fff"/>
  <rect x="40" y="${y}" width="14" height="${h}" rx="7" fill="${color}"/>
  <text x="84" y="${y + 62}" ${FONT} font-size="38" font-weight="700" fill="#1f2937">${esc(title)}</text>
  <text x="84" y="${y + 112}" ${FONT} font-size="30" fill="#6b7280">${esc(sub)}</text>`;

const tabBar = `
  <rect y="${H - 150}" width="${W}" height="150" fill="#fff"/>
  ${[0, 1, 2, 3].map((i) => `<circle cx="${110 + i * 187}" cy="${H - 85}" r="26" fill="${i === 1 ? "#4F46E5" : "#d1d5db"}"/>`).join("")}`;

const screens: Record<string, string> = {
  "screen-1": `${header("Tổng quan")}
    ${card(250, 190, "12 công việc hôm nay", "4 sắp đến hạn", "#4F46E5")}
    ${card(480, 190, "Dự án Website", "Hoàn thành 68%", "#10b981")}
    ${card(710, 190, "Họp nhóm 14:00", "Phòng họp tầng 3", "#F59E0B")}
    ${card(940, 190, "Báo cáo tuần", "Quá hạn 1 ngày", "#ef4444")}
    ${card(1170, 190, "Thiết kế logo", "Đang thực hiện", "#6366f1")}${tabBar}`,
  "screen-2": `${header("Bảng Kanban")}
    ${["Cần làm", "Đang làm", "Xong"].map((c, i) => `<rect x="${30 + i * 245}" y="230" width="230" height="1200" rx="22" fill="#e5e7eb"/><text x="${50 + i * 245}" y="290" ${FONT} font-size="32" font-weight="700" fill="#374151">${c}</text>`).join("")}
    ${[0, 1, 2, 3].map((k) => `<rect x="42" y="${330 + k * 190}" width="206" height="160" rx="18" fill="#fff"/>`).join("")}
    ${[0, 1].map((k) => `<rect x="287" y="${330 + k * 190}" width="206" height="160" rx="18" fill="#fff"/>`).join("")}
    ${[0, 1, 2].map((k) => `<rect x="532" y="${330 + k * 190}" width="206" height="160" rx="18" fill="#d1fae5"/>`).join("")}${tabBar}`,
  "screen-3": `${header("Nhắc việc")}
    ${card(250, 180, "Nộp báo cáo • 09:00", "Nhắc trước 30 phút", "#ef4444")}
    ${card(460, 180, "Gọi khách hàng • 11:30", "Nhắc trước 10 phút", "#F59E0B")}
    ${card(670, 180, "Review code • 15:00", "Nhắc trước 15 phút", "#4F46E5")}
    ${card(880, 180, "Gửi hóa đơn • 17:00", "Nhắc trước 1 giờ", "#10b981")}${tabBar}`,
  "screen-4": `${header("Cài đặt")}
    ${card(250, 150, "Thông báo", "Bật", "#4F46E5")}
    ${card(430, 150, "Giao diện", "Sáng", "#6366f1")}
    ${card(610, 150, "Đồng bộ", "Mỗi 5 phút", "#10b981")}
    ${card(790, 150, "Tài khoản", "demo@taskflow.app", "#F59E0B")}${tabBar}`,
};

for (const [name, body] of Object.entries(screens)) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${body}</svg>`;
  await sharp(Buffer.from(svg)).png().toFile(path.join(out, `${name}.png`));
  console.log("wrote", `${name}.png`);
}

const clip = path.join(out, "clip.mp4");
const ff = spawnSync(
  "ffmpeg",
  ["-y", "-f", "lavfi", "-i", `testsrc2=size=${W}x${H}:rate=30:duration=6`, "-pix_fmt", "yuv420p", "-c:v", "libx264", clip],
  { stdio: "inherit" },
);
if (ff.status !== 0) throw new Error("ffmpeg failed (is ffmpeg installed and on PATH?)");
console.log("wrote clip.mp4");
