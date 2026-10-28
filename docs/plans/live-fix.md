# Kế hoạch LIVE-FIX

Nguồn: tin nhắn người dùng ngày 2026-10-29 (test live demoblaze, ghi chú ở `docs/demo-note.md`). Kết quả ở `docs/live-fix/README.md`.

## Nguyên tắc
- Không code riêng demoblaze; chỉ quy tắc chung cho SPA đọc dữ liệu bằng POST.
- Không nới an toàn: không chắc = chặn; mọi ghi vẫn bị chặn ngoài cửa sổ ghi.
- Commit nhỏ, mỗi commit T0 vùng bị ảnh hưởng, nối `&&`, kiểm exit code.

## Chẩn đoán (xong): giả thuyết A đúng, xem `docs/live-fix/README.md`.

## Commit theo thứ tự
| # | Việc | Ý chính |
|---|---|---|
| A | Guard đọc/ghi + env_issue | `classify_write_intent(url, body)` → read/write/unknown (từ theo ranh giới từ; GraphQL query vs mutation; body JSON < 4 KB không trường ghi); sự kiện `guard_decision`; sau `wait_for_settle` trang trống + request bị chặn trong 3 s → `env_issue guard_broke_page`; give_up `env_blocked` cần bằng chứng; thẻ cảnh báo web + CLI; test fixture fetch POST + ≥20 cặp đơn vị |
| B | Chờ nội dung + ảnh trắng | settle chờ fetch/XHR = 0 trong 500 ms + vùng chính có nội dung, tối đa 8 s; khung trắng → bước `blank`, không vào storyboard |
| C | Mô tả = mục tiêu bắt buộc; redo/modify | `required_actions` (LLM + kiểm bằng code); không đổi luồng; phân loại redo/modify; redo không giữ tiền tố; modify chỉ giữ tiền tố hợp lệ; 6 câu fixture |
| D | `goal_status` bằng code | reached / stopped_before_submit / not_reached; hành động cam kết thuộc submit_policy; ref stop_before_submit kiểm `target_text` |
| E | no_effect + vòng lặp | delta inventory; cùng trạng thái lần 3 → `stuck`/`env_blocked`; storyboard bỏ no_effect |
| F | Hộp thoại native | `page.on("dialog")` ở app/browser: alert accept, confirm/prompt dismiss (trừ bước gửi được phép); ghi sự kiện `dialog` |
| G | Gợi ý sửa storyboard | bỏ ví dụ OrangeHRM, sinh bằng code từ luồng hiện tại + vitest |

## Nghiệm thu
T0 các vùng (browser, flows, core, web) + `pytest -n auto` 1 lần, ruff, mypy, codegen-check nếu đổi schema, tsc + vitest; T1 4 snapshot không xấu hơn `docs/regress/last.json`; T3 live tối đa 2 vòng (demoblaze laptop → Add to cart + câu "làm lại"; orangehrm "Thêm nhân viên mới" 0 ghi lọt; todomvc ra video), ghi bảng guard_decision/env_issue; `docs/live-fix/README.md` (trước/sau, ảnh `docs/screenshots/60-*.png`); cập nhật `docs/HANDOFF.md` mục 5–7 và 8 (thêm demoblaze).

## Quyết định cần duyệt
1. Cho phép `viewcart`-kiểu (tên "view…cart") là đọc? Quy tắc đề xuất: từ ghi chỉ khớp theo ranh giới từ, nên `viewcart` (một từ liền) vẫn là **unknown → chặn**; muốn cho qua phải có body đọc rõ ràng. An toàn hơn, nhưng giỏ hàng demoblaze sẽ không tải.
2. T3 live cần API key LLM và mạng; chỉ chạy sau khi A–G xong.
