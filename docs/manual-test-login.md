# Kiểm thử thủ công: đăng nhập bằng cửa sổ trình duyệt (cách A)

Cách A mở một cửa sổ Chromium thật **trên máy chạy API**, nên chỉ dùng được khi API chạy cùng máy với bạn
(bản demo local). Các cách B (tài khoản demo) và C (file auth.json) có test tự động; cách A cần người thật gõ,
nên bạn tự kiểm thử theo các bước dưới đây trên một site thật có tài khoản demo.

## Chuẩn bị
1. Có một site thật có đăng nhập và **một tài khoản demo** (không dùng tài khoản có dữ liệu quan trọng).
   Ghi lại: địa chỉ landing (public), địa chỉ trang đăng nhập (nếu biết), email + mật khẩu demo.
2. `.env` có `DEEPSEEK_API_KEY`. Nên đặt `CREDENTIAL_ENCRYPTION_KEY` (sinh bằng
   `uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).
3. Chạy hệ thống: `pnpm dev:all` (API cổng 8000, web cổng 3000). Không đặt `LOGIN_BROWSER_HEADLESS=1`
   (biến này chỉ dành cho test: nó mở cửa sổ ở chế độ ẩn).

## Kịch bản 1: người dùng báo trước «tính năng chính nằm sau đăng nhập»
1. Mở http://localhost:3000, nhập URL **landing** của site, **tick «Tính năng chính nằm sau đăng nhập»**, bấm «Tạo video».
2. Thẻ **«Cần đăng nhập»** hiện ngay đầu job. Dòng «Trang đăng nhập: …» là link «Log in / Đăng nhập» mà hệ thống tìm được.
   Nếu không tìm thấy, thẻ có ô «Địa chỉ trang đăng nhập»: dán địa chỉ rồi bấm «Dùng địa chỉ này».
3. Tab **«Mở cửa sổ đăng nhập»** (mặc định): bấm nút cùng tên → một cửa sổ Chromium 1280×800 hiện ra ở trang đăng nhập;
   web hiện «Cửa sổ đăng nhập đang mở.».
4. Đăng nhập trong cửa sổ đó như bình thường (có thể có 2FA, captcha, «Đăng nhập với Google»).
   Đợi tới khi thấy trang chính của app.
5. Quay lại web, bấm **«Tôi đã đăng nhập xong»**. Cửa sổ tự đóng; web hiện «Đang kiểm tra phiên đăng nhập…».
6. **Kỳ vọng:** job chuyển sang «Khám phá»; trang bắt đầu khám phá là trang chính của app (không phải landing).
   Xem `out/jobs/<id>/explore/report.json`: `pages_seen` bắt đầu từ URL của app, `sensitive_skipped` liệt kê các trang
   settings/billing... đã bỏ qua.

## Kịch bản 2: chưa đăng nhập đã bấm «xong» (kiểm tra thông báo lỗi)
1. Làm lại bước 1–3, nhưng bấm «Tôi đã đăng nhập xong» **mà chưa đăng nhập**.
2. **Kỳ vọng:** thẻ vẫn hiện, dòng đỏ «Chưa vào được trang bên trong, vui lòng thử lại.»; mở lại cửa sổ và làm tiếp được.

## Kịch bản 3: quá 10 phút
1. Mở cửa sổ đăng nhập rồi để đó hơn 10 phút.
2. **Kỳ vọng:** cửa sổ tự đóng; bấm «Tôi đã đăng nhập xong» báo «Cửa sổ đăng nhập đã đóng vì quá 10 phút», bấm «Mở lại cửa sổ».

## Kịch bản 4: hủy job
1. Mở cửa sổ đăng nhập, rồi bấm «Hủy» ở góc phải trên cùng.
2. **Kỳ vọng:** cửa sổ đóng ngay, job «Đã hủy».

## Kịch bản 5: phiên hết hạn giữa chừng
1. Chạy một job đã đăng nhập; trong lúc đang «Sản xuất» (quay), đăng xuất tài khoản demo từ trình duyệt khác
   (hoặc xóa phiên phía server nếu site cho phép).
2. **Kỳ vọng:** job dừng ở scene đang quay và hiện lại thẻ «Cần đăng nhập — Phiên đăng nhập đã hết hạn.»; đăng nhập xong thì
   chỉ **scene đó** được quay lại (các scene trước không quay lại). Nếu đã dùng cách B (tài khoản demo), hệ thống tự đăng nhập lại
   mà không hỏi.

## Kiểm tra riêng tư sau khi job xong
- Xem video: email, số điện thoại, avatar/menu tài khoản ở header phải bị làm mờ.
- `out/jobs/<id>/` **không còn** `storage_state.json`, `credentials.enc`, `login_profile/` (xóa khi job kết thúc).
- `interactions.jsonl`, `state.json`, `report.json` không chứa mật khẩu/email đăng nhập.
- Trình duyệt không truy cập được `http://localhost:8000/api/jobs/<id>/files/storage_state.json` (404).

## Ghi lại kết quả
Với mỗi kịch bản ghi: đạt / không đạt, URL site, và (nếu không đạt) ảnh chụp thẻ + đoạn cuối `out/jobs/<id>/error.log`
(nếu có). Gửi lại để chỉnh.
