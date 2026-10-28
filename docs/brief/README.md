# BRIEF — marketing brief do người dùng cung cấp

Website không nói hết đối tượng, lợi ích, số liệu và ưu đãi, nên critic benefit/CTA thiếu nguyên liệu. Hệ thống nay hỏi người dùng đúng những điều đó, sau khi storyboard luồng được duyệt và trước dàn ý.

## Cách chạy

| Việc | Cách |
|---|---|
| Hỏi qua web | Thẻ «Bổ sung brief cho video» (`docs/screenshots/30-marketing-brief-card.png`): gợi ý dạng chip bấm chọn, ô tự nhập, danh sách số liệu thêm/xóa dòng, nút Bỏ qua, ghi chú «Chỉ nhập số liệu có thật — số liệu sẽ xuất hiện trong video». |
| Hỏi qua CLI | Menu `Nhập brief / Bỏ qua`, chọn gợi ý hoặc tự nhập từng ô. |
| `--auto` | Bỏ qua (hành vi cũ, không tốn lần gọi LLM tạo gợi ý) trừ khi có `--brief <file.json>` hoặc có câu trả lời `marketing_brief` trong `answers.json`. |
| Brief sẵn | `explore_cli --brief file.json` (file là brief, hoặc `{"brief": {...}}` kèm ghi chú gạch dưới). |
| Lưu | `<job>/marketing_brief.json`; `{"skipped": true}` khi bỏ qua, để job chạy tiếp không hỏi lại. |

Schema: `packages/script-schema/schemas/marketing_brief.json` (+ `brief_suggestions.json`, kind `marketing_brief`, action `skip`, `UserResponse.brief`).

## Brief đi vào đâu

- **Gợi ý** (`app/proposal/brief_suggest.py`, prompt `brief_suggest.md`): 1 lần gọi LLM, 3 gợi ý đối tượng / lợi ích chính / ưu đãi; lỗi thì dùng gợi ý chung theo loại site.
- **Proof bank** (`app/script/proof.py`): số liệu của người dùng có `source="user"`, đứng đầu và không bị xóa (được tính là có nguồn cho kiểm tra số); câu số liệu và lợi ích chính thành quote; ưu đãi thành offer `user`. Số được tách đơn vị («40%» → 40 + %).
- **Writer / scene writer / critic** (`{# changed #}` trong prompt): hook ưu tiên lợi ích chính hoặc số liệu thật; mỗi chương gắn một lợi ích và mở bằng kết quả; CTA dùng ưu đãi + lời kêu gọi; giọng điệu theo brief; critic chấm benefit/CTA theo brief.
- **avoid**: thành cụm cấm của script (prompt và kiểm tra code ở mọi scene, headline, hook).
- **cta_url**: tên miền ngắn hiện ở cảnh cuối (`cta_domain` của render).

## Nghiệm thu T2 (3 snapshot, DeepSeek, bước script + critic, không render)

Điểm critic hook / benefit / proof / CTA / flow. «Không brief» = hành vi cũ; «brief» = `tests/golden/<site>/brief.sample.json` (dữ liệu thử nghiệm, không dùng cho video thật). Critic dao động ±1 giữa các lần.

| Snapshot | Không brief | Brief (lần 1) | Brief (sau chỉnh prompt «mở bằng kết quả») |
|---|---|---|---|
| orangehrm | 6 / 5 / 3 / 7 / 6 | 6 / 6 / 5 / 6 / 6 | 8 / 5 / 4 / **8** / 6 |
| squoosh | 7 / 7 / 8 / 8 / 8 | 7 / 6 / 6 / **7** / 7 | 7 / 6 / 7 / **8** / 7 |
| todomvc | 6 / 5 / 7 / 6 / 7 | 7 / 6 / 5 / **8** / 7 | 7 / 6 / 4 / **7** / 7 |

Mục tiêu «có brief thì benefit ≥ 7 và CTA ≥ 7 ở ≥ 2/3 snapshot»:
- **CTA ≥ 7: đạt** (lần 1: 2/3; sau chỉnh prompt: 3/3, điểm 8 / 8 / 7).
- **Benefit ≥ 7: chưa đạt** (6, 6, 6 → 5, 6, 6). Critic vẫn nói các chương giữa «kể thao tác». Với brief chỉ có lợi ích chính + ưu đãi và không có số liệu, các chương demo ít nguyên liệu; nhiều lần viết lại bị bỏ vì bị chấm thấp hơn hoặc vì chứa số không có nguồn (bộ chặn số hoạt động đúng). Hướng tiếp: brief có lợi ích phụ + số liệu, và thử ép mỗi chương một câu kết quả trong kiểm tra bằng code.

Hook và CTA sinh ra (lần sau chỉnh prompt):
- orangehrm — hook: «HR gõ hồ sơ giấy cả buổi chỉ cho một cái tên.» · CTA: «Tạo hồ sơ nhân viên mới trong vài phút — mã nguồn mở, dùng miễn phí. Vào orangehrmlive chấm com dùng thử.»
- squoosh — hook: «Ảnh 2.8MB làm web ì ạch?» · CTA: «Miễn phí, chạy ngay trên trình duyệt, ảnh không rời thiết bị — thử tại squoosh.app.»
- todomvc — hook: «Quá nhiều việc mà bạn quên mất việc còn phải làm?» · CTA: «Thử ngay, không cần đăng ký, lập danh sách việc trong ngày tại todomvc.com.»

Chi phí LLM của nghiệm thu: không brief 36 lần gọi / 142 714 token; brief lần 1 48 / 170 609; brief sau chỉnh prompt 61 / 216 387; tổng 145 lần gọi, 529 710 token. Mốc lưu ở `docs/regress/last.json` (`t2`: không brief, `t2_brief`: có brief).

## Hiệu chỉnh critic (chưa đổi ngưỡng)

`docs/critic-calibration.md`: 3 kịch bản snapshot ở dạng đọc được + bảng trống để tự chấm 5 tiêu chí 0–10. Điền xong chạy `uv run python scripts/critic_calibration.py compare` (trong `services/api`) để xem độ lệch giữa điểm bạn chấm và điểm critic.
