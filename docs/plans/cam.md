## BỐI CẢNH (chẩn đoán đã xác nhận trên 3 video M1: out/m1-orangehrm, out/m1-squoosh, out/m1-todomvc)
Phân tích từng frame (ước lượng phép biến đổi affine giữa 2 frame liên tiếp trong vùng khung media, độ khác biệt frame, các đoạn đứng yên):
- N1 Snap zoom: OrangeHRM giây 7.07–7.40 tỉ lệ zoom mỗi frame 1.11→1.17→1.17→1.15→1.13… (≈3x trong 11 frame), giây 9.0 lùi ~0.86/frame; todomvc giây 6.8, 14.8, 22.6, 29.9 ≈1.8x trong ~0.3s. Nguyên nhân: spring quá cứng, không giới hạn tốc độ zoom/pan.
- N2 Đứng yên → giật → đứng yên: OrangeHRM 30 đoạn hình đứng yên tuyệt đối (dài nhất 1.9s), todomvc 33 đoạn (dài nhất 1.7s), xen giữa là zoom gắt.
- N3 Nối cảnh: squoosh 8.40→8.55→8.75 có 3 trạng thái trong 0.35s (trang chủ → khung xám ảnh đang tải lọt qua → ảnh); todomvc 7.97, 10.2, 13.17 nhảy dọc 27–47px trong 1 frame (điểm cắt nằm cạnh lúc bố cục đổi).
- N4 Tiêu điểm sai: OrangeHRM ~7.5s lời "bấm nút Add" nhưng zoom vào Reset/Search; ~26s lời "tên Nguyen Van An" nhưng zoom Cancel/Save + ô trống, chữ bị cắt ngang; 5–20s cả form thu nhỏ khi đang nhập từng ô; hook là sidebar thay vì form đã điền. squoosh zoom vào bên trong ảnh canvas (mắt/lông mèo), bảng nén bị cắt mép. todomvc ~5.5s và ~27s lùi ra thấy sidebar giữa chừng (mỗi scene tự mở bằng toàn trang).
- N5 Lời: critic benefit/CTA = 6; hook bị code cắt cụt ("…chỉ với một cú."); stat dùng mã nhân viên "0736" (không phải lợi ích); critic chưa nối router.

## D — Motion QA (làm TRƯỚC để có số liệu "trước")
- app/producer/motion_qa.py (Python, OpenCV — thêm opencv-python-headless làm dependency nếu chưa có): đọc video cuối, cắt vùng khung media theo template, mỗi cặp frame liên tiếp tính: mean abs diff (ảnh xám thu nhỏ), phép biến đổi affine (ORB + estimateAffinePartial2D, RANSAC) → scale và tịnh tiến; phân biệt điểm cắt (diff lớn) với chuyển động camera.
- Chỉ số + ngưỡng đạt: max_zoom_rate ≤ 2.5%/frame (|scale−1|, bỏ qua frame điểm cắt); max_pan_rate ≤ 1.5% bề rộng khung/frame; freeze_then_jump = 0 (đứng yên ≥ 0.4s rồi frame kế có zoom > 2.5% hoặc pan > 1.5%); flash_shots = 0 (đoạn < 0.8s giữa 2 điểm cắt); loading_frames_ms = 0 (vùng media/ảnh đồng màu xám/đen trong bbox media của frame_inventory); static_ms_max ≤ 400 (đứng yên tuyệt đối liên tục, không tính khung kết thúc); focus_text_clipped = 0 (item text của tiêu điểm giao mép cửa sổ nhìn — từ focus_track + frame_inventory); focus_match_rate ≥ 85% (tỉ lệ thời gian tiêu điểm có text khớp cụm lời đọc, hoặc là phần tử đang được thao tác/kết quả).
- Gắn vào scorecard (report.json + trang video_review). Xuất docs/cam/<site>-before.json và biểu đồ (PNG) scale/pan theo thời gian.
- Chạy trên 3 video M1 hiện có → bảng "trước" trong docs/cam/README.md.
- Công cụ xem trước lộ trình camera: scripts/camera_preview.py — từ render_props.json vẽ đồ thị zoom/pan theo thời gian + 6 still có khung tiêu điểm, KHÔNG render video (để chỉnh nhanh).

## A — Lộ trình camera (apps/render/src/camera + producer)
- Lập lộ trình TOÀN CỤC cho cả clip (keyframes từ focus_track) rồi làm mượt, thay vì spring phản ứng từng frame.
- Chuyển tiêu điểm: 400–900ms tỉ lệ với khoảng cách + mức đổi zoom, ease-in-out cubic; bắt đầu di chuyển 300–500ms TRƯỚC mốc click/gõ (biết trước từ mốc bước).
- Kẹp tốc độ cứng: zoom ≤ 2.5%/frame, pan ≤ 1.5% bề rộng/frame (nếu không kịp thì bắt đầu sớm hơn hoặc giảm mức zoom đích).
- Giữ hình: trôi nhẹ 0.5–1%/giây (zoom-in rất chậm hoặc pan nhẹ về phía tiêu điểm), không đứng yên tuyệt đối > 0.4s.
- Gộp: hai tiêu điểm cách nhau < 1.2s và gần nhau → một đường liền, không zoom ra rồi vào.
- Punch-in theo câu thoại: ≤ 6%, kéo 8–10 frame, không chồng lên lúc đang chuyển tiêu điểm.
- Liên tục giữa các scene cùng trang: establishing shot chỉ 1 lần mỗi trang; scene sau bắt đầu từ vị trí camera cuối scene trước.
- Hằng số trong camera/config.ts. Vitest cho từng quy tắc (kẹp tốc độ, bắt đầu sớm, trôi khi giữ, gộp, liên tục).

