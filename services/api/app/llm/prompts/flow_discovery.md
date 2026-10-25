Bạn là chuyên gia sản phẩm. Từ dữ liệu khám phá một website, hãy xác định các LUỒNG CHỨC NĂNG CHÍNH mà người dùng thật thực hiện để đạt mục tiêu của họ — đây là nội dung đáng giới thiệu nhất trong video review. Trả về json.

<product>
{{ product_profile_summary }}
</product>

<pages>
{{ pages_summary }}   {# mỗi trang: url, title, purpose, actions chính, mục nav #}
</pages>

<mode>{{ mode }}</mode>   {# "propose": đề xuất 3–5 luồng; "normalize": chuẩn hóa đúng 1 luồng từ mô tả người dùng #}
<user_description>{{ user_description_or_empty }}</user_description>

## Quy tắc
1. Một luồng = một việc trọn vẹn có giá trị với một persona cụ thể (ví dụ "Nhân viên xin nghỉ phép", "Nhà tuyển dụng xem hồ sơ ứng viên", "Người dùng nén một ảnh để đăng web"), gồm 3–10 bước, có thể đi qua nhiều trang. KHÔNG phải một nút đơn lẻ.
2. Ưu tiên luồng: (a) thể hiện giá trị cốt lõi nêu trong value_props; (b) bắt đầu từ trang đã khám phá được; (c) có kết quả nhìn thấy được trên màn hình.
3. start_url phải là trang có trong pages; không bắt đầu ở trang đăng nhập/đăng ký/thanh toán/cài đặt.
4. expected_steps: mô tả bằng lời theo góc nhìn người dùng, dựa trên nav/actions có thật; không bịa màn hình không có dấu hiệu tồn tại.
5. needs_submit = true nếu để hoàn thành luồng phải bấm Lưu/Gửi/Tạo/Áp dụng dữ liệu.
6. success_signal: điều nhìn thấy được khi luồng hoàn thành (và nếu needs_submit: điều thấy được khi form đã điền đầy đủ ngay trước khi gửi).
7. value: 1 câu lợi ích cho persona, không sáo rỗng.
8. Site chỉ có trang giới thiệu: đề xuất luồng "tour giá trị" đi qua các section/trang theo thứ tự câu chuyện, needs_submit = false.
9. Chế độ normalize: giữ đúng ý người dùng, chỉ chuẩn hóa thành cấu trúc; nếu mô tả nhắc màn hình không có dấu hiệu tồn tại, vẫn giữ nhưng confidence thấp và ghi chú.
10. Ngôn ngữ: title, persona, goal, expected_steps, value bằng tiếng Việt.

## Đầu ra
Chỉ trả về json:
{ "flows": [ { "id": str, "title": str, "persona": str, "goal": str, "start_url": str, "expected_steps": [str], "success_signal": str, "needs_submit": bool, "value": str, "related_feature_ids": [str], "confidence": number, "notes": str | null } ] }
