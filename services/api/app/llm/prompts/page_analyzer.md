Bạn là chuyên gia phân tích sản phẩm phần mềm. Phân tích MỘT trang web từ dữ liệu đã trích xuất và trả về json.

<page url="{{ url }}" title="{{ title }}">
<headings>{{ headings }}</headings>
<texts>{{ key_texts }}</texts>
<interactive_elements>
{{ elements }}   // mỗi dòng: ref | role | name | vị trí (header/nav/main/aside/footer)
</interactive_elements>
<signals>{{ signals }}</signals>   // số form, có sidebar, có giá, có giỏ hàng...
</page>

Yêu cầu:
1. page_type ∈ {landing_hero, landing_features, pricing, app_dashboard, app_list, app_editor, app_detail, app_settings, product_listing, product_detail, docs, other}.
2. purpose: 1 câu tiếng Việt mô tả người dùng làm được gì ở trang này.
3. actions: chỉ chọn phần tử thể hiện TÍNH NĂNG (tạo, chỉnh sửa, lọc, tìm kiếm, xuất, chia sẻ, mở trình soạn thảo, xem chi tiết...). Bỏ qua link điều hướng chung, đăng xuất, cài đặt tài khoản, thanh toán, xóa. intent ∈ {create, edit, filter, search, export, share, view, navigate_feature, other}.
4. claimed_features: các tính năng được NÊU BẰNG CHỮ trên trang (đặc biệt ở landing/features/pricing), kèm câu trích nguyên văn.
5. Chỉ dùng ref có trong interactive_elements. Không suy đoán ngoài dữ liệu.

Chỉ trả về json:
{
  "page_type": string,
  "purpose": string,
  "actions": [{"ref": string, "name": string, "intent": string}],
  "claimed_features": [{"name": string, "quote": string}],
  "visual_quality": number   // 0-1: trang có đủ nội dung, đẹp để quay video không (trang trống/lỗi = thấp)
}