## B — Chọn tiêu điểm (producer/focus_rules, focus_plan)
- Đơn vị tiêu điểm = phần tử + nhãn của nó (ô nhập + label, nút + vùng quanh 12%). "Không cắt chữ" CHỈ áp cho chữ của chính tiêu điểm, không mở rộng ra cả form/card cha.
- Khi gõ: tiêu điểm = ô đang gõ; ô vừa điền trước đó được phép trong khung (framing medium).
- Nút gửi (stop_before_submit) chỉ làm tiêu điểm trong chương cuối, sau shot "form đã điền đầy đủ".
- Media = img, video, canvas, svg lớn (bbox ≥ 15% viewport): không bao giờ zoom vào trong; tiêu điểm chuyển sang panel điều khiển hoặc nhãn số liệu gần nhất (ví dụ dung lượng trước/sau). Recorder/frame_inventory phải gán kind media cho canvas.
- Phần tử có text khớp cụm lời đọc được ưu tiên tuyệt đối (kiểm bằng code sau Focus Planner); nhiều nút gần nhau thì chọn đúng nút được nhắc.
- Hook = hero frame đúng nghĩa (form đã điền đủ / danh sách có mục mới / kết quả nén), không phải sidebar/menu.
- Test với dữ liệu thật đã lưu của 3 job M1 (frame_inventory, focus_track): các ca N4 phải được sửa.

## C — Nối cảnh (producer/trim, dead-frame)
- Khung chết mở rộng: vùng media đang tải (đồng màu xám/đen trong bbox img/canvas), skeleton, ảnh chưa decode → cắt.
- Độ dài tối thiểu mọi đoạn giữa hai điểm cắt ≥ 0.8s; ngắn hơn thì gộp vào đoạn kề hoặc bỏ.
- Chọn điểm cắt nơi hình ổn định (khác biệt nhỏ hai bên). Khác biệt lớn (bố cục đổi, danh sách dài thêm) → crossfade 4–6 frame, hoặc đặt điểm cắt trong lúc camera đang chuyển động. Thay đổi bố cục tự nhiên do thao tác (item mới xuất hiện) giữ nguyên, không đặt điểm cắt kề nó (±300ms).
- Test thuần cho từng quy tắc.

## NGHIỆM THU (sau C)
1. Chạy lại 3 luồng cũ (OrangeHRM "Thêm nhân viên mới" stop, squoosh nén + so sánh, todomvc "lên danh sách việc" allow) → Motion QA phải đạt mọi ngưỡng; bảng trước/sau trong docs/cam/README.md + contact sheet + biểu đồ scale/pan trước/sau.
2. Tổng quát hóa — 3 site CHƯA TỪNG chạy, public, không đăng nhập, chạy --auto (luồng do Discovery đề xuất, chọn mặc định): https://excalidraw.com, https://regex101.com, https://coolors.co/generate (site nào bị chặn/không truy cập được thì thay bằng công cụ web public cùng loại và ghi lại). Báo Motion QA, scorecard, footage_ratio, steps_in_clip và các lỗi gặp phải; KHÔNG tinh chỉnh riêng cho các site này trong lượt này — chỉ ghi vào docs/cam/generalization.md để lượt sau xử lý.
3. Đường dẫn tuyệt đối mọi video.

## E — Nội dung lời (sau nghiệm thu hình)
- Hook > 12 từ: viết lại bằng LLM 1 lần thay vì cắt; vẫn lỗi mới cắt, và chỉ cắt ở ranh giới câu/cụm.
- Proof bank phân loại số: benefit (thời gian, dung lượng, lượt dùng, %, số người dùng), identifier (mã, ID, số điện thoại/email mẫu, số do agent tự nhập), other. Stat callout, hook, headline chỉ dùng benefit.
- Nối copy_critic vào router (role riêng). Scene điểm < 6 được 2 vòng rewrite; prompt rewrite kèm 2–3 ví dụ mẫu lời lợi ích/CTA tốt theo loại sản phẩm (tool, web app nội bộ, SaaS).
- Chạy lại script + render cho 3 luồng cũ, báo điểm critic trước/sau.

Cuối lượt: pytest -n auto 3 lần 0 fail, ruff, codegen-check, tsc + vitest pass; cập nhật docs/HANDOFF.md; commit và dừng.
