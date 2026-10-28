# V3 — «Đơn giản hóa như editor thật»

Kế hoạch: `docs/plans/v3.md`. T1 trên 4 snapshot (`orangehrm`, `squoosh`, `todomvc`, `aisoeasy`), 0 lần gọi LLM, không mở trình duyệt. Mốc: `docs/regress/last.json` (`t1_frame`, `t1_focus`).

## A. Template `desktop_frame` (mặc định mới)

Khung 16:9 rộng 96% (1040×585) ngay dưới tiêu đề; phụ đề karaoke cỡ 64 px (≤ 2 dòng) rồi bullet key_point (≤ 2 dòng). Camera **đứng yên ở toàn cảnh**; chỉ zoom khi có sự kiện (bấm / gõ / chọn / kết quả hiện ra) **và** lời đọc nói về nó, tối đa 2 lần mỗi cảnh (hook 1 lần, vào kết quả; CTA không), một mức 1,7×, vùng zoom = khối giao diện (card / hàng / dialog, hoặc ô + nhãn) + 10% đệm; khối to quá thì hạ mức (≥ 1,3×), vẫn không chứa thì **không zoom**. Vào 0,7 s ease-in-out, giữ yên ≥ 1,2 s, ra 0,6 s. Crossfade chỉ khi hai camera đứng yên ở toàn cảnh, còn lại cắt thẳng. `desktop_focus` vẫn còn (`--template desktop_focus`).

| Chỉ số (T1) | Ngưỡng | orangehrm | squoosh | todomvc | aisoeasy |
|---|---|---|---|---|---|
| Camera chuyển động | ≤ 25% | 0,0% (focus 13,2%) | 0,0% (14,2%) | 16,6% (17,1%) | 15,2% (15,8%) |
| Toàn cảnh | ≥ 50% | 100% (0%) | 100% (23%) | 70,2% (16,9%) | 68,9% (0%) |
| Zoom/cảnh (max) | ≤ 2 | 0 | 0 | 2 | 1 |
| Khối bị cắt (frame) | 0 | 0 | 0 | 0 | 0 |
| Crossfade khi camera chuyển động | 0 | 0 | 0 | 0 | 0 |
| Ảnh chồng (frame) | 0 | 0 (0) | 0 (1) | 0 (0) | 0 (0) |
| Đứng rồi giật / cảnh chớp / ảnh đang tải | 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| Zoom / pan lớn nhất mỗi frame | ≤ 5% / 3,5% | 0,2% / 0,1% | 0,8% / 0,1% | 4,5% / 1,7% | 4,4% / 1,7% |
| Đứng yên lâu nhất (ms) | ≤ 5000 | 4467 | 3367 | 2700 | 3300 |
| Chữ tiêu điểm bị cắt (focus) | — | — (0) | — (0) | — (0) | — (**128**) |
| Motion QA đạt | | có | có | có | có |

Trong ngoặc: cùng snapshot với `desktop_focus` (camera cũ). Với aisoeasy, camera cũ cắt chữ 128 frame và tiêu điểm khớp lời chỉ 71,5%; camera mới không còn khái niệm «tiêu điểm theo dõi».

**Ngưỡng cũ phải nới cho `desktop_frame` (chọn có chủ ý, cần bạn xem bằng mắt):** thiết kế mới tự mâu thuẫn với 3 ngưỡng cũ nên chúng được đặt riêng theo template (`TEMPLATE_LIMITS` trong `app/producer/motion_qa.py`): (1) tốc độ zoom 2,5% → 5%/frame và pan 1,5% → 3,5%: zoom 1,7× trong 0,7 s theo ease-in-out cần ~4% mỗi frame ở đỉnh; giữ 2,5% buộc mỗi lần zoom kéo dài ≥ 1,1 s và camera sẽ chuyển động > 25% thời gian; (2) đứng yên 400 ms → 5 s: camera đứng yên là chủ ý, trang giữ nguyên trong lúc đọc một câu. Các ngưỡng còn lại (đứng-rồi-giật, chớp, ảnh đang tải) giữ nguyên 0. `focus_match` không dùng cho `desktop_frame` (không còn track bám theo; việc «lời đọc liên quan» do bộ lập kế hoạch kiểm tra trước khi zoom).

