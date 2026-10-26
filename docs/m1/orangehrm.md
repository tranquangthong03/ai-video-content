# M1 — orangehrm

- Video: `E:\WORK SPACE\AI-video-content\services\api\out\m1-orangehrm\video.mp4`
- Job: `E:\WORK SPACE\AI-video-content\services\api\out\m1-orangehrm`
- Thời lượng thực: 43.5s (mục tiêu 45s)
- Contact sheet 16 khung: `orangehrm-contact-sheet.png`
- Still của hook: `orangehrm-hook.png`

## Lời đọc cũ (R4) và mới (M1) từng cảnh

| # | Loại | Cũ | Mới |
|---|---|---|---|
| s1 | hook | Tạo hồ sơ cho nhân viên mới mất bao lâu? Chỉ vài thao tác trong module PIM là xong. | Tạo hồ sơ nhân viên mới trong PIM chỉ với một cú. |
| s2 | feature_demo | Mở module PIM, bấm Add là form thêm nhân viên hiện ra ngay. | Ngay tại danh sách nhân viên PIM, bấm nút Add là form mở ra tại chỗ, không cần chuyển trang — tiết kiệm thao tác cho HR. |
| s3 | feature_demo | Nhập họ, tên đệm và họ của nhân viên vào form. | Nhập First Name và Last Name, hệ thống ghi nhận tự động, hồ sơ đã sẵn sàng ngay sau khi điền xong. |
| s4 | feature_demo | Đã điền đủ họ tên và mã nhân viên, chỉ còn chờ bấm Save. | Form đã có đủ họ tên Nguyen Van An và mã nhân viên 0736, bạn dừng lại kiểm tra một lượt, rồi chỉ một cú bấm Save là xong. |
| s5 | cta | Tạo hồ sơ nhân sự mới ngay trong module PIM, không cần rời giao diện quản trị tập trung. | Trải nghiệm OrangeHRM mã nguồn mở miễn phí ngay tại opensource-demo.orangehrmlive.com. |

Headline cũ: Tạo hồ sơ nhân sự mới nhanh trong PIM  
Headline mới: Tạo hồ sơ nhân viên mới ngay trong PIM

## Hook

1. `pain_question`: «Tạo hồ sơ nhân viên mới trong PIM chỉ với một cú.» (chữ: Một cú bấm Add) ← **được chọn**
2. `result_first`: «Tạo hồ sơ nhân viên mới chỉ trong vài cú bấm.» (chữ: Vài cú bấm là xong)

Điểm hook_strength của 2 phương án: [6, 4]

Khung kể chuyện: `pain_journey_result`

## Điểm Copy Critic trước / sau

- Trước: hook_strength=6, benefit_clarity=5, proof_usage=4, cta_strength=5, flow=6
- Sau viết lại: hook_strength=5, benefit_clarity=6, proof_usage=4, cta_strength=6, flow=7 (giữ bản viết lại)
- Đã viết lại các cảnh: ['s1', 's2', 's3']
- Nhận xét: Kịch bản đạt mức khá (trung bình 5.6/10), có thể cải thiện rõ rệt bằng cách làm hook đánh trúng nỗi đau chuyển trang, nhấn mạnh lợi ích thời gian ở scene 2-3, và CTA mạnh hơn với ưu đãi 'mã nguồn mở miễn phí' từ proof_bank. Chưa nên đăng ngay vì hook và proof chưa đủ mạnh.

## Scorecard

| Tiêu chí | Giá trị | Cần | Kết quả |
|---|---|---|---|
| Hook: khung gần + chữ ngắn trong 2 giây đầu | gần, 4 từ | khung tight/medium, chữ ≤ 5 từ | pass |
| Không cảnh nào đứng yên quá lâu | 2.61 | ≤ 3.0 s | pass |
| Không có khung hình chết | 0 | 0 ms | pass |
| Thẻ chữ toàn màn hình | 0%, max 0ms | mỗi thẻ ≤ 3 s, tổng ≤ 15% | pass |
| Critic: hook | 5 | ≥ 7 | fail |
| Critic: lợi ích | 6 | ≥ 7 | fail |
| Critic: kêu gọi | 6 | ≥ 7 | fail |
| Dùng bằng chứng thật | có | có | pass |
| Tỉ lệ cảnh quay thật | 89% | ≥ 60% | pass |
| Bước thao tác có trong video | 100% | ≥ 80% | pass |
| Âm thanh | chưa có (M2) | — | info |

Đạt 7/10 (không đạt: 3)

## Con số trong video và nguồn

| Ở đâu | Con số | Nguồn |
|---|---|---|
| s4 lời đọc | 0736 | proof bank — frame: «0736» |
| s4 stat | 0736 | proof bank — frame: «0736» |

## Số liệu dựng phim

- footage_ratio: 0.893
- dead_frames_ms: 0
- dead_frames_cut_ms: 0
- max_static_shot_s: 2.61
- punch_ins: 9
- text_cards: {'count': 0, 'longest_ms': 0, 'ratio': 0.0, 'ok': True}
- hero: {'t_ms': 42145, 'from_ms': 41233, 'to_ms': 43233, 'score': 15.0}
- steps_in_clip: 1.0
- write_requests: []
