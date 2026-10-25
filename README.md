# Short Video AI

Nhập URL website → hệ thống khám phá, hỏi lại, sinh kịch bản, duyệt, quay màn hình, lồng tiếng và dựng MP4 dọc 9:16. Chi tiết kiến trúc và quy ước: xem [CLAUDE.md](CLAUDE.md).

## Yêu cầu môi trường
- Docker + Docker Compose v2
- make (chạy các lệnh tắt)
- Chạy ngoài Docker: Python 3.12 + [uv](https://docs.astral.sh/uv/), Node 20+ + pnpm

## Chạy
```sh
cp .env.example .env        # điền secret (make up tự tạo nếu chưa có)
make up                     # chạy toàn bộ stack
make down
```
Chỉ chạy hạ tầng:
```sh
docker compose -f infra/docker-compose.yml up postgres redis minio browser-vnc
```
Dev (mount source + hot reload): `make up-dev`.

| Dịch vụ | URL |
|---|---|
| web | http://localhost:3000 |
| api | http://localhost:8000/health |
| render | http://localhost:3001/health |
| noVNC (live view) | http://localhost:6080 |
| Chrome CDP | http://localhost:9222/json/version |
| MinIO console | http://localhost:9001 |
| Postgres (host) | localhost:5433 |

## Chạy demo (không cần Docker)
Giao diện web đơn giản: nhập URL, trả lời/duyệt/sửa trên trình duyệt, nhận video MP4 (chưa có lồng tiếng).

Chuẩn bị một lần:
```sh
cp .env.example .env                      # điền DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
pnpm install
cd services/api && uv sync && uv run playwright install chromium && cd ../..
# cần thêm ffmpeg + ffprobe trong PATH
```
Chạy cả API và web:
```sh
pnpm dev:all        # hoặc: make demo
```
Mở http://localhost:3000. Hoặc chạy riêng: `cd services/api && uv run uvicorn app.api.main:app --port 8000` và `pnpm --filter web dev`.

- Mỗi lúc chỉ chạy 1 công việc, các công việc khác xếp hàng. Dữ liệu ở `services/api/out/jobs/<id>/` (đổi bằng biến `JOBS_DIR`).
- `NEXT_PUBLIC_API_URL` (mặc định `http://localhost:8000`) trỏ web tới API.
- Website cần đăng nhập: cứ nhập URL, hệ thống tự phát hiện và hiện thẻ «Cần đăng nhập» với 3 cách (hoặc tick «Tính năng chính nằm sau đăng nhập» ở trang chủ):
  - **Mở cửa sổ đăng nhập** (khuyến nghị): một cửa sổ Chromium thật hiện ra để bạn tự đăng nhập. **Chỉ dùng được khi API chạy cùng máy với bạn (bản demo local).** Hướng dẫn kiểm thử: `docs/manual-test-login.md`.
  - **Tài khoản demo**: nhập email/mật khẩu; mã hóa Fernet (`CREDENTIAL_ENCRYPTION_KEY` trong `.env`), xóa khi job kết thúc. Không vượt được captcha/2FA/«Đăng nhập với Google».
  - **Tải file phiên đăng nhập**: `uv run playwright codegen --save-storage=auth.json <url>` rồi tải `auth.json` lên (ở trang chủ hoặc trong thẻ).
  Chỉ dùng tài khoản demo. Khi có phiên đăng nhập, email/số điện thoại/avatar bị làm mờ trong video (`BLUR_PERSONAL_DATA=0` để tắt), các trang settings/billing/admin không được khám phá hay quay.
- Khởi động lại API thì công việc đang chạy thành «Lỗi: Máy chủ đã khởi động lại»; bấm «Chạy tiếp» để làm tiếp.
- Dùng CLI thay cho web: xem mục «Pipeline URL → video» trong [CLAUDE.md](CLAUDE.md).

## Cấu trúc repo
```
apps/web                 Next.js UI
apps/render              Remotion render service
services/api             FastAPI + Celery worker
packages/script-schema   JSON Schema (nguồn sự thật)
infra/                   docker-compose, browser-vnc (Chromium + noVNC + CDP)
```
# ai-video-content