**Kết quả thật khi xem số:** orangehrm và squoosh **không có cú zoom nào** (orangehrm: form nằm trong một card to hơn cửa sổ ở 1,3× nên theo quy tắc «không bao giờ cắt khối» giữ toàn cảnh; squoosh: một thao tác không tìm được phần tử trong ảnh chụp, thao tác kia có lời đọc không nói về nó). Chữ nhỏ ở toàn cảnh hơn bản 4:5. Chỉnh `SHOT_MIN_LEVEL` (1,3) / `MAX_BLOCK_SHARE` trong `app/producer/zoom_shots.py` nếu muốn zoom nhiều hơn.

### Video và hình để xem bằng mắt

| | Video (desktop_frame) | Contact sheet 16 frame | 2 still (zoom / toàn cảnh) | Đồ thị camera |
|---|---|---|---|---|
| orangehrm | `E:\WORK SPACE\AI-video-content\services\api\out\regress\orangehrm\video.mp4` | `docs/v3/orangehrm-frame-sheet.png` | `orangehrm-frame-stillA/B.png` | — |
| squoosh | `…\out\regress\squoosh\video.mp4` | `docs/v3/squoosh-frame-sheet.png` | `squoosh-frame-stillA/B.png` | — |
| todomvc | `…\out\regress\todomvc\video.mp4` | `docs/v3/todomvc-frame-sheet.png` | `todomvc-frame-stillA/B.png` | `preview-todomvc-frame.png` |
| aisoeasy | `…\out\regress\aisoeasy\video.mp4` | `docs/v3/aisoeasy-frame-sheet.png` | `aisoeasy-frame-stillA/B.png` | `preview-aisoeasy-frame.png` |

(`…` = `E:\WORK SPACE\AI-video-content\services\api`; `*-focus-*` là cùng snapshot với camera cũ để so sánh. Video nằm trong `out/` — ngoài git, bị ghi đè khi chạy lại `regress.py --tier t1`.)

## B. Nội dung có giá trị (không tốn token)

| Việc | Cách |
|---|---|
| `value_actions` | `app/core/flow_value.py`: số bước gõ / chọn / tick / chọn ngày / upload, và click không chuyển trang mà làm xuất hiện thứ mới (click chuyển trang chỉ tính khi hiện canvas/video, ví dụ ảnh mẫu mở trong editor). Đề xuất (chưa chạy) ước lượng từ `expected_steps`. < 2 → nhãn «Chỉ điều hướng — video sẽ ít hấp dẫn», Discovery xếp sau, ghi vào `report["flow"]["value_actions"]` và dòng scorecard. |
| Trang trống | ≥ 2 dấu hiệu khác nhau (số 0 cạnh nhãn tiến độ / «0/…», «(0)», No data, Nothing here, Chưa có…, trang báo not found / failed to load) → cảnh báo ở thẻ select_flow và storyboard (vẫn cho duyệt). |
| Thẻ select_flow | ô «Tự mô tả luồng muốn quay» lên đầu + 2 ví dụ; mỗi luồng hiện «~N thao tác tạo kết quả» và nhãn (web: `docs/screenshots/50-select-flow-v3.png`; CLI hỏi mô tả trước). |
| Storyboard | cảnh báo trước nút Duyệt (`docs/screenshots/51-storyboard-warning.png`). |
| Test T0 (dữ liệu đã lưu) | `tests/test_flow_value.py`: aisoeasy → gắn nhãn + cảnh báo trống; todomvc / orangehrm / squoosh → không cảnh báo sai. |

## Snapshot thứ 4

`tests/golden/aisoeasy/` từ job live đăng nhập (`out/jobs/j70a1281ec4`, video ~31 s). JSON đã thay tên tài khoản (`quangthong…` → `demo-user`) và mọi địa chỉ e-mail (`golden.py` `SCRUB`); không có `storage_state`, credential hay profile. Media ở `tests/golden-media/aisoeasy/` (ngoài git). Dựng lại: `uv run python scripts/golden.py build --names aisoeasy`.
