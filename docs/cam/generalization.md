# CAM — Kiểm tra tổng quát hóa (3 site mới, không tinh chỉnh riêng)

Chạy `--auto`, không đăng nhập, **không chỉnh code theo từng site** trong lượt này.

| Site | Kết quả |
|---|---|
| https://excalidraw.com | Ra video |
| https://regex101.com | **Không ra video**: explorer hết ngân sách thời gian 300 s ở bước analyze (exit 4), mới xem 5/15 trang |
| https://coolors.co/generate | **Bị Cloudflare chặn** → thay bằng https://paletton.com/ (ghi chú theo yêu cầu "thay nếu bị chặn") |

Video (đường dẫn tuyệt đối):
- `E:\WORK SPACE\AI-video-content\services\api\out\gen-excalidraw\video.mp4`
- `E:\WORK SPACE\AI-video-content\services\api\out\gen-paletton\video.mp4`

## Motion QA (render lại bằng camera mới nhất)

| Chỉ số | Ngưỡng | excalidraw | paletton |
|---|---|---|---|
| Zoom tối đa mỗi khung | ≤ 2,5% | 2,52% ✗ (sát) | 2,43% |
| Kéo khung tối đa mỗi khung | ≤ 1,5% | **1,75%** ✗ | 1,32% |
| Đứng yên rồi giật | 0 | 0 | 0 |
| Cảnh chớp | 0 | 0 | 0 |
| Ảnh/canvas đang tải (ms) | 0 | 0 | **4000** ✗ |
| Đứng yên dài nhất (ms) | ≤ 400 | **833** ✗ | 67 |
| Khung chữ tiêu điểm bị cắt | 0 | **37** ✗ | **32** ✗ |
| Tiêu điểm khớp lời/thao tác | ≥ 85% | 100% | 89% |

Biểu đồ và JSON: `excalidraw-gen.json/.png`, `paletton-gen.json/.png`.

## Scorecard, footage, lỗi

| | excalidraw | paletton |
|---|---|---|
| footage_ratio | 0,737 | 0,900 |
| Thời lượng | 31,4 s | 62,6 s (vượt khung 30–60 s) |
| steps_in_clip | báo cáo chưa ghi trường này theo cảnh (None) | như vậy |
| Critic (hook/benefit/proof/CTA/flow) | 7/6/5/6/6 | 7/6/**1**/6/6 |
| Dòng scorecard không đạt | benefit, CTA, zoom, pan, static, text_clipped | benefit, CTA, proof_used, loading_frames, text_clipped |
| Cảnh báo | 0 | 2 |

## Nhận xét

- Không site nào qua hết ngưỡng. Lỗi chính khi sang site lạ: **khung chữ tiêu điểm bị cắt** (cả hai), **kéo khung vượt ngưỡng** trên canvas (excalidraw), **khung phẳng bị coi là đang tải** trên paletton (có thể là dương tính giả: vùng màu phẳng thật, vì paletton là bảng màu) và **regex101 quá chậm ở bước khám phá**.
- `steps_in_clip` chưa là trường của `report.json` theo cảnh; cần thêm nếu muốn theo dõi.
- Đây là số liệu gốc cho lượt sau; không có chỉnh sửa riêng cho site nào.
