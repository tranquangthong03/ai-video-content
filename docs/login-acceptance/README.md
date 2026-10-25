# Nghiệm thu đăng nhập (cách B, site fixture `tests/fixtures/site_auth`)

`services/api/scripts/acceptance_login.py` dựng site có đăng nhập (landing public → «Log in» → form 2 bước email → Next →
mật khẩu → `/app` có danh sách, nút tạo, email ở header, `/app/settings`, nút «Invite member») rồi chạy `run_job` với
`requires_login=True`, một «người dùng» trả lời thẻ `login_required` bằng tài khoản demo, các câu hỏi còn lại trả lời mặc định.
LLM thật (DeepSeek), render thật.

## Kết quả (job `services/api/out/v3/login`)
- Thoát 0, có video: `E:\WORK SPACE\AI-video-content\services\api\out\v3\login\video.mp4` (20,4 s, 1080×1920).
- Thẻ `login_required` được hỏi **đúng 1 lần**, ngay đầu job (`reason: requested`); hệ thống tự tìm link «Log in» ở landing
  (`/login`), đăng nhập 2 bước bằng tài khoản demo (2 POST: `/login/identify`, `/login/password`).
- Khám phá bắt đầu từ trang chính của app (`pages_seen: [/app]`, không phải landing); `/app/settings` nằm trong
  `sensitive_skipped` và không được truy cập; `/logout` không bị gọi; nút «Invite member» không bị bấm.
- `login_report.json`: chỉ ghi host nhận POST của pha đăng nhập (không có body).
- Credential không có trong `interactions.jsonl`, `state.json`, `report.json` (đã kiểm bằng test tự động và bằng mắt).

## Làm mờ dữ liệu cá nhân
- `contact-sheet.png`: 16 frame; `still-header-blurred.png`: crop header ở giây 17,5 — email người dùng, avatar và «Support line»
  (số điện thoại) bị làm mờ, chữ còn lại sắc nét.
- Test tự động so mức cạnh (FIND_EDGES) của vùng email có/không làm mờ (`tests/test_login_privacy.py`).

## Ghi chú
- `storage_state.json` vẫn nằm trong thư mục job của lần chạy CLI này (script chạy `run_job` trực tiếp, không qua worker web).
  Khi chạy qua API, worker xóa `storage_state.json`, `credentials.enc`, `login_profile/` khi job kết thúc; CLI chỉ xóa `credentials.enc`.
- Cách A (cửa sổ trình duyệt thật) cần người gõ: xem `docs/manual-test-login.md`.
