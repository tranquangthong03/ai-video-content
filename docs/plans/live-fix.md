# Kế hoạch LIVE-FIX

Nguồn: tin nhắn người dùng ngày 2026-10-29 (test live demoblaze, ghi chú ở `docs/demo-note.md`). Kết quả ở `docs/live-fix/README.md`.

## Nguyên tắc
- **Tổng quát (bổ sung bắt buộc, 2026-10-29)**: mọi sửa là thay đổi chung, chạy trên mọi website; demoblaze chỉ là một ca kiểm thử. Không tên miền/chuỗi đặc thù trong `app/`, `apps/`, prompt (trừ `SHARED_DEMO_SITES`); `tests/test_generality.py` kiểm tự động. Danh sách động từ cam kết vi + en dùng chung ở `app/core/commit_verbs.py` (C, D, G dùng lại, không lặp). Ví dụ trong prompt LLM trung tính hoặc nhiều loại sản phẩm.
- Không code riêng demoblaze; chỉ quy tắc chung cho SPA đọc dữ liệu bằng POST.
- Không nới an toàn: không chắc = chặn; mọi ghi vẫn bị chặn ngoài cửa sổ ghi.
- Commit nhỏ, mỗi commit T0 vùng bị ảnh hưởng, nối `&&`, kiểm exit code.

## Chẩn đoán (xong): giả thuyết A đúng, xem `docs/live-fix/README.md`.

## Commit theo thứ tự
| # | Việc | Ý chính |
|---|---|---|
| A | Guard đọc/ghi theo NGỮ CẢNH + env_issue | `classify_write_intent(url, body, trigger)`: (a) hành động gây ra là commit → write; (b) page_load/navigate/filter/search/open_detail + body không ý định ghi + đường dẫn không có động từ ghi → read; (c) không rõ hành động → từ trong đường dẫn + body (động từ ghi thắng động từ đọc, tách từ ghép như `addtocart`/`viewcart`), còn lại unknown → chặn. Bỏ "by", "entries" khỏi từ đọc. Ý định ghi trong body: GraphQL mutation, operationName/method/action/op/type là động từ ghi, trường cá nhân/giao dịch. Sự kiện `guard_decision`; sau `wait_for_settle` trang trống + request bị chặn trong 3 s → `env_issue guard_broke_page`; give_up `env_blocked` cần bằng chứng; thẻ cảnh báo web + CLI; test fixture fetch POST + ≥20 cặp đơn vị |
| B | Chờ nội dung + ảnh trắng | settle chờ fetch/XHR = 0 trong 500 ms + vùng chính có nội dung, tối đa 8 s; khung trắng → bước `blank`, không vào storyboard |
| C | Mô tả = mục tiêu bắt buộc; redo/modify | `required_actions` (LLM + kiểm bằng code); không đổi luồng; phân loại redo/modify; redo không giữ tiền tố; modify chỉ giữ tiền tố hợp lệ; 6 câu fixture |
| D | `goal_status` bằng code | reached / stopped_before_submit / not_reached; hành động cam kết thuộc submit_policy; ref stop_before_submit kiểm `target_text` |
| E | no_effect + vòng lặp | delta inventory; cùng trạng thái lần 3 → `stuck`/`env_blocked`; storyboard bỏ no_effect |
| F | Hộp thoại native | `page.on("dialog")` ở app/browser: alert accept, confirm/prompt dismiss (trừ bước gửi được phép); ghi sự kiện `dialog` |
| G | Gợi ý sửa storyboard | bỏ ví dụ OrangeHRM, sinh bằng code từ luồng hiện tại + vitest |

## Nghiệm thu
T0 các vùng (browser, flows, core, web) + `pytest -n auto` 1 lần, ruff, mypy, codegen-check nếu đổi schema, tsc + vitest; T1 4 snapshot không xấu hơn `docs/regress/last.json`; T3 live tối đa 2 vòng (demoblaze laptop → Add to cart + câu "làm lại"; orangehrm "Thêm nhân viên mới" 0 ghi lọt; todomvc ra video), ghi bảng guard_decision/env_issue; `docs/live-fix/README.md` (trước/sau, ảnh `docs/screenshots/60-*.png`); cập nhật `docs/HANDOFF.md` mục 5–7 và 8 (thêm demoblaze).

## Thay đổi so với bản kế hoạch trước (báo ở commit A)
| Chỗ | Đã đổi |
|---|---|
| Quy tắc guard | Từ «theo tên đường dẫn» sang «theo hành động gây ra → body → đường dẫn». Bỏ `by`, `entries`. |
| Fixture test | Theo KIỂU API (REST tên lạ, GraphQL, JSON-RPC, search service, form urlencoded có email), cửa hàng chỉ là một trong số đó |
| Quyết định mở về `viewcart` | Không còn cần hỏi: tên liền được tách từ; danh từ (`cart`, `order`) chỉ là ghi khi không đi cùng động từ đọc, nên `viewcart` là đọc khi hành động là tải/điều hướng, và ghi khi không rõ hành động |
| Kiểm tra tổng quát | `tests/test_generality.py` (quét tên site) + bảng «Tính tổng quát» ở nghiệm thu |
| Nghiệm thu T3 | Thêm explore-only trên ≥ 4 URL (squoosh, todomvc, orangehrm dừng trước khi gửi, excalidraw/paletton): bảng read/write/unknown/env_issue so với trước; 0 ghi lọt, không env_issue mới |

## Chưa rõ / giới hạn đã biết (ghi ở commit A)
- Hành động `type` (không phải ô tìm), `select`, `check`, `pick_date`, nút không thuộc commit/liên kết được xét theo quy tắc (c), không theo (b): an toàn hơn đề bài.
- Body JSON đọc tới 256 KB (không phải 4 KB) để không siết chặt các truy vấn tìm kiếm lớn đang qua được.
- Explorer (`extract_page`) chưa phát `env_issue` (không có guard trong đường đó); agent và recorder có.
