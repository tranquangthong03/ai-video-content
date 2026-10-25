# Benchmark Flow Agent (chỉ DeepSeek)

Agent chạy không quay video; cache LLM tắt; mỗi ô là số lần đạt / số lần chạy. «Đạt» = luồng thật sự tới đích (`stopped_before_submit` đúng nút Apply, hoặc todomvc: ≥ 3 lần gõ, 1 lần tích, bấm Active), không chỉ agent tự báo.

| Luồng | Cấu hình | Đạt | Hành động TB | Gọi LLM TB | Cảnh báo lặp | Ref bịa | Giây TB | Token TB |
|---|---|---|---|---|---|---|---|---|
| fixture | text | 3/3 | 8.0 | 8.3 | 0 | 0 | 19.7 | 12954 |
| fixture | vision | 3/3 | 8.0 | 8.0 | 0 | 0 | 23.8 | 18521 |
| orangehrm | text | 0/3 | 5.3 | 6.0 | 3 | 0 | 33.9 | 10176 |
| orangehrm | vision | 0/3 | 2.7 | 3.7 | 0 | 0 | 25.1 | 9285 |
| todomvc | text | 3/3 | 5.0 | 6.0 | 0 | 0 | 13.3 | 10431 |
| todomvc | vision | 3/3 | 5.0 | 6.0 | 0 | 0 | 16.4 | 14894 |
| tổng | text | 6/9 | 6.1 | 6.8 | 3 | 0 | 22.3 | 11187 |
| tổng | vision | 6/9 | 5.2 | 5.9 | 0 | 0 | 21.8 | 14233 |

## Các bước agent hay kẹt nhất

**text**

