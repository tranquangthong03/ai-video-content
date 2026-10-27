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


## Sau lượt CAM (D → A → B → C → E)

Đo bằng `scripts/motion_qa.py` trên video chạy lại hoàn toàn (kịch bản mới + quay + render). Mỗi lần LLM viết lại kịch bản thì clip/tiêu điểm đổi nên số đo dao động giữa các lần; bảng dưới là lần cuối.

| Chỉ số | Ngưỡng | orangehrm | squoosh | todomvc |
|---|---|---|---|---|
| Zoom tối đa mỗi khung | ≤ 2,5% | 2,52% ✗ (sát) | 2,1% | 2,3% |
| Kéo khung tối đa mỗi khung | ≤ 1,5% | 1,1% | **2,2%** ✗ | 0,7% |
| Đứng yên rồi giật | 0 | 0 | 0 | 0 |
| Cảnh chớp (< 0,8 s) | 0 | 0 | 0 | 0 |
| Ảnh/canvas đang tải (ms) | 0 | 0 | 0 | 0 |
| Đứng yên tuyệt đối dài nhất (ms) | ≤ 400 | 167 | 0 | 0 |
| Khung chữ tiêu điểm bị cắt | 0 | **207** ✗ | **434** ✗ | **38** ✗ |
| Tiêu điểm khớp lời/thao tác | ≥ 85% | **71%** ✗ | 100% | 93% |
| Đạt cả bộ | | không | không | không |

So với "trước": zoom từ 11–17%/khung xuống ≈ 2,1–2,5%; kéo khung từ tới 10% xuống 0,7–2,2%; đứng yên tới 2000 ms xuống ≤ 167 ms; không còn đứng-rồi-giật hay cảnh chớp; focus_match từ 28–74% lên 71–100%.

**Chưa đạt, nói thẳng**: (1) `focus_text_clipped` — khung camera cắt mép chữ của chính tiêu điểm, nặng nhất ở squoosh (hook nhắm vào ô có nhãn dài); (2) squoosh có một lần kéo khung 2,2%/khung; (3) orangehrm 71% khớp và zoom sát ngưỡng (2,52%). Chưa sửa vì cần thay đổi cách tính khung tiêu điểm (nới biên theo chiều rộng chữ) và sẽ phải đo lại cả bộ.

Wording (E): hook > 12 từ được LLM viết lại một lần, chỉ cắt ở ranh giới cụm làm phương án cuối; số trong proof bank phân loại benefit/identifier/other, headline/hook/stat chỉ dùng benefit (squoosh: stat «2.8MB» là số lợi ích, không còn mã định danh); critic có role riêng `copy_critic`, cảnh < 6 được viết lại tối đa 2 vòng kèm ví dụ theo loại sản phẩm.

Điểm critic (hook / benefit / proof / CTA / flow), trước E → sau E (LLM sinh lại nên dao động):
- orangehrm: 7/5/2/6/6 → 6/5/3/6/5 (2 vòng viết lại)
- squoosh: 8/6/7/8/7 → 7/6/7/6/7
- todomvc: 6/5/4/7/6 → 6/5/4/6/6

Kết luận trung thực: critic **không cải thiện** trong lần chạy này (benefit vẫn 5–6, CTA tụt 1 điểm ở 2 site); bản viết lại chỉ được giữ khi không thấp hơn. Cần thêm một lượt riêng cho wording.

Video: `E:\WORK SPACE\AI-video-content\services\api\out\cam-orangehrm\video.mp4`, `...\cam-squoosh\video.mp4`, `...\cam-todomvc\video.mp4`. Biểu đồ: `*-after.png`, JSON `*-after.json`; kiểm tra tổng quát: `generalization.md`.
