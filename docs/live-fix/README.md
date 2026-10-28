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
