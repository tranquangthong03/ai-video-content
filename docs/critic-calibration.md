# Hiệu chỉnh Copy Critic

Đọc từng kịch bản dưới đây như một người xem, rồi điền điểm của bạn (0–10, 10 là xuất sắc; ≥ 7 nghĩa là có thể đăng) vào cột «Điểm của bạn». Điểm của critic KHÔNG hiện ở đây. Điền xong chạy: `cd services/api && uv run python scripts/critic_calibration.py compare`.

Lượt này chỉ tạo file này; chưa đổi ngưỡng nào của critic.

## OrangeHRM — thêm nhân viên mới (`orangehrm`)

**Headline:** Tạo hồ sơ nhân viên mới trong 30 giây

- Phương án hook 1 (pain_question): Hồ sơ nhân viên mới lạc giữa giấy tờ và bảng tính? — chữ trên màn hình: «Hồ sơ lạc giữa giấy?»
- Phương án hook 2 (result_first): Đưa người mới vào hệ thống nhân sự chỉ vài cú nhấp. — chữ trên màn hình: «Vài cú nhấp»

1. **HOOK** — Hồ sơ nhân viên mới lạc giữa giấy tờ và bảng tính?
   _(chữ trên màn hình: «Hồ sơ lạc giữa giấy?»)_
2. **Chương 1** — Mở PIM, bấm Add. Toàn bộ thông tin nhân viên mới nằm gọn trong một bảng điều khiển tập trung.
   _(chữ trên màn hình: «Mở PIM, bấm Add»)_
3. **Chương 2** — Gõ First Name, rồi Middle Name Văn một lần. Hệ thống lưu lại, lần sau không phải nhập lại.
   _(chữ trên màn hình: «Nhập một lần, dùng mãi»)_
4. **Chương 3** — Form đã đủ họ tên và mã nhân viên, chỉ một cú bấm Save là xong.
   _(chữ trên màn hình: «Sẵn sàng Save»)_
5. **CTA** — Đưa người mới vào hệ thống nhân sự tập trung, hết giấy tờ rời rạc. Dùng thử miễn phí ngay.
   _(chữ trên màn hình: «Dùng thử ngay»)_

| Tiêu chí | Câu hỏi | Điểm của bạn |
|---|---|---|
| hook_strength | 12 từ đầu có khiến người xem dừng lướt không? | |
| benefit_clarity | mỗi chương nói rõ họ ĐƯỢC GÌ, không chỉ kể thao tác? | |
| proof_usage | dùng số liệu / câu trích / ưu đãi thật một cách tự nhiên? (để trống nếu không có gì để dùng) | |
| cta_strength | hành động cụ thể + lý do làm ngay + dễ nhớ? | |
| flow | mạch kể liền: nỗi đau → hành trình → kết quả, nhịp ngắn gọn? | |

## Squoosh — nén và so sánh ảnh (`squoosh`)

**Headline:** Nén ảnh 2.8MB và thấy khác biệt ngay

- Phương án hook 1 (pain_question): Ảnh 2.8MB làm trang tải chậm, nén xuống vẫn nét được không? — chữ trên màn hình: «2.8MB quá nặng?»
- Phương án hook 2 (result_first): Chọn ảnh mẫu, hạ chất lượng, thấy ngay ảnh nhẹ hơn. — chữ trên màn hình: «Nhẹ hơn trong 30 giây»

1. **HOOK** — Ảnh 2.8MB làm trang tải chậm, nén xuống vẫn nét được không?
   _(chữ trên màn hình: «2.8MB quá nặng?»)_
2. **Chương 1** — Bạn chỉ cần mở trình duyệt và chọn ảnh mẫu 2.8MB có sẵn, không cần cài đặt gì thêm.
   _(chữ trên màn hình: «Chọn ảnh mẫu»; số nổi: 2.8MB ảnh mẫu ban đầu)_
3. **Chương 2** — Hạ chất lượng xuống 50, bạn thấy ngay dung lượng giảm mà vẫn đủ nét, rồi lưu ảnh đã nén về máy.
   _(chữ trên màn hình: «Chất lượng 50»; số nổi: 50 mức chất lượng nén)_
4. **CTA** — Mở squoosh.app, thử nén ảnh mẫu ngay trên máy bạn và tự tin chọn mức nén phù hợp.
   _(chữ trên màn hình: «Thử tại squoosh.app»)_

| Tiêu chí | Câu hỏi | Điểm của bạn |
|---|---|---|
| hook_strength | 12 từ đầu có khiến người xem dừng lướt không? | |
| benefit_clarity | mỗi chương nói rõ họ ĐƯỢC GÌ, không chỉ kể thao tác? | |
| proof_usage | dùng số liệu / câu trích / ưu đãi thật một cách tự nhiên? (để trống nếu không có gì để dùng) | |
| cta_strength | hành động cụ thể + lý do làm ngay + dễ nhớ? | |
| flow | mạch kể liền: nỗi đau → hành trình → kết quả, nhịp ngắn gọn? | |

## TodoMVC — lên danh sách việc (`todomvc`)

**Headline:** Lên việc trong ngày, lọc việc còn lại

- Phương án hook 1 (pain_question): Bạn có đang quên việc cần làm mỗi ngày? — chữ trên màn hình: «Quên việc mỗi ngày?»
- Phương án hook 2 (you_are_doing_it_wrong): Đừng ghi việc lên giấy nữa, thử cách này xem. — chữ trên màn hình: «Ghi giấy lộn xộn?»

1. **HOOK** — Đừng ghi việc lên giấy nữa, thử cách này xem.
   _(chữ trên màn hình: «Ghi giấy lộn xộn?»)_
2. **Chương 1** — Mở trang là thêm ngay việc đầu tiên, không cần tài khoản.
   _(chữ trên màn hình: «Thêm việc tức thì»)_
3. **Chương 2** — Gõ thêm hai việc nữa, danh sách tự cập nhật ngay tại dòng nhập.
   _(chữ trên màn hình: «Thêm nhanh hai việc»)_
4. **Chương 3** — Đánh dấu xong việc Mua sữa, bạn thấy ngay một việc đã hoàn thành.
   _(chữ trên màn hình: «Xong một việc»)_
5. **Chương 4** — Chọn lọc Active, chỉ còn hai việc chưa làm hiện ra, tập trung liền.
   _(chữ trên màn hình: «Chỉ xem việc còn lại»; số nổi: 2 việc còn lại)_
6. **CTA** — Lập danh sách việc trong ngày ngay tại todomvc.com, không cần đăng ký.
   _(chữ trên màn hình: «todomvc.com»)_

| Tiêu chí | Câu hỏi | Điểm của bạn |
|---|---|---|
| hook_strength | 12 từ đầu có khiến người xem dừng lướt không? | |
| benefit_clarity | mỗi chương nói rõ họ ĐƯỢC GÌ, không chỉ kể thao tác? | |
| proof_usage | dùng số liệu / câu trích / ưu đãi thật một cách tự nhiên? (để trống nếu không có gì để dùng) | |
| cta_strength | hành động cụ thể + lý do làm ngay + dễ nhớ? | |
| flow | mạch kể liền: nỗi đau → hành trình → kết quả, nhịp ngắn gọn? | |
