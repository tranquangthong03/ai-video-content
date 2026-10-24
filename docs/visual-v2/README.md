# Visual v2 — nghiệm thu

Mỗi video chạy qua `run_job` (`--auto`, trả lời mặc định), thời lượng đề xuất 30s, capture 1440×900,
template `desktop_focus`. Số liệu thô: `metrics-<site>.json` (sinh bằng `services/api/scripts/visual_metrics.py`;
camera đo bằng `apps/render/scripts/camera-metrics.ts`).

| | todomvc | aisoeasy.co | squoosh.app | aisoeasy.co @1280×800 |
|---|---|---|---|---|
| Thời lượng thực / mục tiêu | 30,5 / 30 s (+1,8%) | 32,2 / 30 s (+7,4%) | 31,1 / 30 s (+3,7%) | 32,2 / 30 s (+7,3%) |
| Camera ≥ cover (không tính establishing) | 100% | 99,7% | 99,8% | 99,7% |
| Camera trung bình (đơn vị cover) | 1,20 | 1,07 | 1,08 | 1,06 |
| Scene trùng chữ ký sau khi quay | 0 | 0 | 0 (1 scene được đổi section «Small») | 0 |
| Lần xuất hiện trang phụ | 0 | 0 | 0 | 0 |
| Giây chữ trên nền đen | 0,0 | 0,0 | 0,0 | 0,0 |
| Giữ trung bình sau thao tác | 1,58 s | 1,63 s | 1,58 s | 1,63 s |
| Tốc độ tối đa ở cảnh thao tác | 1,00 | 1,00 | 1,00 | 1,00 |
| Tốc độ tối đa ở cảnh cuộn/chỉ vị trí | 1,00 | 1,15 | 1,15 | 1,15 |
| Tỉ lệ cảnh quay thật (footage_ratio) | 0,74 | 0,86 | 0,84 | 0,86 |
| Đoạn chết đã cắt | 2,2 s | 4,6 s | 20,3 s | 2,9 s |
| idle_max ≤ 2,5 s | đạt | đạt | đạt | đạt |
| ffprobe | 1080×1920 h264 yuv420p 30 fps | như trái | như trái | như trái |

Ảnh: `<site>.png` là contact sheet 16 frame; `<site>-still-N.png` là 3 still lấy giữa các cảnh quay (camera đã tới nơi).

## aisoeasy.co: trước và sau
- `aisoeasy-before.png`: video cũ (job `j234d75f6e4`) — toàn trang 1920 trong khung nhỏ, nửa dưới trống, form "Create account"
  hiện hai lần, scene mở đầu và CTA là chữ trên nền đen, rate tới 1,37.
- `aisoeasy.png`: bản mới — khung 4:5 lấp kín, camera zoom theo tiêu điểm, hook/CTA là hình sản phẩm.
  Hai sheet dùng cùng cách lấy 16 frame đều theo thời lượng. Lưu ý: kịch bản được LLM viết lại nên không phải cùng từng scene.

## Biến thể capture 1280×800 (không đổi mặc định)
- Layout KHÔNG đổi sang tablet/mobile ở 1280: vẫn 10 liên kết điều hướng, không có nút hamburger, grid 2 cột,
  h1 cùng cỡ 60 px, không cuộn ngang (`aisoeasy-layout-1440-vs-1280.json`, `.png`). Chỉ khác lề trái (h1 ở x=32 thay vì 112).
- `aisoeasy-1440-vs-1280-closeup.png`: hai still cận chữ cùng thời điểm, trái 1440×900, phải 1280×800. Ở 1280 chữ to hơn
  khoảng 12% so với chiều cao khung (cùng nội dung CSS, viewport thấp hơn 100 px) và vẫn nét. Các chỉ số còn lại gần như
  trùng bản 1440 (cùng kịch bản, cùng cấu trúc cảnh). Lưu ý: hai video không phải cùng từng khung hình, vì thời điểm và
  vị trí cuộn khác nhau chút ít giữa hai lần quay.

## Hạn chế còn lại
- Chữ khi zoom được phóng từ clip 1440 px (không quay được 2x, xem `spike-2x/`); `SHARPEN_AMOUNT=0.5` bù một phần.
- Feature không có bước nào (ví dụ `edit_todo_dblclick` của todomvc) vẫn rơi về ảnh trang + Ken Burns, không phải clip.
- Nút CTA tìm bằng heuristic (từ khóa + vùng header/hero); khi không có nút rõ ràng thì dùng ảnh trang chủ.
- Scene trùng chữ ký chỉ được đổi sang heading chưa dùng của cùng trang (thử tối đa 3 lần); hết heading thì bỏ scene
  (không bao giờ dưới 3 scene).
