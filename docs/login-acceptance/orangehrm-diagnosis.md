# Chẩn đoán: video OrangeHRM chỉ quay trang đăng nhập

Dữ liệu: job web `services/api/out/jobs/j19fef18f81` (video 37 s, 6 scene) và job `j295be50431` (lần chạy trước, thất bại ở bước script).
Site: https://opensource-demo.orangehrmlive.com (Admin / admin123).

## Dòng thời gian của job j19fef18f81 (giờ máy, từ mtime của file)
| Giờ | Việc |
|---|---|
| 13:16:51 | job tạo (`state.json: created_at`) |
| ~13:20 | khám phá xong (`explore/map.json` 13:20:49); `pages_seen` = `/web/index.php/dashboard/index` ⇒ **explore đã đăng nhập thành công** |
| 13:26–13:27 | xác nhận / chọn tính năng / chọn hướng / duyệt dàn ý |
| 13:28:24 | duyệt kịch bản (lần duy nhất trong `interactions.jsonl`) |
| 13:28:30–13:30:50 | quay + render. Mọi ảnh chụp/clip là trang Login |

`job.json` của job: `{"storage_state": "storage_state.json", "resume": true, "from_step": "script"}` — nghĩa là phần script/produce là một lần **chạy tiếp** («Chạy tiếp»), không phải lần chạy đầu.

## Kết quả theo từng câu hỏi
1. **storage_state.json lúc bắt đầu produce?** KHÔNG còn. Cả hai thư mục job (`j19fef18f81`, `j295be50431`) không có `storage_state.json`
   dù `job.json` vẫn trỏ tới nó. `j295be50431` (thất bại ở script, `Không viết được kịch bản hợp lệ: badge dài 25 ký tự`) cũng không còn file.
   Nguyên nhân: `JobRunner._run` (commit L5) gọi `cleanup_job_secrets()` trong `finally` cho **mọi** kết thúc kể cả `failed`. Lần chạy đầu
   thất bại ở bước script (lỗi 1) → phiên bị xóa → «Chạy tiếp» không còn phiên.
2. **Recorder nhận đúng đường dẫn không?** Không có đường dẫn để nhận: `JobRunner._run` chỉ đặt `cfg.storage_state` khi file tồn tại
   (`directory / auth if auth and (directory / auth).is_file() else None`) ⇒ `None` ⇒ `BrowserSession(storage_state=None)` ⇒
   `_Recorder.authenticated = False`.
3. **Cookie / thời hạn.** Thử trực tiếp bây giờ với đúng site: phiên là cookie phiên `orangehrm` (`expires = -1`, httpOnly),
   được `storage_state` lưu; mở lại `/web/index.php/dashboard/index` bằng file đó ngay sau khi đăng nhập **vào được** (15 s sau đăng nhập).
   Hạn phía máy chủ chưa đo (sẽ đo ở bước nghiệm thu: chờ ≥ 6 phút rồi mở lại). Khoảng từ lúc đăng nhập tới lúc quay scene đầu của job này
   ≈ 12 phút, nhưng điều đó không còn quan trọng vì file đã bị xóa trước đó.
4. **Recorder có phát hiện bị đẩy về login không?** Không. Phát hiện chỉ chạy khi `authenticated` (có phiên). Không có phiên ⇒ `check_login` bỏ qua,
   cảnh quay trang Login như bình thường, không có `LoginRequired`, không có cảnh báo; cũng không có lớp chặn nào ở cuối nên video vẫn được xuất.

## Nguyên nhân gốc (một chuỗi)
- **Phiên bị xóa sớm** (lỗi do commit L5: dọn bí mật ở cả `failed`), kích hoạt bởi lỗi 1 (script thất bại vì độ dài badge).
- **Không truyền phiên** vào lần chạy tiếp (hệ quả).
- **Không phát hiện / không chặn** khi quay trang login lúc job không giữ phiên: thiếu kiểm tra phiên trước khi quay và thiếu quality gate.
- Không phải do phiên hết hạn phía máy chủ (chưa có bằng chứng; sẽ kiểm ở nghiệm thu).

## Hai phát hiện thêm trong dữ liệu
- **Bug cách B (đăng nhập bằng tài khoản demo) trên OrangeHRM:** `perform_login(Admin, admin123)` báo `wrong_credentials` dù đăng nhập thành công
  (cookie có, mở lại dashboard vào được). Lý do: sau khi bấm Login trang SPA chuyển URL chậm hơn thời gian chờ `wait_for_settle` nên
  `signed_in()` còn thấy URL `/auth/login`. Cần chờ chuyển trang (URL rời path login hoặc ô password biến mất) trước khi kết luận.
- **Scene không có bước chạy được:** 3/6 scene (s2–s4) ra «không bước nào chạy được, dùng ảnh trang đích thay cho clip». Các bước `hover` nhắm vào
  chữ tiếng Việt rời rạc («khiển», «bảng») trên trang tiếng Anh nên không tìm thấy phần tử. Đây là lỗi độc lập với đăng nhập (chọn đích showcase),
  sẽ thấy rõ ngay khi phiên được sửa; sẽ kiểm ở nghiệm thu và báo riêng nếu còn.
