Trả lời bằng tiếng Việt, báo cáo NGẮN GỌN (tối đa ~30 dòng, bảng số liệu thay cho văn xuôi). Lượt "Kiểm thử theo tầng" (TEST-TIERS) — mục tiêu: giảm thời gian và chi phí token khi nghiệm thu. KHÔNG chạy lại nghiệm thu thật trong lượt này.

1. Snapshot chuẩn: tạo services/api/tests/golden/{orangehrm,squoosh,todomvc}/ từ 3 job cam-* hiện có, chỉ giữ những gì cần để chạy lại từ bước script hoặc produce mà KHÔNG gọi LLM, KHÔNG mở trình duyệt: confirmed_profile, flow_run (+ live clip đã quay và logs), outline/script đã duyệt, render_props, proof bank, frame_inventory, focus_track, report gốc. Clip video lớn: lưu ngoài git (thư mục golden-media/ trong .gitignore + script tải/tạo lại từ out/), ghi rõ trong README của golden.

2. scripts/regress.py với 3 chế độ:
   - --tier t0: chạy pytest theo marker của phần đã sửa (cho tham số --paths) + camera_preview cho 3 snapshot (đồ thị + 6 still, không render).
   - --tier t1: render lại 3 video từ snapshot (giữ nguyên script và clip), chạy Motion QA, in bảng so sánh với kết quả lưu gần nhất (docs/regress/last.json) và cập nhật file đó khi có --save.
   - --tier t2: chạy lại CHỈ bước script + critic trên snapshot (LLM_CACHE tắt cho riêng các bước này, upstream đọc từ snapshot), in điểm critic so với lần trước. Có tham số --brief <file.json> để nạp brief mẫu.
   - Mọi chế độ in tổng: thời gian, số lần gọi LLM, token (t0/t1 phải = 0 lần gọi LLM — test kiểm tra điều này).

3. Quy tắc kiểm thử (ghi vào CLAUDE.md, mục mới "Chính sách kiểm thử"):
   - Mỗi commit: T0 (test liên quan + ruff, codegen-check nếu đụng schema, tsc/vitest nếu đụng TS).
   - Sửa camera/dựng phim/template/nối cảnh: thêm T1 trước khi báo xong.
   - Sửa phần lời/prompt: thêm T2.
   - Toàn bộ pytest -n auto: 1 lần ở cuối mỗi lượt (bỏ yêu cầu 3 lần liên tiếp, trừ khi lượt đó sửa test chập chờn).
   - T3 (chạy thật từ URL, site mới): CHỈ khi tôi yêu cầu rõ, hoặc khi lượt đó sửa explorer/flow agent/recorder/login; khi đó chạy 1 site, không phải 3–6 site.
   - Đầu ra lệnh dài: chạy với -q và chỉ đọc phần tóm tắt/lỗi; không dán log dài vào ngữ cảnh. Không đọc lại toàn bộ tài liệu dài nếu không cần — đọc đúng mục.
   - Báo cáo cuối lượt ≤ 30 dòng: bảng chỉ số, việc chưa đạt, đường dẫn file. Chi tiết để trong docs/.

4. Chạy thử: regress t0 và t1 một lần trên 3 snapshot để lấy mốc (docs/regress/last.json). Báo thời gian và xác nhận 0 lần gọi LLM. Commit "test: tiered regression with golden snapshots", cập nhật docs/HANDOFF.md (mục 5 và mục quy trình), rồi dừng.
