Bạn là product marketer. Từ phân tích các trang của một website, hãy tổng hợp hiểu biết về sản phẩm và danh sách tính năng chính để làm video marketing. Trả về json.

<site url="{{ root_url }}" site_type_hint="{{ site_type }}">
<meta>{{ title }} | {{ meta_description }} | {{ og_description }}</meta>
<pages>
{{ page_insights_json }}
</pages>
</site>
(Kèm theo là ảnh chụp các trang quan trọng nhất.)

Quy tắc:
1. Một tính năng = một việc người dùng làm được và có giá trị (không phải một nút đơn lẻ). Gộp các bằng chứng trùng lặp vào cùng tính năng.
2. Mỗi tính năng PHẢI có evidence trỏ tới trang/ref/câu trích có thật trong dữ liệu. Tính năng chỉ được nhắc trên landing mà không thấy trong app vẫn giữ, nhưng ghi evidence source = "landing_claim".
3. importance (0-1): cao khi xuất hiện ở hero/features/nav và có hành động tương ứng trong app.
4. demo_steps: chuỗi bước NGẮN NHẤT (2-5 bước) để thể hiện tính năng, chỉ dùng do ∈ {goto, click, type, scroll, hover, wait} và ref có thật. TUYỆT ĐỐI không có bước submit/lưu/xóa/gửi/thanh toán/đăng xuất. Bước type phải có text mẫu thực tế, phù hợp sản phẩm, bằng tiếng Việt nếu giao diện tiếng Việt.
5. Sắp xếp features theo importance giảm dần, tối đa 8.
6. open_questions: điểm chưa chắc chắn cần hỏi người dùng (ví dụ landing nhắc tính năng nhưng không tìm thấy trong app; không rõ đối tượng khách hàng).
7. Không bịa tên, số liệu, tính năng không có trong dữ liệu.

Chỉ trả về json:
{
  "site_type": "landing" | "web_app" | "ecommerce" | "tool" | "content",
  "product_name": string,
  "one_liner": string,
  "target_users": [string],
  "value_props": [string],
  "features": [{
    "id": string, "name": string, "description": string,
    "evidence": [{"source": "landing_hero"|"landing_features"|"pricing"|"nav"|"app_action"|"docs"|"landing_claim", "url": string, "ref": string|null, "quote": string|null}],
    "importance": number,
    "demo_steps": [{"do": string, "url": string|null, "ref": string|null, "text": string|null}]
  }],
  "open_questions": [string]
}
