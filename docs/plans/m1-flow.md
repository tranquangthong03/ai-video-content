## NHIỆM VỤ — P0 (dọn dẹp) + M1 (nội dung marketing + dựng phim theo luồng/chương)

Trả lời bằng tiếng Việt. Lượt R (quay trực tiếp, luồng không khả thi) đã đạt. Lượt này gồm P0 rồi M1 viết THEO CẤU TRÚC LUỒNG/CHƯƠNG. Được sửa prompt flow_discovery.md, flow_agent.md, script_writer.md, scene_writer.md, duration_fit.md (đánh dấu {# changed: ... #}), template desktop_focus, producer. Commit nhỏ, kiểm tra trước commit nối && + kiểm exit code. Giữ nguyên mục 0–4 và 8–10 của docs/HANDOFF.md, chỉ cập nhật mục 5–7 sau các lượt lớn (P0, M1-2, M1-4, M1-6) và commit cùng lượt đó. Chạy pytest -n auto 3 lần liên tiếp chỉ ở cuối P0-a và cuối M1-6; commit giữa chừng chạy test liên quan ở foreground.

### Quyết định mặc định đã duyệt
- Copy Critic dùng model text (role copy_critic, deepseek-chat), không gửi ảnh.
- Hero frame chấm bằng code từ frame_inventory (item is_new, form đã điền, bảng/danh sách có dữ liệu, mật độ chữ vừa phải, ưu tiên bước cuối/cao trào), không dùng LLM nhìn ảnh.
- Scene trước/sau là layout mới của scene before_after có sẵn, không thêm scene type; nếu cần thì thêm layout vào scene.json rồi codegen.
- steps_in_clip của scorecard dùng cùng định nghĩa với P0-c.
- M1-4 tách 2 commit: M1-4a (producer/focus_plan) và M1-4b (template DesktopFocus), có test thuần cho từng quy tắc (shot, khung chết, giới hạn zoom, thẻ chữ).
- URL thứ 4 trong nghiệm thu: bỏ qua.

### P0 — Dọn dẹp trước M1
P0-a. 3 test chập chờn khi chạy -n auto (test_api hàng đợi job, test_login_privacy làm mờ header, test_upload_and_settle hover file input; chạy riêng thì pass). Nghi phạm: browser_session module-scope, time.monotonic() < 3.5 cố định, time.sleep(0.02) + thread JobRunner, cổng cố định, thư mục out/ dùng chung, env/.env, singleton. Tìm nguyên nhân gốc, sửa để chạy song song ổn định (tmp riêng mỗi test, cổng ngẫu nhiên, chờ theo điều kiện thay vì sleep/timeout cứng). Xong khi: pytest -n auto 3 lần liên tiếp 0 fail.
P0-b. Luồng người dùng tự mô tả bị đánh "không khả thi" (OrangeHRM: "Thêm nhân viên mới", "Thêm ứng viên") trong khi luồng tương tự do Discovery đề xuất chạy được. Dùng flows_infeasible.json và flow_run.json của job out/r4-orangehrm, so core_flow sau normalize với core_flow của Discovery (start_url, expected_steps, success_signal), xác định nguyên nhân bằng bằng chứng rồi sửa: normalize chọn start_url từ pages đã khám phá gần nhất với mô tả; agent chỉ được give_up no_data/feature_missing khi có thông báo trên trang hoặc đã thử điều hướng qua menu khớp mô tả (ràng buộc cả ở prompt flow_agent.md và trong code). Test hồi quy với dữ liệu OrangeHRM đã lưu.
P0-c. flow_report thêm steps_in_clip = số bước có thao tác xuất hiện trong clip cuối / tổng bước (tính từ marks của live clip hoặc focus_log), in cho 3 video R4 và lưu vào docs/core-flow/r4/.

### M1-1 — Proof bank (app/script/proof.py, hàm thuần + test)
- Trích từ confirmed_profile, pages (key_texts, value_props, evidence quotes) và frame_inventory của clip luồng: numbers {value, unit, context, source}, quotes (≤ 120 ký tự nguyên văn), offers (free, dùng thử, mã nguồn mở, không cần thẻ, không cần cài đặt...), audience_pains.
- unsupported_numbers(text, proof, inventory): mọi con số trong voiceover/on_screen_text/headline/stat phải có nguồn; không có → vòng sửa 1 lần → vẫn sai thì code xóa con số (sau đó chạy duration_fit).

### M1-2 — Narrative theo luồng (schema + script_writer, scene_writer, duration_fit)
- Schema + codegen: script.framework, script.hook_options (2 phương án, mỗi phương án {kind, voiceover, on_screen_text}), scene.stat {value, label} tùy chọn; EditOp set để chọn hook ở script_review (không gọi LLM).
- Input bổ sung cho writer: core_flow (persona, goal, value), các chương (title, value_line, bước + note), proof bank, mô tả hero frame (text items nổi bật), submit_policy/kết quả luồng.
- Framework mặc định cho video luồng: pain → journey → result (PAS rút gọn); tool một trang: before_after_bridge. Ghi script.framework.
- Hook ≤ 12 từ, 2 hook_options khác kiểu ∈ {pain_question, result_first, shocking_number (chỉ khi có số), counterintuitive, you_are_doing_it_wrong}; không mở bằng tên sản phẩm; nói với persona. Mặc định chọn phương án critic chấm cao hơn; người dùng đổi ở script_review.
- Mỗi chương: câu đầu là LỢI ÍCH/KẾT QUẢ của chặng cho persona, nhắc thao tác tối đa 1 cụm ngắn; chương cuối nhấn kết quả. Nếu dừng trước khi gửi: lời ở cao trào kiểu "chỉ một cú bấm là xong" (không khẳng định dữ liệu đã được lưu).
- Ít nhất 1 chỗ dùng proof (nếu proof bank có).
- CTA: hành động cụ thể + lý do có thật (offer từ proof bank) + domain ngắn; không đọc URL dài.
- Cấm sáo rỗng: "giải pháp toàn diện", "tối ưu hóa trải nghiệm", "nâng tầm", "đột phá", "hoàn hảo".
- on_screen_text ≤ 5 từ, là "cú đấm" (lợi ích/con số), không lặp phụ đề.
- Kiểm tra bằng code (không chỉ nhờ prompt): độ dài hook, cụm cấm, độ dài on_screen_text, con số có nguồn.

### M1-3 — Copy Critic (app/script/critic.py + prompts/copy_critic.md — NGUYÊN VĂN prompt ở cuối)
- Chấm 0–10: hook_strength, benefit_clarity, proof_usage, cta_strength, flow. Ngưỡng ≥ 7 mỗi tiêu chí; dưới ngưỡng → Scene Writer rewrite đúng scene yếu theo gợi ý (1 vòng) → chấm lại; lưu điểm trước/sau vào script_report. Không chạy tự động sau khi người dùng tự sửa (chỉ hiển thị điểm). proof_usage = null khi proof bank rỗng (không tính vào ngưỡng).
- Web script_review: 5 thanh điểm + nhận xét ngắn + chọn 1 trong 2 hook.

### M1-4 — Dựng phim theo luồng
M1-4a (producer/focus_plan):
- Hero frame (theo quyết định mặc định). Hook = 1.5–2.5s quanh hero frame, framing tight/medium.
- Shot theo câu thoại: mỗi cụm captions là một shot; đầu shot phải có thay đổi hình (đổi tiêu điểm, punch-in +8–12% trong 6 frame, hoặc cắt sang đoạn kế); không shot nào > 3.0s không đổi hình.
- Chặn khung hình chết: đoạn gần đồng màu / trang trắng / spinner / skeleton > 300ms → cắt (như dead-time) hoặc giữ khung có nội dung kế tiếp; dead_frames_ms = 0 trong video cuối.
- Giới hạn zoom quá sát: framing tight sao cho tiêu điểm + 1 phần tử ngữ cảnh gần nhất (label, heading) vẫn trong khung; ghi số lần áp giới hạn.
- Thẻ chữ toàn màn hình (không có hình sản phẩm rõ): ≤ 3s mỗi thẻ, tổng ≤ 15%.
M1-4b (template DesktopFocus):
- Kinetic text: on_screen_text xuất hiện theo từ (pop + scale 0.85→1, so le 60–90ms/từ) đúng mốc lời đọc; từ khóa tô màu highlight.
- Stat callout: số lớn màu highlight + nhãn nhỏ, bật nhẹ ở 30% đầu scene, góc không che tiêu điểm (đổi góc nếu giao).
- Trước/sau: chia đôi khung media: trái = khung đầu luồng (form trống/trang trước thao tác), phải = hero frame; nhãn nhỏ; ≤ 3s; chỉ tạo khi có cặp khung phù hợp.
- CTA: nền là hero frame hoặc khung đẹp nhất của trang chính (logo + nội dung), không vùng trắng/biểu đồ bị cắt; nút CTA template + domain; zoom nhẹ vào logo/nút thật nếu resolve được.

### M1-5 — Marketing scorecard (app/producer/scorecard.py)
Chấm sau render, ghi report.json, hiển thị ở video_review trên web (đạt/không đạt): hook_visual (0–2s có tiêu điểm tight/medium + on_screen_text ≤ 5 từ), max_static_shot_s ≤ 3.0, dead_frames_ms = 0, fullscreen_text_ratio ≤ 15% và mỗi thẻ ≤ 3s, critic hook/benefit/cta ≥ 7, proof_used (khi proof bank không rỗng), footage_ratio ≥ 0.6, steps_in_clip ≥ 80%, audio_present = "chưa có (M2)" (không tính).

### M1-6 — Nghiệm thu
- Chạy lại 3 luồng R4: OrangeHRM "Thêm nhân viên mới" (requires_login, Admin/admin123, stop), squoosh nén + so sánh, todomvc "lên danh sách việc" (allow).
- Mỗi video: contact sheet 16 frame, bảng so sánh lời đọc cũ/mới từng scene, 2 hook options + phương án được chọn, điểm critic trước/sau, scorecard đầy đủ, con số dùng trong video kèm nguồn, still hook. Đường dẫn tuyệt đối video.
- pytest -n auto 3 lần liên tiếp 0 fail, ruff, codegen-check, tsc + vitest pass. Cập nhật docs/HANDOFF.md mục 5–7. Commit và dừng.

### PROMPT "COPY CRITIC" (prompts/copy_critic.md)
Bạn là giám đốc sáng tạo chuyên short video marketing (TikTok/Reels/Shorts) cho sản phẩm phần mềm. Hãy chấm kịch bản dưới đây một cách khắt khe và đưa gợi ý sửa cụ thể. Trả về json.

<persona_and_flow>
Persona: {{ persona }}
Mục tiêu của persona: {{ goal }}
Giá trị cốt lõi: {{ value }}
Các chương của luồng: {{ chapters_summary }}
</persona_and_flow>

<proof_bank>
{{ proof_bank_json_or_empty }}
</proof_bank>

<script>
{{ script_compact_json }}   {# headline, hook (voiceover, on_screen_text), mỗi scene: id, chapter, voiceover, on_screen_text, stat; cta #}
</script>

## Tiêu chí (0–10, 10 là xuất sắc)
1. hook_strength: 12 từ đầu có khiến persona dừng lướt không? Cụ thể, đánh trúng nỗi đau hoặc kết quả hấp dẫn; không chung chung, không mở bằng tên sản phẩm.
2. benefit_clarity: mỗi chương có nói rõ persona ĐƯỢC GÌ (thời gian, công sức, kết quả) thay vì kể lại thao tác không?
3. proof_usage: có dùng số liệu/câu trích/ưu đãi THẬT trong proof_bank một cách tự nhiên không? (proof_bank rỗng → trả null)
4. cta_strength: CTA có hành động cụ thể + lý do làm ngay (ưu đãi thật) + dễ nhớ không?
5. flow: mạch kể có liền từ nỗi đau → hành trình → kết quả, câu nối tự nhiên, nhịp ngắn gọn, không sáo rỗng không?

## Quy tắc
- Chấm dựa trên nội dung thực tế, không khen chung chung. Điểm ≥ 7 nghĩa là có thể đăng được.
- Mỗi tiêu chí kèm reason 1 câu.
- weak_scenes: liệt kê scene (id) cần sửa, mỗi scene kèm gợi ý cụ thể có thể làm theo ngay (ví dụ đề xuất câu thay thế ≤ 25 từ), chỉ dùng thông tin có trong persona_and_flow và proof_bank — không bịa số liệu.
- Phát hiện cụm sáo rỗng hoặc con số không có trong proof_bank → ghi vào issues.

## Đầu ra
Chỉ trả về json:
{
  "scores": {
    "hook_strength": {"score": int, "reason": str},
    "benefit_clarity": {"score": int, "reason": str},
    "proof_usage": {"score": int | null, "reason": str},
    "cta_strength": {"score": int, "reason": str},
    "flow": {"score": int, "reason": str}
  },
  "weak_scenes": [ {"scene_id": str, "problem": str, "suggestion": str} ],
  "issues": [ str ],
  "summary": str
}
