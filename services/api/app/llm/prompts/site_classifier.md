Phân loại một website theo dữ liệu đã trích xuất từ trang đầu tiên. Trả về json.

<page url="{{ url }}" title="{{ title }}">
<meta>{{ meta_description }}</meta>
<headings>{{ headings }}</headings>
<signals>{{ signals }}</signals>
<heuristic_guess>{{ heuristic }}</heuristic_guess>
</page>

site_type ∈ {landing, web_app, ecommerce, tool, content}:
- landing: trang giới thiệu/tiếp thị một sản phẩm, nhiều section, ít thao tác trực tiếp.
- web_app: ứng dụng nhiều chức năng, có điều hướng/sidebar, thao tác trên dữ liệu.
- ecommerce: bán hàng, có giá và giỏ hàng.
- tool: công cụ một mục đích (một ô nhập/thả file lớn hoặc vùng làm việc chính).
- content: blog, tài liệu, tin tức.

Chỉ trả về json:
{"site_type": string, "reason": string}
