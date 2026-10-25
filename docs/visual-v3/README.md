# Visual v3 — nghiệm thu: chọn tính năng + camera theo ý nghĩa

Ba video chạy qua `run_job` bằng `services/api/scripts/acceptance_v3.py` (chọn tính năng như người dùng: khớp từ khóa,
thiếu thì `explore_more`). Bảng tiêu điểm và số liệu sinh bằng `scripts/focus_report.py`; cột «Khớp» do tôi xem từng dòng
trên contact sheet và bảng (file `review-<site>.json`); dòng «mở đầu» (toàn trang ~1–2 s đầu mỗi cảnh) không tính.

## Video (đường dẫn tuyệt đối)
- todomvc: `E:\WORK SPACE\AI-video-content\services\api\out\v3\todomvc\video.mp4` — chọn: thêm việc + sửa việc
- squoosh: `E:\WORK SPACE\AI-video-content\services\api\out\v3\squoosh\video.mp4` — chọn: nạp/nén ảnh + so sánh chất lượng
- aisoeasy.co: `E:\WORK SPACE\AI-video-content\services\api\out\v3\aisoeasy\video.mp4` — chọn: Learning Paths (thêm bằng `explore_more`,
  mô tả «Lộ trình học theo vai trò (Learning Paths)») + AI Learning Hub

(`out/` bị gitignore; contact sheet 16 frame và bảng nằm cạnh README này: `<site>.png`, `<site>-focus.md`, `metrics-<site>.json`.)
Ảnh thẻ chọn tính năng (2 trạng thái): `docs/screenshots/select-features.png`, `docs/screenshots/select-features-exploring.png`.

Lưu ý chạy: aisoeasy lần đầu lỗi ở bước viết kịch bản («headline dài 43 ký tự, tối đa 40», exit 6); chạy lại 1 lần từ bước script thì xong.

## Chỉ số mới
| | Mục tiêu | todomvc | squoosh | aisoeasy |
|---|---|---|---|---|
| `frames_text_clipped` (chữ của tiêu điểm bị cắt ở mép, sau khi camera tới nơi) | 0 | **0** / 473 frame | **0** / 331 | **0** / 473 |
| % thời gian tiêu điểm là nav/aside/footer khi lời đọc không nhắc | 0 | **0 %** | **0 %** | **0 %** |
| Lần zoom vào bên trong ảnh | 0 | **0** | **0** | **0** |
| % thời gian tiêu điểm khớp lời đọc (đã xem tay) | ≥ 80 % | **49 %** | **0 %** | **16 %** |
| Nguồn tiêu điểm plan / rule / fallback | | 8 / 2 / 0 | 5 / 0 / 2 | 8 / 0 / 0 |
| Chữ bị cắt ở mép của BẤT KỲ khối nào (tham khảo) | | 99 frame | 123 | 405 |

Không đạt: **% khớp lời đọc** (mục tiêu 80 %). Ba chỉ số «không cắt chữ / không tiêu điểm ở nav-aside-footer / không zoom vào ảnh» đạt.
Ghi chú: todomvc dòng 10 tiêu điểm là nút «React» ở footer, được cho qua vì lời đọc có chữ «React» (đúng quy tắc «nhắc tới»), nhưng tôi vẫn chấm «không khớp» vì lời đọc đang nói về địa chỉ trang.

## Chỉ số visual-v2 cũ
| | todomvc | squoosh | aisoeasy |
|---|---|---|---|
| Thời lượng thực / mục tiêu | 26,4 / 30 s (−12 %) | 35,0 / 30 s (+16,8 %) | 32,6 / 30 s (+8,7 %) |
| Camera ≥ cover (không tính mở đầu) | 93,2 % | 64,1 % | 60,1 % |
| Camera trung bình (đơn vị cover) | 1,06 | 1,08 | 0,97 |
| Scene trùng chữ ký | 0 | 1 (s3 ~ s2) | 0 |
| Trang phụ | 0 | 0 | 0 |
| Giây chữ trên nền đen | 0 | 0 | 0 |
| Giữ trung bình sau thao tác | 1,58 s | 1,58 s | 1,63 s |
| Tốc độ tối đa cảnh thao tác / mọi cảnh | 1,00 / 1,15 | 1,00 / 1,15 | 1,00 / 1,15 |
| footage_ratio | 1,00 | 0,57 | 0,81 |
| Đoạn chết đã cắt | 5,5 s | 4,5 s | 2,8 s |
| idle ≤ 2,5 s | đạt | **không đạt** | **không đạt** |

«Camera ≥ cover» giảm so với v2 (99–100 %) là cố ý: khối chữ rộng hơn cửa sổ ở cover thì camera zoom ra (xuống tới cả bề rộng clip) để không cắt chữ.

## Bảng tiêu điểm
Xem `todomvc-focus.md`, `squoosh-focus.md`, `aisoeasy-focus.md` (cột: thời gian | cụm lời đọc | tiêu điểm thực tế | nguồn | khớp).

## Đánh giá
- **Đã sửa được**: tiêu điểm không còn là sidebar «React / Official Resources» hay ảnh mèo; khi gõ, tiêu điểm là ô nhập; chữ không bị cắt
  khi camera đã tới; không zoom vào trong ảnh; không tiêu điểm ở nav/aside/footer khi lời đọc không nhắc.
- **Chưa đạt (khớp lời đọc)** và nguyên nhân tôi thấy:
  1. *Nội dung quay sai, camera không cứu được.* aisoeasy s2 («mở lộ trình theo vai trò») thực ra quay mục «Vietnam's AI community…»,
     s3 («AI Learning Hub») quay thẻ «TikTok», vì `showcase_target`/bước demo của feature được thêm bằng `explore_more` trỏ sai phần tử
     trên trang. Planner chỉ chọn được trong những gì đang hiện trên màn hình.
  2. squoosh: cảnh «so sánh» (s4) chỉ bấm một ảnh mẫu rồi chờ, thanh so sánh trước/sau gần như không vào khung (chỉ thấy panel Edit);
     s2 và s3 cùng một chuỗi bước nên bị trùng. Scene hook/CTA dùng toàn trang (fallback) vì không có item phù hợp.
  3. todomvc: «nhấp đúp vào todo» (dòng 7) tiêu điểm vẫn là ô nhập, vì ở khoảng đó chưa có item todo trong inventory (todo hiện sau).
  4. Nhịp: planner đôi khi chia khoảng theo thời gian của cả cảnh thay vì theo từng cụm; quy tắc ≥ 1,5 s làm các cụm ngắn bị gộp.
- **Việc nên làm tiếp (ngoài phạm vi lần này)**: kiểm tra `showcase_target` cho feature thêm bằng `explore_more` (đối chiếu text với heading
  của trang vừa khám phá); bước demo «so sánh» của squoosh (kéo thanh trượt); ràng buộc idle ≤ 2,5 s và thời lượng ±10 % cho squoosh/aisoeasy.
