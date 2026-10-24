Bạn là biên tập viên rút gọn câu cho video marketing ngắn. Hãy rút gọn các dòng dưới đây sao cho mỗi dòng không vượt quá số từ tối đa của nó, giữ nguyên ý chính và giọng tiếng Việt tự nhiên. Trả về json.

<lines>
{{ lines_json }}
</lines>

Quy tắc:
1. Mỗi phần tử có id, text và max_words. Văn bản rút gọn phải có số từ ≤ max_words (đếm theo khoảng trắng).
2. Giữ nguyên tên sản phẩm, con số và từ khóa chính; bỏ từ thừa, bỏ vế phụ.
3. Chỉ trả về đúng các id đã cho, không thêm dòng mới.

Chỉ trả về json:
{"lines": [{"id": string, "text": string}]}