- select «Reason category» — 3 lần chạy — select: không thấy lựa chọn «Personal Leave» (có: Family, Medical, Travel)
- Dừng: «click:Apply» lặp N lần mà trang không đổi. — 2 lần chạy — Dừng: «click:Apply» lặp 3 lần mà trang không đổi.
- type «To Date» — 1 lần chạy — lỗi trình duyệt: Locator.fill: Timeout 4000ms exceeded.
- Agent bỏ cuộc: Trang Apply Leave không hiển thị form nhập liệu nào (ch — 1 lần chạy — Agent bỏ cuộc: Trang Apply Leave không hiển thị form nhập liệu nào (chỉ có nav); các nút Apply đã click 2 lần đều không đổi trang nên không 
- select «Leave» — 1 lần chạy — select: đã bấm «Apply» nhưng ô vẫn hiện «Leave»

**vision**

- select «Reason category» — 3 lần chạy — select: không thấy lựa chọn «Personal» (có: Family, Medical, Travel)
- Agent bỏ cuộc: Trang Apply Leave hiển thị "No Leave Types with Leave B — 2 lần chạy — Agent bỏ cuộc: Trang Apply Leave hiển thị "No Leave Types with Leave Balance" — tài khoản demo không có loại nghỉ phép/không có số dư phép, 
- Agent bỏ cuộc: Trang Apply Leave chỉ hiển thị thông báo 'No Leave Type — 1 lần chạy — Agent bỏ cuộc: Trang Apply Leave chỉ hiển thị thông báo 'No Leave Types with Leave Balance', không có form chọn loại nghỉ / ngày / lý do để 

## Trạng thái cuối

| Luồng | Cấu hình | Trạng thái | Số lần |
|---|---|---|---|
| fixture | text | stopped_before_submit | 3 |
| fixture | vision | stopped_before_submit | 3 |
| orangehrm | text | partial | 3 |
| orangehrm | vision | partial | 3 |
| todomvc | text | reached_goal | 3 |
| todomvc | vision | reached_goal | 3 |

## Nhận xét

**Cách đọc.** Hai cấu hình: `text` = `deepseek-chat`, không ảnh; `vision` = `deepseek-flash` + ảnh viewport mỗi vòng. 3 luồng × 3 lần × 2 cấu hình,
cache LLM tắt, agent không quay video. Đây là vòng chạy **sau** các cải tiến ở dưới; vòng đầu (trước cải tiến) ở `llm-benchmark-before.md`
(cùng cấu hình: text 7/9, vision 7/9, token TB 15,7k / 22,8k, hành động TB 8,0 / 8,3).

**Kết quả chính.**
- Trên hai luồng làm được (fixture, todomvc) cả hai cấu hình đều **đạt 6/6**. Ảnh **không làm tăng tỉ lệ đạt**; nó tốn thêm khoảng
  **+43 % token** (fixture 18,5k so với 13,0k; todomvc 14,9k so với 10,4k) và **+20–25 % thời gian** (23,8 s so với 19,7 s; 16,4 s so với 13,3 s).
- OrangeHRM «xin nghỉ phép» **0/3 ở cả hai cấu hình**, nhưng lý do là **dữ liệu của site demo**, không phải model: trang Apply Leave báo
  «No Leave Types with Leave Balance» và không có form. Ở vòng đầu có 2/6 lượt «đạt» (agent dừng ở nút Apply mà chưa chọn được loại nghỉ):
  tiêu chí «đạt» cho luồng này chỉ kiểm dừng đúng nút Apply, **không kiểm các ô bắt buộc đã điền**, nên không phản ánh chất lượng thật.
- Điểm vision có ích: **nhận ra ngõ cụt sớm hơn**. Trên trang không có form, vision bỏ cuộc sau 3,7 lần gọi (0 cảnh báo lặp); text-only mất 6,0 lần gọi và
  lặp «bấm Apply» (3 cảnh báo lặp; 2 lượt bị dừng vì bấm Apply 3 lần mà trang không đổi).
- Không có ref bịa nào ở cả 18 + 18 lượt (cơ chế từ chối ref ngoài danh sách chưa phải kích hoạt).

**Các bước hay kẹt nhất và nguyên nhân** (xem bảng ở trên).
1. `select` trên dropdown tự vẽ («Reason category»): agent đoán một lựa chọn **không có** («Personal», «Personal Leave») trong cả 6/6 lượt fixture.
   Nguyên nhân: danh sách option chỉ hiện khi mở, mà agent chưa mở. Đã sửa: lỗi giờ liệt kê «có: Family, Medical, Travel» và đóng danh sách; mọi lượt sau đó tự sửa được.
2. Ô ngày của OrangeHRM có **cùng một tên** (placeholder «yyyy-dd-mm») → agent nhầm ô, sửa đi sửa lại tới 15 hành động, thậm chí dùng nhầm `select`
   cho ô ngày. Đã sửa: tên lấy từ nhãn nằm phía trên/bên trái ô (vòng đầu: 11,0 / 10,3 hành động TB trên OrangeHRM → 5,3 / 2,7 sau sửa).
3. Trang không có phần tử nào để thao tác: trước đây agent không thấy dòng chữ «No Leave Types…» (không phải `alert`) và tiếp tục thử. Đã sửa: trạng thái trang có thêm
   «Nội dung trang: …» và heading lấy cả h3–h6. Token OrangeHRM giảm 22,5k / 28,9k → 10,2k / 9,3k.
4. `type «To Date»`: `Locator.fill` quá 4 s (1 lượt, text-only) — ô chỉ đọc cần chọn bằng lịch, agent gõ vào.

**Đề xuất cho `flow_agent` (không tự đổi mặc định).**
- Mặc định hiện tại là `deepseek-flash` có ảnh (`LLM_FLOW_AGENT_VISION=true`). Dữ liệu này **không chứng minh vision đáng tiền** trên các luồng form/danh sách: cùng tỉ lệ đạt, đắt hơn ~43 % token.
- Đề xuất: **text-only `deepseek-chat` làm mặc định**, và **chuyển sang có ảnh khi vòng đầu bị kẹt** (cảnh báo lặp hoặc `give_up` hoặc ≥ 2 hành động bị từ chối), rồi chạy lại đúng đoạn đó với ảnh. Cách này giữ
  chi phí thấp mà vẫn dùng ảnh ở nơi nó có ích (ngõ cụt, canvas). Chưa cài đặt vì cần đo thêm.
- Hạn chế của phép đo: mỗi ô chỉ 3 lượt; OrangeHRM bị dữ liệu demo chi phối; **chưa có luồng canvas/control tự vẽ** (squoosh) là chỗ ảnh nhiều khả năng có giá trị. Nên chạy thêm 5 lượt squoosh
  và một site có dropdown tự vẽ trước khi đổi mặc định.

