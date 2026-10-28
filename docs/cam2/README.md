# CAM-2 — kết quả (T1 trên 3 snapshot, 0 lần gọi LLM)

| Chỉ số | Ngưỡng | orangehrm trước → sau | squoosh trước → sau | todomvc trước → sau |
|---|---|---|---|---|
| Zoom tối đa/khung | ≤ 2,5% | 2,5% → 1,9% | 2,1% → 1,6% | 2,3% → 2,5% (sát; kế hoạch camera 2,0%) |
| Pan tối đa/khung | ≤ 1,5% | 1,1% → 1,1% | 2,2% → 1,1% | 0,7% → 0,7% |
| Đứng yên dài nhất | ≤ 400 ms | 167 → 167 | 0 → 0 | 0 → 0 |
| Đứng yên rồi giật / cảnh chớp / ảnh đang tải | 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| Chữ tiêu điểm bị cắt (khung) | 0 | 207 → **0** | 434 → **0** | 38 → **0** |
| Tiêu điểm khớp lời/thao tác | ≥ 85% | 71,2% → **100%** | 100% → 100% | 92,7% → 92,7% |

Contact sheet: `orangehrm-contact-sheet.png`, `squoosh-contact-sheet.png`, `todomvc-contact-sheet.png`.
Video T1: `services/api/out/regress/<site>/video.mp4`.

## Nguyên nhân và cách sửa

| Việc | Nguyên nhân gốc | Sửa |
|---|---|---|
| A1 chữ bị cắt | Camera «trôi» chậm (breathe/lean) quanh chính giữa view, không biết khung tiêu điểm; khi nút sát mép clip (squoosh «Compress» x=1140..1440) view thu nhỏ và trượt, mép nút ra ngoài. | `driftView` nhận hộp tiêu điểm đã đệm 12% (`paddedBox`), luôn trượt view (`keepBox`) và không cho zoom gần hơn mức còn chứa hộp; view đã sát giới hạn thì «thở» ra ngoài (`wobble`) thay vì đứng yên. Số đo chỉ đếm chữ của chính phần tử (+ nhãn nếu là ô nhập) và in top 5 khoảng bị cắt (`focus_clipped_spans`). |
| A1 chính sách khối chữ rộng | Khối chữ rộng hơn cửa sổ ở cover. | (1) `narrow_to_child`: thu về phần tử con có chữ khớp lời đọc, hoặc chứa con số; (2) nếu không có thì giữ nguyên, camera zoom dưới cover (đã có trong `targetView`). Bộ đếm `narrowed_to_child` / `fit_below_cover` trong `focus/<scene>.json["summary"]`. Trên 3 snapshot cả hai bằng 0 (không khối nào rộng quá). |
| A2 pan squoosh 2,2% | Không phải camera: kế hoạch camera chỉ 1,1%/khung. Một khung ở 6,1 s là nội dung trang đổi (ảnh hiện ra) mà phép quy kết chưa nhận ra vì ngưỡng «lệch so với kế hoạch» quá rộng (= đúng ngưỡng giới hạn). | `page_changes`: lệch quá 0,6% (pan) / 0,8% (zoom) so với kế hoạch camera là do trang. Thêm `camera_plan_max_zoom_rate/pan_rate` vào metrics để thấy tốc độ camera thật. Orangehrm zoom 2,52%: nhiễu đo; kế hoạch 1,9%. |
| A3 orangehrm 71% | Tiêu điểm của đoạn 7,7–13,8 s là «toàn trang» vì phần tử «Add» không có trong ảnh chụp nào gần đó (trang tải 4 s, ảnh chụp đầu tiên sau thao tác ở 12,0 s) và planner hỏng id. | `newest_or_center`: phần tử không có ảnh chụp thì lấy phần tử lời đọc nhắc, hoặc khối mới lớn nhất của ảnh chụp gần nhất (chỉ khi không có tiêu điểm cũ của recorder, không phải trang ảnh). Bộ đếm `unresolved_recovered`. `focus_unmatched` in các khoảng không khớp. |
| A4 «ảnh đang tải» | Vùng màu phẳng ổn định bị coi là chờ tải (Paletton 4000 ms). | Inventory ghi `loaded` cho img (`complete`), canvas 2d (có pixel), video (`readyState`). Phẳng + `loaded=true` → là nội dung; `loaded=false` → đang tải; không rõ → chỉ tính là chờ khi kết thúc trong ≤ 3 s. |
| A5 test chụp ảnh chập chờn | `Page.captureScreenshot` thất bại khi máy bận vì khung hình đầu tiên của trang mới chưa có và test chờ theo đồng hồ (`wait_for_timeout(300)`). Tái hiện: 2/24 chạy song song. | `open_app` chờ 2 `requestAnimationFrame` (+ `bring_to_front`) thay cho 300 ms. Sau sửa: 24/24 pass. |

Lưu ý: `tests/test_recorder.py::test_typing_and_cursor_movement_are_not_idle_time` (đo khoảng nghỉ theo đồng hồ) trượt 1 lần trong lần chạy `area_producer or area_recorder` tải nặng và pass 2/2 khi chạy riêng; chưa sửa.
