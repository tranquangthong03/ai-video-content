// Generates the desktop dev assets into public/dev-assets: a fake 1920x1080 web app (4 UI states as
// PNG) and an 8s clip made of those states. Click times match DESKTOP_CLICK_LOG in src/dev/sampleProps.ts.
import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";
import { DESKTOP_CLICK_LOG } from "../src/dev/sampleProps";

const W = 1920;
const H = 1080;
const out = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../public/dev-assets");
mkdirSync(out, { recursive: true });

const FONT = 'font-family="Arial, Helvetica, sans-serif"';
const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");

type State = { tab: number; extraRow: boolean; filter: boolean };

function screen({ tab, extraRow, filter }: State): string {
  const tabs = ["Tất cả", "Đang làm", "Hoàn thành"];
  const rows = [
    ["Thiết kế trang chủ", "Đang làm", "#F59E0B"],
    ["Viết nội dung blog", "Hoàn thành", "#10b981"],
    ["Họp nhóm sản phẩm", "Đang làm", "#F59E0B"],
    ["Gửi báo cáo tuần", "Hoàn thành", "#10b981"],
    ["Cập nhật tài liệu", "Đang làm", "#F59E0B"],
  ];
  if (extraRow) rows.unshift(["Việc mới vừa thêm", "Đang làm", "#F59E0B"]);
  const shown = rows.filter((r) => tab === 0 || (tab === 1 && r[1] === "Đang làm") || (tab === 2 && r[1] === "Hoàn thành"));
  return `
  <rect width="${W}" height="${H}" fill="#f4f5fb"/>
  <rect width="${W}" height="96" fill="#fff"/>
  <rect y="95" width="${W}" height="2" fill="#e5e7eb"/>
  <text x="48" y="62" ${FONT} font-size="34" font-weight="700" fill="#4F46E5">TaskFlow</text>
  <rect x="1400" y="26" width="320" height="44" rx="22" fill="#eef0f7"/>
  <text x="1430" y="56" ${FONT} font-size="22" fill="#9ca3af">Tìm kiếm công việc…</text>
  <rect x="1440" y="115" width="0" height="0"/>
  <rect y="97" width="300" height="${H - 97}" fill="#1f2937"/>
  ${["Tổng quan", "Công việc", "Lịch", "Báo cáo", "Cài đặt"]
    .map(
      (t, i) =>
        `<rect x="24" y="${140 + i * 74}" width="252" height="56" rx="14" fill="${i === 1 ? "#4F46E5" : "none"}"/>
         <text x="56" y="${177 + i * 74}" ${FONT} font-size="26" fill="${i === 1 ? "#fff" : "#9ca3af"}">${t}</text>`,
    )
    .join("")}
  <text x="360" y="190" ${FONT} font-size="46" font-weight="700" fill="#111827">Công việc của tôi</text>
  <rect x="1380" y="120" width="${DESKTOP_CLICK_LOG[0].x - 1380 + 160}" height="80" rx="16" fill="#4F46E5"/>
  <text x="${1380 + 70}" y="172" ${FONT} font-size="28" font-weight="700" fill="#fff">+ Thêm việc</text>
  ${tabs
    .map(
      (t, i) =>
        `<rect x="${360 + i * 280}" y="${DESKTOP_CLICK_LOG[1].y - 40}" width="250" height="80" rx="40" fill="${i === tab ? "#4F46E5" : "#e5e7eb"}"/>
         <text x="${360 + i * 280 + 125}" y="${DESKTOP_CLICK_LOG[1].y + 10}" text-anchor="middle" ${FONT} font-size="28" font-weight="700" fill="${i === tab ? "#fff" : "#4b5563"}">${t}</text>`,
    )
    .join("")}
  ${shown
    .map(
      (r, i) =>
        `<rect x="360" y="${400 + i * 110}" width="1500" height="92" rx="20" fill="#fff"/>
         <rect x="360" y="${400 + i * 110}" width="12" height="92" rx="6" fill="${r[2]}"/>
         <text x="410" y="${456 + i * 110}" ${FONT} font-size="30" font-weight="700" fill="#1f2937">${esc(r[0])}</text>
         <text x="1600" y="${456 + i * 110}" ${FONT} font-size="26" fill="#6b7280">${esc(r[1])}</text>`,
    )
    .join("")}
  ${filter ? `<rect x="1560" y="130" width="260" height="8" rx="4" fill="#F59E0B"/>` : ""}`;
}

// Four UI states: start, after the "add" click, after tab 2, after tab 3
const states: State[] = [
  { tab: 0, extraRow: false, filter: false },
  { tab: 0, extraRow: true, filter: false },
  { tab: 1, extraRow: true, filter: false },
  { tab: 2, extraRow: true, filter: true },
];
// seconds each state is on screen: changes land at the click times (1.2s, 3.4s, 4.3s); 8s in total
const holds = [1.2, 2.2, 0.9, 3.7];

for (const [i, s] of states.entries()) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${screen(s)}</svg>`;
  await sharp(Buffer.from(svg)).png().toFile(path.join(out, `web-${i + 1}.png`));
  console.log("wrote", `web-${i + 1}.png`);
}

const inputs = states.flatMap((_, i) => ["-loop", "1", "-framerate", "30", "-t", String(holds[i]), "-i", path.join(out, `web-${i + 1}.png`)]);
const filter = `${states.map((_, i) => `[${i}:v]`).join("")}concat=n=${states.length}:v=1:a=0,format=yuv420p[v]`;
const ff = spawnSync(
  "ffmpeg",
  ["-y", ...inputs, "-filter_complex", filter, "-map", "[v]", "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", path.join(out, "web-clip.mp4")],
  { stdio: "inherit" },
);
if (ff.status !== 0) throw new Error("ffmpeg failed (is ffmpeg installed and on PATH?)");
console.log("wrote web-clip.mp4");
