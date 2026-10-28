Trả lời bằng tiếng Việt, báo cáo ngắn (≤ 30 dòng). Lượt FIX-LIVE: sửa 2 lỗi gặp khi test live trên web. BƯỚC ĐẦU: lưu nguyên văn tin nhắn này vào docs/plans/fix-live.md, commit. Áp dụng "Chính sách kiểm thử": mỗi commit T0; KHÔNG chạy T3 (tôi sẽ tự test lại qua web); toàn bộ pytest -n auto 1 lần ở cuối. Lệnh dài chạy nền thì dùng monitor (timeout ≤ 20 phút). Chỉ dừng khi có lỗi chặn hoặc xong.

## Lỗi 1 — AttributeError: 'CoreFlow' object has no attribute 'chapters' (làm trước)
Giao diện web hiện "Lỗi không mong đợi: AttributeError: 'CoreFlow' object has no attribute 'chapters'" khi chạy job live (chế độ Core Flow mặc định).
1. Tìm job lỗi gần nhất trong services/api/out/jobs/ (state.json status failed), đọc traceback đầy đủ (log/state), xác định dòng code và bước pipeline gây lỗi.
2. Nguyên nhân dự đoán: chapters thuộc FlowRun (flow_run.json), không thuộc CoreFlow (core_flow.json); một chỗ nào đó (ví dụ bước marketing brief, outline_from_flow, budget/thời lượng đề xuất, hoặc nhánh resume/luồng do người dùng tự mô tả/luồng thay thế sau "không khả thi") đang đọc core_flow.chapters. Sửa đúng nguồn dữ liệu (lấy từ flow_run đã duyệt), không vá bằng getattr mặc định.
3. Rà toàn bộ code: grep mọi truy cập .chapters, .steps, .sample_data, .live trên đối tượng CoreFlow; sửa hết các chỗ dùng sai kiểu tương tự.
4. Bật kiểm tra kiểu (mypy hoặc pyright, đã có cấu hình thì dùng) cho các package app/flows, app/proposal, app/pipeline, app/script; sửa các lỗi kiểu tìm được liên quan CoreFlow/FlowRun; thêm bước này vào T0 khi đụng các package đó.
5. Test hồi quy: chạy pipeline giả (ScriptedFrontend + FakeLLM + phiên trình duyệt giả) đi qua các nhánh: luồng Discovery đề xuất; luồng người dùng tự mô tả; luồng thay thế sau "không khả thi"; có và không có marketing brief; resume từ bước script — không nhánh nào được truy cập chapters trên CoreFlow.
6. Lỗi không mong đợi trên web: thông báo phải kèm bước đang chạy + mã job + nút "Chạy tiếp" (resume từ bước lỗi sau khi sửa code); traceback đầy đủ chỉ ghi vào log của job, không hiển thị cho người dùng.

## Lỗi 2 — Vòng lặp "Phiên đăng nhập đã hết hạn" (https://aisoeasy.co)
Cờ "Tính năng chính nằm sau đăng nhập", cách A (cửa sổ đăng nhập): tôi đăng nhập thành công 3 lần (bấm "Tôi đã đăng nhập xong"), nhưng bước Khám phá vẫn hiện "Phiên đăng nhập đã hết hạn", trang đăng nhập https://aisoeasy.co/login — lặp vô hạn. Site có "Sign up with Google".
1. Chẩn đoán bằng dữ liệu job đó (không đoán): sau login_done, storage_state có bao nhiêu cookie, của domain nào, localStorage có key nào; URL của cửa sổ đăng nhập lúc bấm xong (app_home_url); verify_session mở URL nào và vì sao kết luận chưa đăng nhập (redirect về login? thấy input password? 401?); lúc Khám phá thì trang nào phát LoginRequired. Kiểm tra site lưu phiên trong IndexedDB/sessionStorage (Firebase/Supabase/đăng nhập Google) — storage_state mặc định không lưu các thứ này. Ghi kết quả vào docs/login-acceptance/aisoeasy-loop.md.
2. Sửa theo nguyên nhân, áp dụng chung (không sửa riêng site):
   - Cách A: giữ profile của cửa sổ đăng nhập (launch_persistent_context, thư mục profile trong job) và dùng CHÍNH profile đó (headless) cho verify, explore, flow agent, recorder thay vì chỉ storage_state. Nếu buộc dùng storage_state thì bật lưu IndexedDB (storage_state(indexed_db=True) nếu bản Playwright hỗ trợ; nếu không thì nâng Playwright) và tự lưu + khôi phục sessionStorage của origin bằng init script. Chú ý: persistent context không mở được 2 lần cùng lúc — mỗi bước mở/đóng tuần tự, hoặc sao chép profile cho từng context.
   - verify_session và LoginGate dùng app_home_url (URL thực tế sau đăng nhập, có thể khác domain/subdomain), không dùng landing; form đăng nhập nhỏ/ẩn/modal trên landing không được coi là "chưa đăng nhập". Mapper khi có phiên bắt đầu khám phá từ app_home_url.
   - Chặn vòng lặp: verify thất bại ngay sau login_done 2 lần liên tiếp → không hỏi lại; hiển thị thẻ lỗi giải thích cụ thể (phiên thiếu ở đâu, URL bị đẩy về) + gợi ý (tài khoản demo, nhập URL trang bên trong app) + nút "Tiếp tục với phần public".
   - Vòng đời profile: xóa khi job done/cancelled như storage_state; không phục vụ qua /files.
3. Test (T0): fixture site lưu phiên trong IndexedDB; fixture lưu trong sessionStorage; app ở subdomain khác landing; landing có form đăng nhập ẩn/modal; verify thất bại 2 lần → thẻ lỗi, không lặp.

## Cuối lượt
pytest -n auto 1 lần, ruff, codegen-check, kiểm tra kiểu các package ở Lỗi 1 mục 4, tsc + vitest pass. Báo: nguyên nhân gốc của từng lỗi (1–2 câu), file đã sửa, test mới. Cập nhật docs/HANDOFF.md mục 5 và 7. Commit và dừng.
