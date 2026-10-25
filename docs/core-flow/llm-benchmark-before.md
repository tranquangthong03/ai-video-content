# Benchmark Flow Agent (chỉ DeepSeek)

Agent chạy không quay video; cache LLM tắt; mỗi ô là số lần đạt / số lần chạy. «Đạt» = luồng thật sự tới đích (`stopped_before_submit` đúng nút Apply, hoặc todomvc: ≥ 3 lần gõ, 1 lần tích, bấm Active), không chỉ agent tự báo.

| Luồng | Cấu hình | Đạt | Hành động TB | Gọi LLM TB | Cảnh báo lặp | Ref bịa | Giây TB | Token TB |
|---|---|---|---|---|---|---|---|---|
| fixture | text | 3/3 | 8.0 | 9.0 | 0 | 0 | 21.5 | 14130 |
| fixture | vision | 3/3 | 9.7 | 10.3 | 0 | 0 | 29.8 | 24493 |
| orangehrm | text | 1/3 | 11.0 | 11.7 | 2 | 0 | 34.0 | 22475 |
| orangehrm | vision | 1/3 | 10.3 | 10.0 | 4 | 0 | 52.4 | 28903 |
| todomvc | text | 3/3 | 5.0 | 6.0 | 0 | 0 | 15.1 | 10389 |
| todomvc | vision | 3/3 | 5.0 | 6.0 | 0 | 0 | 19.2 | 15024 |
| tổng | text | 7/9 | 8.0 | 8.9 | 2 | 0 | 23.5 | 15665 |
| tổng | vision | 7/9 | 8.3 | 8.8 | 4 | 0 | 33.8 | 22807 |

## Các bước agent hay kẹt nhất

**text**

- select «Reason category» — 3 lần chạy — select: không thấy lựa chọn «Personal» sau khi mở danh sách
- select «yyyy-dd-mm» — 1 lần chạy — select: không thấy lựa chọn «Annual Leave» sau khi mở danh sách
- Dừng: «pick_date:yyyy-dd-mm» lặp N lần mà trang không đổi. — 1 lần chạy — Dừng: «pick_date:yyyy-dd-mm» lặp 3 lần mà trang không đổi.
- Dừng: đã đủ N hành động. — 1 lần chạy — Dừng: đã đủ 15 hành động.
- pick_date «yyyy-dd-mm» — 1 lần chạy — pick_date: không có nút chuyển tháng trên lịch

**vision**

- select «Reason category» — 3 lần chạy — select: không thấy lựa chọn «Personal» sau khi mở danh sách
- Dừng: «scroll:» lặp N lần mà trang không đổi. — 2 lần chạy — Dừng: «scroll:» lặp 3 lần mà trang không đổi.

## Trạng thái cuối

| Luồng | Cấu hình | Trạng thái | Số lần |
|---|---|---|---|
| fixture | text | stopped_before_submit | 3 |
| fixture | vision | stopped_before_submit | 3 |
| orangehrm | text | partial | 2 |
| orangehrm | text | stopped_before_submit | 1 |
| orangehrm | vision | partial | 2 |
| orangehrm | vision | stopped_before_submit | 1 |
| todomvc | text | reached_goal | 3 |
| todomvc | vision | reached_goal | 3 |


