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
