# Nghiệm thu OrangeHRM (https://opensource-demo.orangehrmlive.com, Admin / admin123)

Chẩn đoán nguyên nhân gốc: `orangehrm-diagnosis.md`. Driver: `services/api/scripts/acceptance_orangehrm.py`
(`main`, `expired`); bảng cảnh: `services/api/scripts/orangehrm_report.py` → `orangehrm-scenes.md`.
Site demo dùng chung: không tạo/sửa/xóa dữ liệu (request guard chỉ cho phép POST của pha đăng nhập).

## Nguyên nhân gốc (đã xác định ở bước A)
Phiên đăng nhập bị **xóa sớm**: commit L5 dọn `storage_state.json` cả khi job `failed`. Lần chạy đầu thất bại ở bước script
(lỗi 1: badge dài 25 ký tự) → «Chạy tiếp» chạy không có phiên → recorder không biết mình cần đăng nhập → quay trang Login và vẫn xuất video.
Không phải do phiên hết hạn phía máy chủ: phiên OrangeHRM sống ≥ 13 phút (xem dưới).

## Đã sửa
| | |
|---|---|
| F1 | giới hạn hình thức (ký tự/từ/dòng/icon) không bao giờ làm hỏng job: cắt tất định + `auto_trimmed:` trong report; chỉ lỗi cấu trúc mới hỏi «Sinh lại» |
| F2 | chỉ xóa phiên/credential khi job `done` hoặc `cancelled` (CLI và web); job lỗi giữ 24 giờ |
| F3 | `verify_session` trước khi quay; hết hạn → tự đăng nhập lại (có tài khoản demo) hoặc thẻ «Phiên đăng nhập đã hết hạn trong lúc bạn duyệt kịch bản…»; `app_home_url` được lưu; `perform_login` chờ SPA chuyển trang (trước đó báo sai «sai mật khẩu» dù đã vào) |
| F4 | recorder / chụp ảnh của job có phiên không bao giờ quay hoặc chụp trang đăng nhập (kể cả khi mất file phiên), quay lại đúng scene sau khi đăng nhập |
| F5 | quality gate: ≥ 2/3 thời điểm (đầu/giữa/cuối) là trang đăng nhập → thử đăng nhập lại, vẫn vậy thì DỪNG, không render |
| F6 | giữ phiên sống khi job chờ người dùng (4 phút/lần, `KEEPALIVE_SESSION=0` để tắt; chỉ trong luồng web) |
| F8 | tìm phần tử bằng chữ của chính trang (evidence quote, tên trong ngoặc, menu), khớp cụm từ đầy đủ; không còn hover vào chữ rời «khiển», «bảng»; link menu sang trang khác → cảnh điều hướng; không tìm được → `no_target` + ảnh trang |
| thêm | recorder chờ tới 10 s cho widget tải muộn (lần chạy 1: Quick Launch còn quay vòng tải → 4/6 cảnh thành ảnh); làm mờ cả tên người dùng ở dropdown header; sau đăng nhập khám phá cả domain (không chỉ path của trang đầu) |

## Lần chạy 1 (trước khi sửa chờ widget): `out/v3/orangehrm_run1`
- Đăng nhập tự động bằng tài khoản demo OK, khám phá từ `/web/index.php/dashboard/index`, **0 cảnh là trang đăng nhập**.
- Nhưng chỉ 1/6 cảnh là clip thật: các nút «Apply Leave»/«Leave List» chưa xuất hiện lúc quay (widget đang quay vòng tải).
  Ảnh lỗi `produce/errors/s2_action_2__click.png` cho thấy phiên đúng (đã vào dashboard, tên người dùng hiện) → sửa bằng chờ 10 s.

## Lần chạy 2 (kết quả chính): `E:\WORK SPACE\AI-video-content\services\api\out\v3\orangehrm\video.mp4`
- 32,9 s, 1080×1920 h264 yuv420p 30 fps. Contact sheet: `orangehrm-contact-sheet.png`. Bảng cảnh: `orangehrm-scenes.md`.
- Cờ `requires_login`, cách B (Admin / admin123), 2 tính năng (Dashboard/Quick Launch, Leave), thời lượng đề xuất 30 s.
- **Chờ 6 phút 20 giây ở bước script_review** (frontend kịch bản có delay) rồi duyệt.

| Chỉ số | Kết quả |
|---|---|
| Cảnh là trang đăng nhập | **0** |
| Cảnh quay thật / tổng cảnh | 3 / 5 sau khi bỏ trùng (6 ban đầu; s3 bị bỏ vì trùng hình s2). 2 cảnh còn lại là ảnh có chủ đích (hook, before_after) |
| Cảnh demo quay thật hiển thị đúng trang (URL trong `frame_inventory`) | 2/2 (cùng `/web/index.php/dashboard/index`) |
| Cảnh `no_target` | **0** |
| Request ghi dữ liệu ngoài pha đăng nhập | **0** (`request_guard`: `allowed = {}`, 6 POST telemetry `events/push` bị chặn) |
| Trang nhạy cảm | `/admin/viewAdminModule` nằm trong `sensitive_skipped`, không truy cập |
| Phiên sau khi chờ | `verify_before_produce: ok` lúc 14:40:59 (đăng nhập 14:27:26 → sống ≥ 13 phút) nên không cần đăng nhập lại; đường «hết hạn» được kiểm bằng lượt C bên dưới và test tự động |
| Dữ liệu cá nhân ở header | làm mờ (xem contact sheet: vùng avatar/tên ở góc phải trên cùng) |

`login_log.json` của job: `login_required (requested)` 14:27:07 → `verify_session ok` 14:27:26 → `verify_before_produce ok` 14:40:59.

## Lượt cách C: phiên đã mất cookie đăng nhập: `out/v3/orangehrm_expired`
Lưu phiên thật, xóa cookie `orangehrm` trong file, chạy bước produce:
- `verify_before_produce: ok=false` (mở dashboard bị đẩy về `/auth/login`) → hiện thẻ `login_required`,
  `reason = session_expired_review`, thông điệp «Phiên đăng nhập đã hết hạn trong lúc bạn duyệt kịch bản, vui lòng đăng nhập lại để quay video.»
- Không có tài khoản/phiên mới → hủy → **không có video** (`video.mp4` không tồn tại).

## Hạn chế còn lại
- Cảnh điều hướng bằng menu (`goto` → click mục «Leave» → trang Leave) đã có test tự động nhưng lần chạy này LLM chọn tính năng mà cả hai cảnh nằm trên
  dashboard nên chưa quay một cảnh chuyển trang thật trên OrangeHRM.
- `KEEPALIVE_SESSION` không được thử trên site thật (driver chạy kiểu CLI, không có FileFrontend); có test tự động.
- Script viết hai cảnh cho cùng một tính năng (`dashboard_overview`); cảnh thứ hai bị bỏ vì trùng hình với cảnh đầu (hết section để đổi), nên video còn 5 cảnh.
