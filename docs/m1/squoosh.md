# M1 — squoosh

- Video: `E:\WORK SPACE\AI-video-content\services\api\out\m1-squoosh\video.mp4`
- Job: `E:\WORK SPACE\AI-video-content\services\api\out\m1-squoosh`
- Thời lượng thực: 22.4s (mục tiêu 30s)
- Contact sheet 16 khung: `squoosh-contact-sheet.png`
- Still của hook: `squoosh-hook.png`

## Lời đọc cũ (R4) và mới (M1) từng cảnh

| # | Loại | Cũ | Mới |
|---|---|---|---|
| s1 | hook | Ảnh nặng làm chậm trang web? Nhiều người lo ảnh nén bị mờ, giảm chất lượng. | Ảnh 2.8MB tải chậm? Nén ngay trên máy, không gửi máy chủ. |
| s2 | feature_demo | Mở Squoosh, chọn ảnh mẫu 2.8MB để thử nén an toàn. | Kéo thanh so sánh: ảnh nhỏ hơn mà vẫn nét, mọi thứ xử lý ngay trên máy bạn, không gửi ảnh lên máy chủ. |
| s3 | cta | Hạ chất lượng MozJPEG xuống 60, dung lượng giảm mạnh mà vẫn cân bằng độ nét. | Mở squoosh.app — nén ảnh ngay trên máy bạn, không cần cài đặt, ảnh không rời thiết bị. |

Headline cũ: Nén ảnh không giảm chất lượng  
Headline mới: Nén ảnh nhỏ hơn mà vẫn giữ chất lượng

## Hook

1. `pain_question`: «Ảnh 2.8MB tải chậm? Nén ngay trên máy, không gửi máy chủ.» (chữ: 2.8MB tải chậm?) ← **được chọn**
2. `result_first`: «Nén ảnh ngay trên trình duyệt, xem rõ khác biệt trước sau.» (chữ: Nén ngay trên trình duyệt)

Điểm hook_strength của 2 phương án: [6, 4]

Khung kể chuyện: `pain_journey_result`

## Điểm Copy Critic trước / sau

- Trước: hook_strength=6, benefit_clarity=7, proof_usage=5, cta_strength=5, flow=6
- Sau viết lại: hook_strength=8, benefit_clarity=6, proof_usage=3, cta_strength=7, flow=6 (giữ bản viết lại)
- Đã viết lại các cảnh: ['s1', 's2', 's3']
- Nhận xét: Kịch bản có hook tốt, mạch gọn và CTA khá rõ nhưng chưa khai thác proof_bank và chưa thể hiện đúng hành vi cốt lõi của persona là so sánh chất lượng trước/sau. Cần siết scene 2 bằng demo thanh so sánh và số Quality:75, đồng thời đưa privacy + không cài đặt vào CTA để tăng độ thuyết phục.

## Scorecard

| Tiêu chí | Giá trị | Cần | Kết quả |
|---|---|---|---|
| Hook: khung gần + chữ ngắn trong 2 giây đầu | gần, 3 từ | khung tight/medium, chữ ≤ 5 từ | pass |
| Không cảnh nào đứng yên quá lâu | 1.85 | ≤ 3.0 s | pass |
| Không có khung hình chết | 0 | 0 ms | pass |
| Thẻ chữ toàn màn hình | 0%, max 0ms | mỗi thẻ ≤ 3 s, tổng ≤ 15% | pass |
| Critic: hook | 8 | ≥ 7 | pass |
| Critic: lợi ích | 6 | ≥ 7 | fail |
| Critic: kêu gọi | 7 | ≥ 7 | pass |
| Dùng bằng chứng thật | có | có | pass |
| Tỉ lệ cảnh quay thật | 67% | ≥ 60% | pass |
| Bước thao tác có trong video | 100% | ≥ 80% | pass |
| Âm thanh | chưa có (M2) | — | info |

Đạt 9/10 (không đạt: 1)

## Con số trong video và nguồn

| Ở đâu | Con số | Nguồn |
|---|---|---|
| s1 lời đọc | 2.8MB | mô tả luồng đã duyệt |
| s1 chữ | 2.8MB | mô tả luồng đã duyệt |
| s2 stat | 2.8MB | mô tả luồng đã duyệt |

## Số liệu dựng phim

- footage_ratio: 0.667
- dead_frames_ms: 0
- dead_frames_cut_ms: 0
- max_static_shot_s: 1.85
- punch_ins: 7
- text_cards: {'count': 0, 'longest_ms': 0, 'ratio': 0.0, 'ok': True}
- hero: {'t_ms': 8717, 'from_ms': 7917, 'to_ms': 9917, 'score': 43.0}
- steps_in_clip: 1.0
- write_requests: []
