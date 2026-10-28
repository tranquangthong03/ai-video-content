# Vòng lặp «Phiên đăng nhập đã hết hạn» (aisoeasy.co)

Chẩn đoán từ dữ liệu hai job thật (`out/jobs/j96c5557c51`, `out/jobs/jc92f9c78b3`: `login_log.json`, `interactions.jsonl`, `job.json`). `storage_state.json` đã bị xóa khi hủy job nên số cookie/key localStorage không đọc lại được; kết luận dựa trên nhật ký kiểm tra.

## Dữ liệu

| Quan sát | Job j96… | Job jc92… |
|---|---|---|
| `verify_session` sau mỗi lần «Tôi đã đăng nhập xong» | ok ×4 (mở `/` hoặc `/login`, **kết thúc ở `/quangthong-be/app`**) | ok ×2 (mở `/privacy`, `/login` → `/quangthong-be/app`) |
| `app_home_url` lưu vào `job.json` | `https://aisoeasy.co/login` | `https://aisoeasy.co/privacy` |
| `login_url` của thẻ đầu | `/login` | `/privacy` (chọn nhầm trang, không phải trang đăng nhập) |
| Thẻ `session_expired` kế tiếp | `target_url` = `/login` (3 lần) | `target_url` = `/login`, sau 8 trang khám phá |
| Đăng nhập lại bằng tài khoản demo | «Sai thông tin» (site chỉ có Google) | – |

## Nguyên nhân

1. **Phiên không hỏng.** Kiểm tra bằng context mới chỉ với `storage_state` vào được `/quangthong-be/app` mọi lần, nên cookie/localStorage (Supabase) đã đủ; IndexedDB/sessionStorage không phải nguyên nhân ở site này.
2. **Trang bắt đầu sai.** `LoginGate.finish` ưu tiên URL cuối của cửa sổ đăng nhập (`login_result.json`) hơn nơi kiểm tra kết thúc. Cửa sổ còn đang ở `/login` hoặc `/privacy` (đăng nhập qua popup Google) nên `app_home_url` thành trang đăng nhập; Khám phá mở đúng `/login` và coi mọi dấu hiệu đăng nhập là «hết hạn». Ở `/privacy` thì kiểm tra không chứng minh được gì (trang công khai).
3. **Liên kết tới `/login` bị coi là hết hạn.** Khi đã có phiên, `mapper.visit` ném `LoginRequired("session_expired")` cho *bất kỳ* trang nào có dấu hiệu đăng nhập, kể cả liên kết «Log in» ở header dẫn tới `/login`.
4. **Không có chốt chặn.** Mỗi lần ném lại đều hỏi lại thẻ giống hệt, vô hạn (tới `MAX_SIGN_INS`).

## Sửa (chung, không riêng site)

| Việc | Chỗ sửa |
|---|---|
| Trang bắt đầu = nơi kiểm tra kết thúc; URL cửa sổ chỉ dùng khi kiểm tra không thấy chuyển hướng và không phải trang đăng nhập | `app/session/gate.py::finish` |
| Trang thật sự là trang đăng nhập thì kiểm tra nó (nó đẩy khách đã đăng nhập vào app), ngược lại kiểm tra trang đích | `finish` |
| Liên kết tới trang đăng nhập khi đã có phiên: bỏ qua (`login_page`), chỉ trang gốc bị đẩy về đăng nhập mới là hết hạn | `app/explorer/mapper.py::visit` |
| Chặn vòng lặp: phiên vừa qua kiểm tra mà bị đẩy về đăng nhập 2 lần (trong 5 phút), hoặc kiểm tra thất bại 2 lần liên tiếp → thẻ giải thích (đã kiểm tra mở gì, kết thúc ở đâu) + gợi ý (tài khoản demo, nhập URL trang trong app) + nút «Tiếp tục với phần public» | `gate.explain_loop`, `interaction.json` (`methods` thêm `public`), `login-card.tsx`, `runner.sign_in` |
| Tiếp tục với phần public: bỏ phiên, mở trang chủ site, `job.json` không còn `storage_state` | `runner.forget_session` |
| Lưu IndexedDB trong mọi `storage_state(...)` (Supabase/Firebase) | `browser_login.py`, `credential_login.py`, `keepalive.py` |

Không làm (chưa có bằng chứng cần): profile persistent dùng chung cho mọi bước (không thể mở 2 lần cùng lúc, và kiểm tra bằng `storage_state` đã qua), và khôi phục sessionStorage (không có trong `storage_state`, site này không dùng). Nếu một site khác vẫn lặp sau bản sửa, thẻ giải thích sẽ ghi rõ trang kiểm tra kết thúc ở đâu.

Profile cửa sổ đăng nhập (`login_profile/`) vẫn bị xóa khi job done/cancelled và không phục vụ qua `/files` (đã có từ trước).

## Test

`tests/test_login_loop.py`: trang bắt đầu lấy từ nơi kiểm tra kết thúc; kiểm tra mở trang đích; bị đẩy về 2 lần → thẻ giải thích và không hỏi lại; kiểm tra thất bại 2 lần → thẻ giải thích; hết hạn muộn không bị coi là vòng lặp; liên kết `/login` bị bỏ qua nhưng trang gốc bị đẩy về vẫn là hết hạn; form đăng nhập ẩn trên landing không phải «chưa đăng nhập»; phiên trong IndexedDB sống sót qua `storage_state(indexed_db=True)`.
