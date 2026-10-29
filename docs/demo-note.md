## Test live: https://www.demoblaze.com — 2026-10-28
| Bước | Đạt? | Ghi chú |
|---|---|---|
| Luồng được chọn | ❌ | Mô tả "thêm vào giỏ" nhưng storyboard ra luồng "Xem chi tiết một sản phẩm" |
| Ảnh storyboard | ❌ | Bước 2 trang chi tiết sản phẩm bị TRẮNG — chụp trước khi nội dung tải bằng JS xong |
| Logic luồng | ❌ | Xem sản phẩm → quay lại trang chủ → chọn danh mục; bước 4 không đổi gì trên màn hình |
| Đánh giá mục tiêu | ❌ | Nhãn "Đạt mục tiêu" dù không có Add to cart; cảnh báo stop_before_submit dùng sai ref |
| Sửa bằng một câu | ? | (ghi kết quả sau khi chạy lại) |
| Hộp thoại "Product added" | ? | (agent xử lý được / bị kẹt) |

## Test live: https://www.demoblaze.com — lần 2 (sửa bằng câu)
| Bước | Đạt? | Ghi chú |
|---|---|---|
| Sửa luồng bằng câu | ❌ | Yêu cầu làm lại luồng khác nhưng hệ thống "giữ 4 bước đầu" sai cũ |
| Trang chi tiết sản phẩm | ❌ | LUÔN trắng (bước 2, 5, 12–14), kể cả sau khi chờ/cuộn — trang không tải được nội dung |
| Lọc danh mục | ❌ | Bấm Laptops nhưng danh sách vẫn là điện thoại |
| Nguyên nhân nghi ngờ | — | Demoblaze lấy dữ liệu bằng POST tới api.demoblaze.com (view, bycat); request guard chặn POST → trang trống. Hệ thống không cảnh báo người dùng |
| Agent | ❌ | Đi vòng 15 hành động rồi dừng; tự nhận "trang chi tiết đang trắng" nhưng không báo lỗi môi trường |
| Giao diện | ❌ | Gợi ý sửa storyboard là ví dụ cứng của OrangeHRM ("Chọn loại nghỉ Annual…", "Thêm bước xem My Leave") |
| Cảnh báo "Chỉ điều hướng" | ✅ | Hiện đúng |