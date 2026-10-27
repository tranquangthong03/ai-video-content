# Lượt CAM — camera và nhịp

Kế hoạch: `docs/plans/cam.md`. Công cụ:
- `services/api/app/producer/motion_qa.py` + `scripts/motion_qa.py <job> docs/cam <tên> <before|after>`: đo chuyển động camera từ chính video cuối (khung media 4:5, ORB + RANSAC), ghi `<tên>-<tag>.json` và biểu đồ `<tên>-<tag>.png` (cột đỏ = vượt ngưỡng).
- `scripts/camera_preview.py <render_props.json> <png>`: vẽ lộ trình camera và 6 still có khung tiêu điểm **không render video** (dùng đúng code camera của renderer qua `apps/render/scripts/camera-path.ts`).
- `scripts/cam_table.py docs/cam <tag>`: bảng so sánh.
- Motion QA nằm trong `report.json["motion_qa"]` và scorecard của trang video.

## Trước (3 video M1, chưa sửa camera)

Cách đo: bỏ 0,6 s đầu (khung media hiện dần); zoom/pan tính theo từng khung hình; `Đứng yên rồi giật` = đứng yên ≥ 0,4 s rồi khung kế zoom > 2,5% hoặc kéo > 1,5%.

### before

| Chỉ số | Ngưỡng | orangehrm | squoosh | todomvc |
|---|---|---|---|---|
| Zoom tối đa mỗi khung | ≤ 2,5% | **16.9%** ✗ | **3.2%** ✗ | **11.5%** ✗ |
| Kéo khung tối đa mỗi khung | ≤ 1,5% | **10.2%** ✗ | **1.6%** ✗ | **8.2%** ✗ |
| Đứng yên rồi giật | 0 | **1** ✗ | **1** ✗ | **1** ✗ |
| Cảnh chớp (< 0,8 s) | 0 | 0 | **1** ✗ | 0 |
| Ảnh/canvas đang tải (ms) | 0 | 0 | 0 | 0 |
| Đứng yên tuyệt đối dài nhất (ms) | ≤ 400 | **2000** ✗ | **633** ✗ | **1267** ✗ |
| Khung chữ tiêu điểm bị cắt | 0 | **13** ✗ | **12** ✗ | 0 |
| Tiêu điểm khớp lời/thao tác | ≥ 85% | **53%** ✗ | **28%** ✗ | **74%** ✗ |
| Đạt cả bộ | | không | không | không |


Các đỉnh đỏ trong biểu đồ trùng với chẩn đoán: todomvc giây 6,8 / 14,8 / 22,6 / 29,9 (zoom ≈ 11%/khung), OrangeHRM giây 7,1 (zoom 17%/khung); nhảy 1 khung ở giây ~10,2 (todomvc, pan 8%).
Ghi chú: `loading_frames_ms = 0` cả ba video dù squoosh có khung xám chen giữa lúc 8,4–8,7 s; số này đo trên clip từng cảnh nên chưa bắt được khung đó (xem phần C).

Biểu đồ: `orangehrm-before.png`, `squoosh-before.png`, `todomvc-before.png`; xem trước camera: `todomvc-preview-before.png`.
