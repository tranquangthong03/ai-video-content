# V3.1 — Action Zoom (`desktop_frame`)

Kế hoạch: `docs/plans/v3-1.md`. Một quy tắc: **mọi hành động trình duyệt thực hiện (click, dblclick, gõ, chọn, tick, chọn ngày, upload, click điều hướng) đều được zoom**, không phụ thuộc lời đọc / Focus Planner / «khối». Mã: `app/producer/action_zoom.py` (kế hoạch), `apps/render/src/camera/shot.ts` (camera), nhãn hành động + chữ hook fade đơn giản ở `FocusViews.tsx`.

- Vùng zoom = phần tử thật (box của điểm bấm trong focus_log, nếu không có thì inventory, rồi toạ độ click) + nhãn của ô (nếu có) + 25%; mức sao cho vùng chiếm ~55% bề rộng khung, kẹp [1,6×; 2,6×] và không bao giờ nhỏ hơn mức giữ trọn phần tử + nhãn.
- Vào 400 ms **trước** lúc bấm thật (không phải lúc bước bắt đầu: con trỏ cần 1–2 s để tới), 500 ms ease-in-out; giữ suốt lúc gõ và ≥ 1,2 s sau kết quả; hành động kế ≤ 1,5 s và gần (≤ 40% bề rộng) thì pan sang, ngược lại zoom ra toàn cảnh 500 ms.
- Nhãn hành động (pill tối, ≤ 6 từ, cắt bằng code từ note của bước) ở góc trên khung khi đang giữ zoom.
- Vùng cấm cắt dead-time quanh sự kiện: 400 ms trước, 1200 ms sau (`trim.py`).

## T1 trên 4 snapshot (0 lần gọi LLM)

| | orangehrm | squoosh | todomvc | aisoeasy |
|---|---|---|---|---|
| Số hành động / số zoom | 4 / 4 | 2 / 2 | 6 / 6 | 4 / 4 |
| `actions_without_zoom` (0) | 0 | 0 | 0 | 0 |
| Phần tử + nhãn bị cắt khi zoom (0) | 0 | 0 | 0 | 0 |
| Chữ gõ nhỏ nhất, khung cuối (≥ 18 px) | 34,3 | 82,4 | 62,8 | — (không gõ) |
| `steps_in_clip` (100%) | 100% | 100% | 100% | 100% |
| Crossfade lúc camera động / ảnh chồng / đứng-rồi-giật / chớp / đang tải (0) | 0 | 0 | 0 | 0 |
| Ghi số: camera chuyển động / toàn cảnh | 14,3% / 70% | 9,4% / 71% | 18,9% / 41% | 15,9% / 66% |
| Motion QA | đạt | đạt | đạt | đạt |

Đã bỏ khỏi chấm đạt/trượt (chỉ ghi số): zoom/cảnh, toàn cảnh ≥ 50%, đứng yên, và tốc độ zoom/pan (trần 12% / 8% mỗi frame chỉ để bắt cú nhảy hỏng; zoom 2,6× trong 0,5 s đạt ~10%). Chữ gõ ước lượng = 0,4 × chiều cao ô × (1040 / bề rộng view) vì inventory không có cỡ chữ.

Lỗi gặp và sửa trong lượt: log hành động ghi lúc bước **bắt đầu**, còn cú bấm thật đến sau 1–2 s → bản đầu zoom lệch giờ và bỏ sót 3 hành động; nay ghép mỗi hành động với mục focus_log/click_log kế tiếp.

## Xem bằng mắt

- Video (sao chép, ngoài git, không bị ghi đè): `E:\WORK SPACE\AI-video-content\docs\v3-1\videos\{orangehrm,squoosh,todomvc,aisoeasy}.mp4`
- `docs/v3-1/<tên>-frame-sheet.png` (16 frame) và 3 still `-typing.png` / `-click.png` / `-result.png`.
