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

## Cấu trúc repo
```
apps/web                 Next.js UI
apps/render              Remotion render service
services/api             FastAPI + Celery worker
packages/script-schema   JSON Schema (nguồn sự thật)
infra/                   docker-compose, browser-vnc (Chromium + noVNC + CDP)
```
# ai-video-content
