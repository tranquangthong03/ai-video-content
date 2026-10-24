# Short Video AI — URL-to-Marketing-Video

## Sản phẩm
Người dùng nhập URL website (+ tài khoản demo tùy chọn). Hệ thống tự đăng nhập (hoặc cho user tự đăng nhập qua live view noVNC), khám phá website, hỏi lại user về mục tiêu/tính năng cần review, sinh kịch bản video dạng JSON, gửi bản tóm tắt cho user duyệt hoặc sửa (lặp tới khi duyệt), sau đó tự quay màn hình bằng Playwright, lồng tiếng TTS, dựng bằng Remotion và xuất MP4 dọc 9:16 cho TikTok/YouTube Shorts.

## Tech stack (đã chốt, không tự ý thay)
- apps/web: Next.js (App Router) + TypeScript + Tailwind + shadcn/ui + @remotion/player, pnpm
- services/api: Python 3.12, uv, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, PostgreSQL, LangGraph (+ langgraph-checkpoint-postgres), Celery + Redis, Playwright (Python), boto3 (MinIO), cryptography (Fernet)
- LLM: DeepSeek qua SDK `openai` với base_url từ env DEEPSEEK_BASE_URL, model từ env DEEPSEEK_MODEL. Luôn dùng response_format={"type":"json_object"}, validate bằng Pydantic, nếu lỗi gửi lỗi lại cho model sửa tối đa 2 lần. Prompt gửi model phải chứa từ "json".
- TTS: ElevenLabs (word timestamps)
- apps/render: Node 20+, Remotion + @remotion/renderer + Express + Zod, pnpm
- Hạ tầng: Docker Compose (postgres, redis, minio, browser-vnc, api, worker, render, web)

## Kiến trúc & quy tắc phụ thuộc
- packages/script-schema/schemas/*.json là NGUỒN SỰ THẬT DUY NHẤT cho: Script, Theme, Scene, InteractionRequest, UserResponse, EditOp. Pydantic (services/api/app/schemas/generated) và Zod (apps/render/src/generated, apps/web/lib/generated) được SINH TỰ ĐỘNG bằng `make codegen`. KHÔNG sửa tay file generated.
- Python: api routers → graph → domain modules (session, explorer, clarifier, script, media, recorder, producer) → core | browser | llm | jobs | interaction; browser chỉ phụ thuộc core (và app/schemas generated). Domain module không import lẫn nhau; chỉ graph và producer được điều phối nhiều module. core và browser không import domain.
- app/browser là tầng hạ tầng trình duyệt dùng chung cho explorer và recorder: blacklist, request guard, session, page_utils (cookie banner, blocker), urls, locate (LocatorSpec + resolve), enter_policy. Không đặt logic trình duyệt dùng chung ở nơi khác.
- Scene là discriminated union theo "type" (HookScene, FeatureDemoScene, BeforeAfterScene, CtaScene), additionalProperties:false. Field "feature" chỉ có ở feature_demo; before_text/after_text chỉ có (và bắt buộc) ở before_after.
- LAYOUTS_BY_TYPE và FIELDS_BY_TYPE được sinh tự động từ scene.json; mọi kiểm tra layout/field theo type phải dùng bảng này, không hardcode.
- `make codegen-check` phải pass trước khi commit; `make test` đã gọi nó.
- Docker build context của render/web là repo root.
- Mọi tương tác với user đi qua cặp InteractionRequest (kind: clarify | login_required | script_review | video_review) và UserResponse (action: answer | approve | edit | regenerate | revert | login_done | cancel).
- Mọi chỉnh sửa kịch bản quy về danh sách EditOp (set, rewrite, delete, insert, move, set_theme, set_global), được áp dụng tất định bằng code; LLM chỉ dùng để lập kế hoạch (Edit Planner) và viết lại scene (Scene Writer).
- Job state: CREATED, LOGGING_IN, WAIT_USER_LOGIN, EXPLORING, CLARIFYING, SCRIPTING, AWAIT_APPROVAL, REVISING, PRODUCING_TTS, PRODUCING_DRY_RUN, PRODUCING_RECORDING, PRODUCING_RENDERING, DONE, FAILED, CANCELLED.

## An toàn (bắt buộc)
- Credential tài khoản demo luôn mã hóa Fernet, không log, xóa sau khi job kết thúc.
- Recorder/explorer không bao giờ click phần tử có text/aria khớp blacklist: xóa, delete, remove, thanh toán, pay, checkout, mua, buy, gửi, send, đăng xuất, logout, hủy tài khoản. Chỉ điều hướng trong cùng domain, tối đa 15 trang khám phá.

## Phạm vi MVP
1 renderer (Remotion), 4 scene type (hook, feature_demo, before_after, cta) × 2 layout, 2 motion preset (energetic, calm), 2 caption style (tiktok_bounce, minimal), video 30–60s, 3–6 scene, login username/password đơn giản + fallback noVNC, tải MP4 về (không auto-post). Sửa ở video_review thì render lại toàn bộ.

## Quy ước code
- Python: Ruff, type hints đầy đủ, pytest. TypeScript: strict mode, ESLint.
- Comment code bằng tiếng Anh. Văn bản hiển thị cho user bằng tiếng Việt.
- Không hardcode secret; mọi cấu hình qua .env (có .env.example).
- Sau mỗi thay đổi lớn: chạy lint + test, báo cáo kết quả.

## Môi trường
- Dự án chạy trên Windows: CLI phải ép UTF-8 cho stdout/stderr (`reconfigure(encoding="utf-8")`), nếu không khi redirect ra file thì codepage cũ (cp1258/cp1252) làm crash với tiếng Việt và ký tự như "→".
- Blacklist chỉ áp dụng cho phần tử được click/hover, không áp dụng cho text được gõ (gõ "Mua sữa" vào ô nhập là hợp lệ).

## Lệnh thường dùng
- make up / make down: chạy/dừng docker compose
- make codegen: sinh Pydantic + Zod từ JSON Schema
- make codegen-check: kiểm tra file generated không lệch so với schema
- make test: chạy toàn bộ test
- make lint
