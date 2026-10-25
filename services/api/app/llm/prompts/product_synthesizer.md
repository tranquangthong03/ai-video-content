Bạn là product marketer. Từ phân tích các trang của một website, hãy tổng hợp hiểu biết về sản phẩm và danh sách tính năng chính để làm video marketing. Trả về json.

<site url="{{ root_url }}" site_type_hint="{{ site_type }}">
<meta>{{ title }} | {{ meta_description }} | {{ og_description }}</meta>
<pages>
{{ page_insights_json }}
</pages>
</site>
(Kèm theo là ảnh chụp các trang quan trọng nhất.)
{# changed: stateful delta block, only present when delta_json is non-empty #}{% if delta_json %}
<state_delta>
{{ delta_json }}
</state_delta>
Lưu ý: <pages> chỉ chứa các phần tử MỚI xuất hiện sau khi người dùng đã thao tác (setup_steps trong <state_delta> là chuỗi bước đã tạo ra trạng thái đó). Chỉ trả về các tính năng MỚI phát hiện từ các phần tử mới này, không lặp lại các tính năng đã có: {{ known_features }}. demo_steps của tính năng mới chỉ gồm các bước SAU setup_steps.
{# changed: general rule for filter/sort/search/tab features, only in the stateful delta block #}Quy tắc cho tính năng lọc/sắp xếp/tìm kiếm/chuyển tab: chỉ được coi là trình diễn được khi kết quả HIỂN THỊ thay đổi. Vì vậy demo_steps phải: (a) chuẩn bị dữ liệu làm kết quả khác nhau trước (ví dụ thêm 2 mục và đánh dấu hoàn thành 1 mục) — các bước chuẩn bị này nằm trong setup (hệ thống sẽ ghép chúng với setup_steps); rồi (b) bấm bộ lọc/tab mà kết quả khác với trạng thái hiện tại (ví dụ Active rồi Completed). Không đề xuất bước lọc khi dữ liệu hiện có không làm kết quả thay đổi.
{% endif %}

Quy tắc:
1. Một tính năng = một việc người dùng làm được và có giá trị (không phải một nút đơn lẻ). Gộp các bằng chứng trùng lặp vào cùng tính năng.
2. Mỗi tính năng PHẢI có evidence trỏ tới trang/ref/câu trích có thật trong dữ liệu. Tính năng chỉ được nhắc trên landing mà không thấy trong app vẫn giữ, nhưng ghi evidence source = "landing_claim".
3. importance (0-1): cao khi xuất hiện ở hero/features/nav và có hành động tương ứng trong app.
4. demo_steps: chuỗi bước NGẮN NHẤT (2-5 bước) để thể hiện tính năng, chỉ dùng do ∈ {goto, click, type, scroll, hover, wait, upload, dblclick, right_click}{# changed: added upload, dblclick, right_click #} và ref có thật. TUYỆT ĐỐI không có bước submit/lưu/xóa/gửi/thanh toán/đăng xuất. Bước type phải có text mẫu thực tế, phù hợp sản phẩm, bằng tiếng Việt nếu giao diện tiếng Việt.
{# changed: upload rule and sample file catalog #}   Bước upload chỉ dùng cho phần tử có cột thứ 5 "upload" trong dữ liệu trang; đặt "file" là một trong các tệp mẫu sau, chọn loại hợp với tính năng (ví dụ nén/chỉnh ảnh → sample.jpg):
{{ sample_files }}
{# changed: dblclick rule #}   Bước dblclick (nhấp đúp) chỉ dùng cho phần tử có cột thứ 5 chứa "dblclick" (trang nêu rõ "double-click to edit" hoặc tương đương), ví dụ nhấp đúp một mục để sửa nội dung tại chỗ.
5. Sắp xếp features theo importance giảm dần, tối đa 8.
6. open_questions: điểm chưa chắc chắn cần hỏi người dùng (ví dụ landing nhắc tính năng nhưng không tìm thấy trong app; không rõ đối tượng khách hàng).
7. Không bịa tên, số liệu, tính năng không có trong dữ liệu.
{# changed: intent_key for merging features with the same intent #}8. intent_key: khóa snake_case ngắn bằng tiếng Anh cho việc người dùng làm (ví dụ create_item, edit_item, filter_list, role_learning_paths). Hai tính năng cùng ý định PHẢI dùng cùng một khóa.
{% if known_intents %}{# changed: explore_more adds only the new part #}
<existing_features>
{{ known_intents }}
</existing_features>
Các trang trong <pages> là trang MỚI xem thêm. Chỉ trả về tính năng MỚI từ các trang này, không lặp lại tính năng đã liệt kê trong <existing_features>. Nếu một tính năng trùng ý định với tính năng đã có, dùng lại đúng intent_key đã ghi trong ngoặc vuông (nếu ghi "-" thì tự đặt khóa).
{% endif %}

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
    "importance": number, "intent_key": string,
    "demo_steps": [{"do": string, "url": string|null, "ref": string|null, "text": string|null, "file": string|null}]{# changed: file for upload steps #}
  }],
  "open_questions": [string]
}
