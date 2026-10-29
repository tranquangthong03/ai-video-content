# LIVE-FIX (demoblaze, 2026-10-28)

## Chẩn đoán

**Giả thuyết A: ĐÚNG.** Guard chặn các POST đọc dữ liệu của SPA, nên trang chi tiết/danh mục trống.

Bằng chứng: `services/api/out/jobs/j0fc9c882da/explore/report.json` → `request_guard`:

| Mục | Giá trị |
|---|---|
| `blocked` | `post_default`: 9 |
| `allowed` | rỗng |
| URL bị chặn | `POST api.demoblaze.com/viewcart` ×6, `/bycat` ×2, `/view` ×1 |

`Guard.decide` (`app/browser/guard.py`): POST không phải GraphQL query, không telemetry và có đường dẫn không khớp `READ_PATH` thì rơi vào `abort post_default`. `view`, `bycat`, `viewcart` không khớp `READ_PATH`. Hệ thống không báo gì cho người dùng.

Kết luận: nguyên nhân gốc là phân loại POST quá thô và không có cảnh báo môi trường. Không có code riêng cho tên miền.

(Các mục còn lại điền khi làm xong.)

## Kết quả

### Trước / sau theo từng dòng của demo-note

| Dòng ghi chú | Trước | Sau (live demoblaze, 2 vòng) |
|---|---|---|
| Luồng được chọn | ra «Xem chi tiết» | luồng giữ `required_actions` «thêm vào giỏ hàng»; agent đi Laptops → Sony vaio i5 → dừng ở Add to cart |
| Trang chi tiết trắng | trắng (POST `/view` bị chặn) | có nội dung (ảnh `flow/steps/s5.jpg` của job `demoblaze1`); `/view`, `/bycat`, `/viewcart` qua khi do tải/điều hướng |
| Lọc Laptops vẫn ra điện thoại | POST `/bycat` bị chặn | `bycat` do điều hướng được qua (read_navigate_action); còn 1–2 lần `bycat` khi không rõ hành động vẫn bị chặn (unknown) |
| Nhãn «Đạt mục tiêu» sai | model tự đặt | `goal_status` do code: vòng 2 tính lại ra `stopped_before_submit` (xem lưu ý) |
| stop_before_submit sai ref | không kiểm | nút phải khớp nhóm hành động cam kết (cart/order/save...), sai thì từ chối |
| Agent đi vòng 15 hành động | không dừng | cùng trạng thái lần 3 → dừng stuck/env_blocked; bước không đổi trang = `no_effect` |
| Không cảnh báo môi trường | không | `env_issue guard_broke_page` + thẻ cảnh báo web/CLI (chưa gặp ca thật ở vòng live: trang đã có nội dung) |
| «Add to cart» không có trong danh sách phần tử | bị ẩn như «trang phụ» | link ở lại trang (href `#`) là hành động, không bị ẩn |
| Gợi ý sửa là ví dụ OrangeHRM | cứng | sinh từ luồng hiện tại (vitest) |
| Hộp thoại «Product added» | chưa xử lý | accept/dismiss, ghi sự kiện, agent thấy ở lượt sau (test cục bộ) |

Bảng guard_decision demoblaze vòng 2: read 9 (6 viewcart + 2 view + 1 bycat), unknown 2 (`bycat`, không có hành động gây ra), write 0 lọt, env_issue 0.

Lưu ý trung thực: vòng 2 lưu `goal_status = not_reached` vì một lỗi (từ chối hành động làm bước trước bị gắn nhầm `no_effect`); đã sửa (commit «a refused action...») và tính lại offline trên chính job đó ra `stopped_before_submit`. Chưa chạy live lần 3 (quy tắc tối đa 2 vòng).

### Tính tổng quát (explore-only, không render)

| URL | read | write | unknown | env_issue | write lọt | so với trước LIVE-FIX |
|---|---|---|---|---|---|---|
| squoosh.app | 0 | 0 | 0 | 0 | 0 | không có POST; agent give_up (clipboard) như trước |
| todomvc (react) | 0 | 0 | 0 (13 telemetry giả 204) | 0 | 0 | lần đầu bị gắn sai `blank`/`no_effect` → sửa; chạy lại: reached, 3 bước hợp lệ |
| excalidraw.com | 0 | 8 (`um.*/api/send`, bị chặn) | 0 (12 telemetry) | 0 | 0 | trước cũng bị chặn (post_default) |
| orangehrm | không chạy | | | | | cần đăng nhập, site dùng chung; chỉ có test cục bộ (không ghi lọt) |

Chưa có log guard_decision trước LIVE-FIX nên cột «so với trước» chỉ so theo quy tắc cũ (read-path theo tên). T1 (4 snapshot, replay không mở trình duyệt): mọi chỉ số Motion QA bằng lần trước.

### Kiểm tra

pytest -n auto 1105 pass + 1 test chập chờn qua khi chạy riêng; ruff sạch; codegen up to date; tsc + vitest 54; mypy: không lỗi mới ở file mới (50 lỗi cũ). Chưa chụp `docs/screenshots/60-*.png` (cần chạy web UI).
