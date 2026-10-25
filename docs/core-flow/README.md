# Nghiệm thu Core Flow (C13)

Chạy thật bằng `services/api/scripts/acceptance_flow.py` (DeepSeek, model luồng `deepseek-flash` có ảnh màn hình).
Mỗi site có báo cáo riêng (`<site>.md`: storyboard từng bước, chương, lời đọc, contact sheet, số lần gọi LLM) và
`<site>-flow_run.json`. Job gốc nằm ở `services/api/out/v4/` (không commit).

| Site / luồng | Trạng thái luồng | Agent (gọi LLM · giây · token) | Phát lại | Chương | Video | Cảnh quay thật | **Request ghi** |
|---|---|---|---|---|---|---|---|
| todomvc · «Lên danh sách việc trong ngày: thêm 3 việc, tích 1, lọc Active» (submit allow) | reached_goal | 6 · 19,6 s · 15,9k | 5/5 | 4 | 35,7 s | 0,85 | **0** |
| OrangeHRM · «Nhân viên xem danh sách đơn nghỉ phép của mình (My Leave)» (stop) | reached_goal | 4 · 25,1 s · 10,0k | 3/3 | 2 | 32,3 s | 0,81 | **0** |
| squoosh · «Nén một ảnh mẫu rồi so sánh trước/sau» (stop) | reached_goal | 6 · 27,9 s · 17,6k | 1/5 (dừng ở bước 3) | 4 | 36,8 s | 0,16 | **0** |
| OrangeHRM · «Nhân viên xin nghỉ phép 2 ngày rồi xem trạng thái đơn» (stop) | **partial** (không hoàn tất) | 10 · 74,8 s · 35,1k | — | — | không dựng | — | **0** |

## Kết luận từng luồng
- **todomvc**: đúng mục tiêu, quay một mạch một context (3 việc được thêm, 1 việc được tích, lọc Active), trạng thái giữ qua các chương.
- **OrangeHRM «xin nghỉ phép»**: **không hoàn thành được trên tài khoản demo Admin**. Agent mở được Leave → Apply, điền hai ngày,
  nhưng form không có ô «Leave Type» dùng được (trang báo «No Leave Types with Leave Balance»: tài khoản không có hạn mức nghỉ).
  Tạo hạn mức là ghi dữ liệu lên site dùng chung nên bị cấm. Storyboard vẫn hiện bằng chứng; sau 1 lần «Chạy lại», người dùng giả lập
  hủy thay vì quay một luồng cụt. Request ghi = 0 (guard + agent + quay).
- **OrangeHRM «xem đơn nghỉ»**: luồng chỉ đọc chạy trọn trên site thật, 0 request ghi, video quay đủ cả hai chương. Luồng khá ngắn
  (3 bước: agent dừng khi thấy danh sách đang tải).
- **squoosh**: agent đạt mục tiêu (chọn ảnh mẫu, chỉnh chất lượng 50 → 25, bật nền, làm mịn) nhưng **phát lại thất bại ở bước 3**:
  bước gõ số ở bước 3 không tìm lại được phần tử (`css_nth` chỉ còn 1 khớp, `bbox` lệch; nghi do control tự vẽ của squoosh). Theo thiết kế (không quay lại
  từ đầu) 3 chương cuối và hook dùng ảnh storyboard → tỉ lệ cảnh quay chỉ 0,16. Đây là điểm yếu còn lại rõ nhất (xem dưới).

## Lỗi thật tìm ra khi nghiệm thu (đã sửa, có test)
1. **Cuộn lên làm sập job**: agent ghi `scroll up` thành `ms = -600`, trái schema (`ms ≥ 0`) → `FlowRun` không hợp lệ. Giờ ms luôn dương, hướng lên nằm ở `text="up"`; recorder và phát lại hiểu.
2. **Agent không nhấn Enter nhưng video có Enter**: `type` của agent chỉ điền chữ, còn recorder nhấn Enter theo `enter_policy` → agent không thấy việc mới xuất hiện (todomvc) rồi bỏ cuộc. Giờ agent dùng cùng chính sách Enter và lịch sử ghi «(đã nhấn Enter)».
3. **Ô tick trong suốt không được liệt kê** (todomvc: `input.toggle` opacity 0, vẽ bằng label): agent không thể «tích xong 1 việc». Giờ được liệt kê và đặt tên theo dòng chứa nó; tên lấy từ dữ liệu người dùng («Mua sữa») không bị blacklist «mua» chặn nhầm.
4. **Render lỗi tạm thời** khi 3 job render cùng lúc (`delayRender` timeout): render tự thử lại 1 lần.
5. **Bước click đã biến mất khi phát lại** (thường là cú click thứ hai của agent lên thứ đang tải): bỏ qua tối đa 2 bước dạng click/hover/cuộn rồi quay tiếp; bước gõ/chọn/ngày không bao giờ bị bỏ; bước bị lớp an toàn từ chối không bao giờ bị bỏ qua.
6. Hover lên nút gửi bị recorder chặn («would submit a form») → đã cho phép khi phát lại luồng (chỉ trỏ, không bấm).

## Còn tồn đọng (không giấu)
- **Phát lại trên control tự vẽ** (squoosh) vẫn mong manh: locator `css_nth` lệch. Cần chiến lược tìm lại tốt hơn (theo nhãn/role đầy đủ) hoặc quay song song lúc agent chạy.
- **Agent lặp lại việc sửa ô ngày** trên OrangeHRM (5 lần «Chỉnh lại ngày…») rồi cuộn vô ích: lãng phí lần gọi, đáng đo ở benchmark C14 (text-only so với có ảnh).
- **Khung hình hook/camera**: hook lấy 2 s quanh khoảnh khắc chính nhưng khung to ở trạng thái cuối, nội dung nhỏ; một vài đoạn zoom quá sát vào góc trang (todomvc). Thuộc lượt M1/camera.
- **Luồng phụ** chưa dựng (chỉ cảnh báo).
- **Test timing có sẵn** `test_recorder::…1440x900…`: video dài hơn đồng hồ log 1,2–1,4 s (ngưỡng 1,2 s), hiện fail ổn định trên máy này. Chưa xác định độ lệch nằm ở đầu hay cuối clip; nếu ở đầu thì log lệch 1,3 s so với hình (ảnh hưởng cắt chương/camera). Cần đo riêng.

## Benchmark Flow Agent (C14)
Xem `llm-benchmark.md` (bảng, các bước hay kẹt, nhận xét, đề xuất cấu hình) và `llm-benchmark-before.md` (vòng chạy trước các cải tiến page-state / lỗi `select`). Chạy lại: `uv run python scripts/bench_flow_agent.py run <fixture|orangehrm|todomvc>` rồi `... report`.
