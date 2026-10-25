**NGÔN NGỮ: Mọi tin nhắn, báo cáo, kể cả tin báo trạng thái ngắn, đều viết bằng tiếng Việt.**
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
- Python: api routers → graph → domain modules (session, explorer, clarifier, script, media, recorder, producer) → core | browser | llm | jobs | interaction; browser chỉ phụ thuộc core (và app/schemas generated). Domain module không import lẫn nhau; chỉ graph và producer được điều phối nhiều module. core và browser không import domain. core/timing.py chứa ước tính thời lượng lời đọc (hàm thuần) và interface SpeechTiming; media/ (TTS sau này) implement interface đó. Logic dùng chung giữa các domain (ví dụ `core/demo_steps.py`) đặt ở core.
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
- Quay video: viewport 1440×900 (mặc định `script.capture`), explorer vẫn 1920×1080. Đã thử quay 2x (Playwright `record_video` với device_scale_factor 2 và CDP screencast): cả hai đều không cho ảnh 2x thật (xem docs/visual-v2/spike-2x/README.md) nên clip là 1440×900, chữ khi zoom bị phóng từ nguồn 1440 px. Mỗi thao tác chính có `hold` 1,5s và tối đa 3 thao tác chính mỗi scene; recorder ghi `focus_log` (bbox tiêu điểm) cho camera.
- Hình ảnh (docs/visual-v2): template mặc định `desktop_focus` (khung 4:5, camera "focus-first" tính theo đơn vị cover, min 1,0 max 1,4, mọi hằng số ở `apps/render/src/camera/config.ts`); cảnh thao tác không bao giờ tăng tốc (cắt đoạn chết bằng ffmpeg ở producer), chỉ cảnh cuộn/chỉ vị trí tới 1,15x; hook/CTA là clip trang chủ; trang phụ (đăng nhập/đăng ký/thanh toán...) không được làm đích quay (`core/subpages.py`); `--capture WxH` đổi kích thước quay; `SHARPEN_AMOUNT` chỉnh độ nét cuối (mặc định 0,5).
- Blacklist chỉ áp dụng cho phần tử được click/hover, không áp dụng cho text được gõ (gõ "Mua sữa" vào ô nhập là hợp lệ).

## Lệnh thường dùng
- make up / make down: chạy/dừng docker compose
- make codegen: sinh Pydantic + Zod từ JSON Schema
- make codegen-check: kiểm tra file generated không lệch so với schema
- make test: chạy toàn bộ test
- make lint

## Web demo (API + UI)
- Web và CLI dùng chung `run_job` (services/api/app/pipeline/runner.py); CLI chỉ là frontend terminal. Tiến độ ghi ở `job-dir/state.json`.
- `FileFrontend` chặn thread chờ phản hồi (`pending.json` → `responses/<interaction_id>.json`) — chỉ phù hợp khi chạy 1 job một lúc. Khi cần nhiều job song song sẽ chuyển sang resume theo bước (LangGraph).
- API: `cd services/api && uv run uvicorn app.api.main:app --port 8000` (job ở `out/jobs/<id>/`, đổi bằng env JOBS_DIR). Khởi động lại thì job running/waiting thành failed "Máy chủ đã khởi động lại"; nút "Chạy tiếp" dùng resume.
- Pipeline URL → video (không TTS), trong services/api: `uv run python -m app.pipeline.explore_cli --url <url> --job-dir out/<job> [--auto --answers tests/fixtures/answers/<x>.json] [--from-step explore|script|produce] [--stop-after outline|script|produce]`. Sinh `outline_approved.json`, `scripts/v{n}.json`, `script_approved.json`, `video.mp4`, `report.json` trong job-dir (`out/` bị gitignore).
- Render: `pnpm --filter render render:sample` (mẫu), `scripts/render-job.ts <props.json> <out.mp4>` (do producer gọi; asset là file local, phục vụ qua http cục bộ).

## Core flow (luồng chức năng chính)
- Mặc định (CLI) job quay MỘT luồng chính thay vì tính năng rời rạc: `select_flow` (Flow Discovery, `app/flows/discovery.py`) → Flow Agent chạy luồng trên một phiên (`app/flows/agent.py`, mỗi vòng 1 hành động JSON, ảnh viewport nếu role `flow_agent` bật vision) → `flow_storyboard_review` → outline theo chương (`app/proposal/flow_outline.py`) → script (`script.flow_id`, scene `chapter_id`) → quay MỘT mạch (`app/recorder/flow.py`) rồi cắt theo chương. `--classic` quay lại đường cũ (chọn tính năng); đường cũ cũng là fallback khi không tìm/chạy được luồng. API/web tạm dùng đường cũ (`core_flow=False` trong worker) tới khi có thẻ web (C11).
- Chính sách gửi dữ liệu: mặc định `stop` (không bấm Gửi/Lưu; bước cuối là hover + highlight nút). `allow` cần tick xác nhận, tối đa 2 lần bấm, trong `guard.allow_writes()`; luôn bị từ chối trên site demo dùng chung (`core/shared_demo.py`, env `SHARED_DEMO_SITES`).
- Cấu hình model theo vai trò: `app/llm/router.py` (`get_client(role)`, env `LLM_<ROLE>_MODEL/_VISION/_PROVIDER`).

## Đăng nhập (web)
- Phát hiện cần đăng nhập (`app/browser/auth_detect.py`): ô password hiển thị, redirect tới path login, HTTP 401/403 → `InteractionRequest` kind `login_required` (payload `login`: login_url, reason, methods). Khi phiên hết hạn giữa chừng chỉ làm lại đúng bước/scene đang dở. Người dùng có thể báo trước bằng checkbox «Tính năng chính nằm sau đăng nhập» / `--requires-login`.
- Ba cách: A cửa sổ Chromium thật (`app/session/browser_login.py`, `POST /api/jobs/{id}/login/browser`; **chỉ dùng được khi API chạy cùng máy với người dùng — bản demo local**; `LOGIN_BROWSER_HEADLESS=1` chỉ cho test), B tài khoản demo (`app/browser/login.py`, mã hóa Fernet bằng `CREDENTIAL_ENCRYPTION_KEY`, `credentials.enc`), C upload `auth.json`. Mọi phiên đều được kiểm tra bằng context headless mới (`app/session/gate.py`).
- Credential không bao giờ ghi vào log/report/state/history (`pipeline/asker.py` che các trường bí mật); `storage_state.json`, `credentials.enc`, `login_profile/` không phục vụ qua `/files` và bị xóa khi job kết thúc (job cũ hơn 24 giờ: dọn khi API khởi động).
- Guard: POST chỉ được phép trong pha đăng nhập (`guard.allow_login_posts()`) tới domain gốc, subdomain auth./login./accounts. và nhà cung cấp xác thực phổ biến.
- Blacklist: các từ gốc (xóa, delete, pay, buy...) khớp chuỗi con; nhóm hành động tài khoản (invite/mời + đối tượng người, upgrade/nâng cấp, revoke/thu hồi, share access, generate key...) khớp theo từ/cụm và chỉ áp cho phần tử tương tác (`ElementInfo.interactive`), nên CTA «Mời bạn dùng thử» và tiêu đề «Upgrade your workflow» không bị chặn nhầm.
- Khi có phiên: làm mờ email/số điện thoại/avatar (`app/browser/privacy.py`, tắt bằng `BLUR_PERSONAL_DATA=0`), không khám phá/quay trang settings/billing/admin..., không `goto` trang logout.

## Ngôn ngữ làm việc
Luôn trả lời và viết báo cáo bằng tiếng Việt.
