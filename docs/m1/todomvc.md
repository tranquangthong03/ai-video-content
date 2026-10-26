# M1 — todomvc

- Video: `E:\WORK SPACE\AI-video-content\services\api\out\m1-todomvc\video.mp4`
- Job: `E:\WORK SPACE\AI-video-content\services\api\out\m1-todomvc`
- Thời lượng thực: 43.9s (mục tiêu 45s)
- Contact sheet 16 khung: `todomvc-contact-sheet.png`
- Still của hook: `todomvc-hook.png`

## Lời đọc cũ (R4) và mới (M1) từng cảnh

| # | Loại | Cũ | Mới |
|---|---|---|---|
| s1 | hook | Bạn hay quên việc cần làm? Ghi chú rối khiến bạn mất tập trung? | Danh sách việc rối tung khiến bạn bỏ sót việc cần làm? |
| s2 | feature_demo | Mở trang, gõ việc đầu tiên vào ô nhập thật nhanh. | Thêm ba việc cần làm trong ngày vào ô nhập, mỗi lần chỉ một dòng ngắn gọn. |
| s3 | feature_demo | Gõ tiếp việc thứ hai, thứ ba, danh sách vẫn gọn gàng. | Việc thứ ba nhập xong, nhấn Enter là danh sách đủ ba mục, gọn trong một dòng. |
| s4 | feature_demo | Tích ô vuông để đánh dấu hoàn thành, thấy ngay việc nào đã xong. | Chỉ muốn xem việc chưa xong? Nhấp bộ lọc Active để ẩn các việc đã hoàn thành đi. |
| s5 | feature_demo | Nhấn Active để chỉ hiện việc chưa xong, danh sách rút gọn giúp tập trung. | Kết quả: danh sách chỉ còn hai việc chưa hoàn thành, bộ lọc Active nổi bật rõ ràng. |
| s6 | cta | Quản lý nhanh việc trong ngày và tập trung việc còn lại. Dùng thử ngay! | Tập trung vào việc còn phải làm mà không bị phân tâm bởi việc đã xong. Thử ngay tại todomvc.com. |

Headline cũ: Lên việc trong ngày, lọc việc còn lại  
Headline mới: Lên danh sách việc trong ngày thật nhanh

## Hook

1. `pain_question`: «Danh sách việc rối tung khiến bạn bỏ sót việc cần làm?» (chữ: Bỏ sót việc?) ← **được chọn**
2. `you_are_doing_it_wrong`: «Đừng ghi việc cần làm lên giấy nữa, có cách gọn hơn.» (chữ: Gọn hơn trên giấy)

Điểm hook_strength của 2 phương án: [7, 6]

Khung kể chuyện: `pain_journey_result`

## Điểm Copy Critic trước / sau

- Trước: hook_strength=7, benefit_clarity=6, proof_usage=4, cta_strength=6, flow=5
- Sau viết lại: hook_strength=6, benefit_clarity=5, proof_usage=3, cta_strength=6, flow=6 (không dùng)
- Đã viết lại các cảnh: không
- Nhận xét: Kịch bản có hướng đúng nhưng chưa khắt khe với persona: hook còn chung, thiếu bước đánh dấu hoàn thành, số liệu chưa khớp proof_bank và CTA thiếu lý do hành động ngay. Cần sửa các scene s1–s6 theo gợi ý để đạt mức có thể đăng.
- Ghi chú: scene s1: không viết lại được (scene: hook có 4 từ, cần 5–12)
- Ghi chú: bản viết lại bị chấm thấp hơn nên giữ bản gốc

## Scorecard

| Tiêu chí | Giá trị | Cần | Kết quả |
|---|---|---|---|
| Hook: khung gần + chữ ngắn trong 2 giây đầu | gần, 3 từ | khung tight/medium, chữ ≤ 5 từ | pass |
| Không cảnh nào đứng yên quá lâu | 2.4 | ≤ 3.0 s | pass |
| Không có khung hình chết | 0 | 0 ms | pass |
| Thẻ chữ toàn màn hình | 0%, max 0ms | mỗi thẻ ≤ 3 s, tổng ≤ 15% | pass |
| Critic: hook | 7 | ≥ 7 | pass |
| Critic: lợi ích | 6 | ≥ 7 | fail |
| Critic: kêu gọi | 6 | ≥ 7 | fail |
| Dùng bằng chứng thật | có | có | pass |
| Tỉ lệ cảnh quay thật | 81% | ≥ 60% | pass |
| Bước thao tác có trong video | 100% | ≥ 80% | pass |
| Âm thanh | chưa có (M2) | — | info |

Đạt 8/10 (không đạt: 2)

## Con số trong video và nguồn

| Ở đâu | Con số | Nguồn |
|---|---|---|
| s3 stat | 3 | proof bank — frame: «3 items left! AllActiveCompleted» |
| s5 chữ | 2 | proof bank — frame: «2 items left! AllActiveCompleted» |
| s5 stat | 2 | proof bank — frame: «2 items left! AllActiveCompleted» |

## Số liệu dựng phim

- footage_ratio: 0.812
- dead_frames_ms: 0
- dead_frames_cut_ms: 0
- max_static_shot_s: 2.4
- punch_ins: 7
- text_cards: {'count': 0, 'longest_ms': 0, 'ratio': 0.0, 'ok': True}
- hero: {'t_ms': 6477, 'from_ms': 5677, 'to_ms': 7677, 'score': 30.2}
- steps_in_clip: 1.0
- write_requests: []
