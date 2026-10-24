# Explorer benchmark: website understanding, concept proposal, outline review

Run with `uv run python -m app.pipeline.explore_cli --auto` (scripted answers in `services/api/tests/fixtures/answers/<site>.json`), LLM cache off, real DeepSeek calls, Playwright Chromium 1920x1080, request guard on. Every outline was edited once with a free-text instruction and then approved.

Models (from `.cache/llm-log.jsonl`): `deepseek-chat` for classify/analyze/concepts/outline (text only); `deepseek-flash` for synthesize **with screenshots (vision)**. No call needed a repair round (34 calls, all `attempts = 1`). No site fell back to text-only.

## 1. Summary

| | plausible.io | todomvc.com/examples/react/dist/ | squoosh.app |
|---|---|---|---|
| Kind of site | landing page | web app, no login | single-page tool |
| site_type (LLM) | landing | tool | tool |
| Pages seen | 15 | 6 | 1 |
| Pages skipped | 43 known URLs not visited (max_pages limit), 0 failed/blocked | 0 | 0 |
| Features (verified / total) | 6 / 8 | 6 / 8 | 6 / 7 |
| Recommended concept | Phân tích web không cookie, một trang dashboard, nhẹ tênh | Một app Todo, hàng chục framework | Nén ảnh ngay trên trình duyệt, không cần upload |
| Concept chosen | overview-no-cookie-analytics | overview-todomvc-react | overview_squoosh |
| Outline edits before approve | 1 | 1 | 1 |
| Final outline | v2, 5 beats | v2, 6 beats | v2, 5 beats |
| Vision | yes (synthesize) | yes (synthesize) | yes (synthesize) |
| Wall time | 99.5 s | 94.7 s | 60.5 s |
| Tokens (in + out) | 81970 | 24559 | 13811 |
| POST/other requests allowed | {"read_path": 14} | {} | {} |
| Requests blocked | 0 | 0 | 0 |
| Telemetry faked (204) | 0 | {"telemetry": 13} | 0 |
| Clicks performed | 7 | 4 | 0 |
| Clicks refused | 0 | 1 | 0 |

## 2. Time per step (seconds)

| step | plausible | todomvc | squoosh |
|---|---|---|---|
| classify | 1.5 | 1.38 | 1.12 |
| map | 20.56 | 20.26 | 3.47 |
| analyze | 13.69 | 6.52 | 1.98 |
| synthesize | 27.33 | 10.48 | 16.39 |
| verify | 28.34 | 48.92 | 29.58 |
| (concepts + outline + interaction) | 8.1 | 7.1 | 8.0 |
| **wall total** | 99.5 | 94.7 | 60.5 |

## 3. Tokens per step (input / output)

| step | model | plausible | todomvc | squoosh |
|---|---|---|---|---|
| classify | deepseek-chat | 466 / 145 (1 calls) | 367 / 92 (1 calls) | 379 / 74 (1 calls) |
| analyze | deepseek-chat | 34340 / 12005 (15 calls) | 5929 / 2042 (6 calls) | 782 / 343 (1 calls) |
| synthesize | deepseek-flash | 18890 / 6752 (1 calls) | 6828 / 2417 (1 calls) | 1755 / 3818 (1 calls) |
| verify | none (no LLM) | 0 / 0 (0 calls) | 0 / 0 (0 calls) | 0 / 0 (0 calls) |
| concepts | deepseek-chat | 6334 / 1088 (1 calls) | 4217 / 833 (1 calls) | 3866 / 934 (1 calls) |
| outline | deepseek-chat | 1887 / 63 (1 calls) | 1773 / 61 (1 calls) | 1798 / 62 (1 calls) |
| **total** | | 81970 | 24559 | 13811 |

## 4.1 plausible: features

`https://plausible.io` (landing page)  
Product understood as: **Plausible Analytics**, Công cụ phân tích web đơn giản, siêu nhẹ và thân thiện quyền riêng tư — giải pháp thay thế Google Analytics, không cookie, không banner đồng ý, lưu trữ tại EU.

| feature | importance | demo_score | evidence | verified |
|---|---|---|---|---|
| Dashboard một trang với các chỉ số cốt lõi (`simple-dashboard`) | 0.95 | 1.0 | 4 | yes |
| Phân tích không cookie, không cần banner đồng ý (`privacy-no-cookie`) | 0.93 | 1.0 | 5 | yes |
| Script theo dõi siêu nhẹ, giữ tốc độ tải trang (`lightweight-script`) | 0.88 | 1.0 | 4 | yes |
| Mục tiêu, sự kiện tùy chỉnh, phễu và hành trình người dùng (`goals-funnels-journeys`) | 0.85 | 1.0 | 5 | yes |
| Lưu trữ tại EU và bộ tài liệu tuân thủ (`eu-hosting-compliance`) | 0.84 | 1.0 | 4 | yes |
| Theo dõi doanh thu thương mại điện tử và chiến dịch UTM (`ecommerce-revenue-utm`) | 0.80 | 1.0 | 4 | yes |
| Nhập lịch sử Google Analytics và chuyển đổi dễ dàng (`ga-import-migration`) | 0.77 | 0.0 | 4 | no |
| Chia sẻ dashboard và xuất số liệu cho đội nhóm/khách hàng (`sharing-export-reports`) | 0.72 | 0.0 | 6 | no |

Concepts: `overview` ★ Phân tích web không cookie, một trang dashboard, nhẹ tênh; `deep_dive` Không cookie, không banner: mọi lượt truy cập đều là thật; `pain_solution` Từ rối rắm GA đến dashboard một trang trong 2 phút

Approved outline:

1. Bạn thật sự cần biết gì từ số liệu website của mình?
2. Mở công cụ ước tính: thấy rõ traffic bị ẩn khỏi Google Analytics vì người dùng từ chối banner.
3. Chuyển sang Plausible: script 2.5KB, không cookie, không banner, không làm chậm site.
4. Dashboard một trang: unique visitors, nguồn traffic, top pages, quốc gia — tất cả trong tầm mắt.
5. Dùng thử miễn phí 30 ngày, không cần thẻ tín dụng; bắt đầu tại plausible.io.

## 4.2 todomvc: features

`https://todomvc.com/examples/react/dist/` (web app, no login)  
Product understood as: **TodoMVC (React)**, Ứng dụng todo mẫu viết bằng React, đồng thời là bộ so sánh cùng một ứng dụng Todo được triển khai trên nhiều framework JavaScript.

| feature | importance | demo_score | evidence | verified |
|---|---|---|---|---|
| Tạo việc cần làm mới (`create-todo`) | 0.95 | 0.5 | 2 | yes |
| Chỉnh sửa todo bằng nhấp đúp (`edit-todo`) | 0.70 | 0.5 | 2 | yes |
| Lọc danh sách theo trạng thái (All / Active / Completed) (`filter-views`) | 0.60 | 0.5 | 2 | yes |
| Duyệt cùng một app Todo trên nhiều framework (`compare-frameworks`) | 0.60 | 1.0 | 3 | yes |
| Bản demo cập nhật theo framework ổn định mới nhất (`up-to-date-versions`) | 0.50 | 1.0 | 3 | yes |
| Dùng trong benchmark đa trình duyệt (Speedometer) (`benchmark-usage`) | 0.45 | 0.5 | 3 | yes |
| Thử framework hoặc AI coding agent với tác vụ UI vừa phải (`ai-agent-eval`) | 0.40 | 0.0 | 2 | no |
| Đóng góp một framework mới qua pull request (`contribute-framework`) | 0.30 | 0.0 | 2 | no |

Concepts: `overview` ★ Một app Todo, hàng chục framework; `deep_dive` So sánh framework trên cùng một đặc tả; `pain_solution` Chọn framework mà không phải đoán

Approved outline:

1. Bạn có hay quên việc cần làm mỗi ngày không?
2. Mở todomvc.com, chọn React, gõ việc cần làm vào ô nhập.
3. Nhấp đúp một todo để sửa ngay tại chỗ, không cần form riêng.
4. Quay lại trang chủ, mở Vue hay Svelte để so sánh cách triển khai.
5. Code mẫu luôn theo bản framework ổn định mới nhất.
6. Chọn framework bằng cách xem code thật, không đoán.

## 4.3 squoosh: features

`https://squoosh.app` (single-page tool)  
Product understood as: **Squoosh**, Trình tối ưu ảnh chạy ngay trong trình duyệt: nén ảnh, so sánh chất lượng và lưu file nhỏ hơn mà vẫn đẹp.

| feature | importance | demo_score | evidence | verified |
|---|---|---|---|---|
| Nén ảnh, giảm dung lượng file (`f_compress`) | 0.95 | 0.5 | 1 | yes |
| So sánh trước/sau và lưu tức thì (`f_compare_save`) | 0.90 | 0.5 | 3 | yes |
| Xử lý cục bộ, ảnh không rời thiết bị (`f_local_privacy`) | 0.85 | 0.5 | 1 | yes |
| Đưa ảnh vào bằng kéo-thả hoặc dán (`f_drop_paste`) | 0.80 | 0.5 | 2 | yes |
| Chỉnh cài đặt nén để có file nhỏ hơn nữa (`f_advanced_settings`) | 0.70 | 0.5 | 1 | yes |
| Nén và so sánh ảnh với nhiều codec khác nhau (`f_codec_compare`) | 0.60 | 0.5 | 1 | yes |
| Thử nhanh bằng ảnh mẫu có sẵn (`f_sample_images`) | 0.55 | 0.0 | 5 | no |

Concepts: `overview` ★ Nén ảnh ngay trên trình duyệt, không cần upload; `deep_dive` Nhìn thấy khác biệt rồi lưu trong một màn hình; `pain_solution` Ảnh quá nặng làm web chậm, sửa ngay không cần upload

Approved outline:

1. Ảnh quá nặng có đang làm trang web của bạn chậm?
2. Mở Squoosh, kéo-thả hoặc dán ảnh vào là bắt đầu ngay.
3. Xem song song ảnh gốc và ảnh nén, dung lượng tụt từ vài MB xuống vài chục KB.
4. Ảnh không rời khỏi máy — mọi thứ xử lý cục bộ trong trình duyệt.
5. Thử nén ảnh đầu tiên của bạn tại squoosh.app.

## 5. Chỗ hệ thống hiểu sai hoặc thiếu, xếp theo mức độ ảnh hưởng

"Xác nhận" = thấy trực tiếp trong dữ liệu của lần chạy; "dự đoán" = suy ra từ code và dữ liệu, chưa kiểm chứng riêng.

| # | Site | Hiện tượng | Nguyên nhân | Đề xuất | Ảnh hưởng |
|---|---|---|---|---|---|
| 1 | plausible | 6/8 tính năng có `demo_score` 1.0 nhưng các bước chỉ là `goto → click một link điều hướng → scroll/wait`; không bước nào thật sự trình diễn tính năng | Xác nhận: `verify` coi đổi URL là "thay đổi rõ". Click link sang trang khác luôn đạt điều kiện đó | Chỉ tính 1.0 khi thay đổi xảy ra trên cùng trang (dialog, DOM, ảnh) hoặc trang đích là `app_*`; điều hướng thuần túy cho 0.5 kèm ghi chú | Cao: `demo_score` điều khiển concept nào được phép demo, nên điểm thổi phồng làm sai hướng video |
| 2 | squoosh | 5/7 tính năng lỗi ở bước 2 (`step 2 (click) failed: RuntimeError`), mọi tính năng chỉ đạt 0.5, không có click nào được ghi | Xác nhận: lỗi `RuntimeError`. Dự đoán: không định vị được nút "2.8MB", "13KB"... vì fallback tìm theo role + tên khớp tuyệt đối (`exact=True`) từ `innerText`, còn tên accessible thật khác, và các nút này không có selector ổn định | Khi trích xuất, lưu chỉ số phần tử trong cùng truy vấn CSS rồi định vị theo chỉ số đó; thêm fallback `get_by_text` không khớp tuyệt đối và click theo bbox | Cao: không có bằng chứng demo nào cho một công cụ vốn rất dễ demo |
| 3 | plausible | Chưa từng phân tích giao diện sản phẩm thật (dashboard). Không tính năng nào có evidence `app_action`; trang `/pricing` không có trong 15 trang | Xác nhận: 15 trang đều là trang marketing (`/for-*`, `/vs-*`, `/*-web-analytics`). Dự đoán: link "View live demo" (đã được click trong verify) không được ưu tiên vì không có từ khóa nào trong đường dẫn; link Pricing có thể là anchor `/#pricing` bị bỏ phần fragment nên trùng với trang gốc | Cộng điểm theo văn bản link (`demo`, `try`, `live demo`, `playground`, `pricing`); gom các trang cùng mẫu (`/for-*`, `/vs-*`) và chỉ phân tích 1-2 trang mỗi nhóm; dành chỗ cho trang demo | Cao: với landing page, đây là nơi duy nhất có thể thấy sản phẩm thật |
| 4 | squoosh | Tính năng cốt lõi (nén ảnh của chính người dùng, kéo thả/dán) chỉ đạt 0.5 hoặc 0 | Xác nhận: không có bước nào để đưa file vào. Cần upload file, hệ thống không hỗ trợ (cố ý: chưa có file mẫu an toàn) | Thêm bước `upload` dùng `set_input_files` với một ảnh mẫu đi kèm repo; nó không ghi dữ liệu lên site | Cao với site dạng tool |
| 5 | todomvc | `product_name` là "TodoMVC (React)" và có tính năng về dự án TodoMVC (`ai-agent-eval`, `contribute-framework`, `compare-frameworks`, `benchmark-usage`) chứ không phải về ứng dụng todo | Xác nhận: trang 2 và 6 là `todomvc.com/examples/typescript-react/` và `todomvc.com/`. Crawl cùng domain đi theo link ở sidebar/footer ra khỏi thư mục ứng dụng | Khi URL bắt đầu có đường dẫn sâu, ưu tiên (hoặc giới hạn) các link cùng tiền tố đường dẫn; `open_questions` đã hỏi người dùng nhưng nên có câu hỏi chủ động về phạm vi | Trung bình đến cao: lẫn sản phẩm với dự án chứa nó |
| 6 | todomvc | `create-todo` và `edit-todo` chỉ 0.5; `filter-views` 0.5 dù là tính năng dễ nhất | Xác nhận: không bao giờ nhấn Enter nên gõ xong todo không được thêm vào. Xác nhận: `filter-views` dùng `goto` tới `#/active`, và `goto` không được tính là thay đổi | Cho phép Enter ở ô nhập đơn lẻ không nằm trong form khi request guard đang bật; tính `goto` hash-route có đổi DOM là thay đổi | Trung bình |
| 7 | todomvc | Click "Speedometer" bị từ chối nhưng `clicks_blocked` chỉ ghi tên, không ghi lý do | Xác nhận: phần tử là link ra ngoài site ("leaves the site"), không phải blacklist; lý do chỉ nằm trong ghi chú của tính năng | Thêm trường `reason` vào mục `clicks_blocked` | Thấp nhưng cần cho kiểm toán an toàn |
| 8 | plausible, squoosh | Beat dài hơn 15 từ: plausible b2 (19 từ), b4 (~16), squoosh b3 (17) | Xác nhận: giới hạn 15 từ nằm trong prompt nhưng code không kiểm tra; Outline Editor và Concept Proposer đều có thể vượt | Kiểm tra số từ sau khi áp dụng ops và sau khi sinh concept; nếu vượt thì cho LLM rút gọn một lần | Trung bình: ảnh hưởng nhịp video về sau |
| 9 | squoosh | Chỉ thấy 1 trang; "advanced settings" và "codec compare" chỉ có evidence `landing_claim` | Dự đoán: các tùy chọn đó chỉ xuất hiện sau khi đã mở một ảnh, mà hệ thống chỉ trích xuất trạng thái ban đầu của trang | Khám phá có trạng thái: sau một bước thành công thì trích xuất lại trang và phân tích phần mới | Trung bình |
| 10 | plausible | 56% token (46k/82k) dành cho phân tích 15 trang gần giống nhau | Xác nhận từ số token từng bước | Gom theo mẫu trang như mục 3 | Thấp: chi phí, không sai kết quả |
| 11 | plausible | Chạy được 14 request POST được cho qua theo luật `read_path` nhưng báo cáo không cho biết là URL nào | Xác nhận: báo cáo chỉ liệt kê 10 URL bị chặn đầu tiên | Ghi thêm 10 URL được cho qua đầu tiên theo từng luật | Thấp, cần cho kiểm toán |

### Hạn chế chung còn lại

- Chưa đăng nhập tự động (ngoài phạm vi): site sau login chỉ khám phá được nếu có `--storage-state`.
- Bộ blacklist khớp theo chuỗi con nên chặn dư (ví dụ `pay` trong `payroll`); chủ ý chặn dư để an toàn.
- `demo_score` chỉ có ba mức 0 / 0.5 / 1.0 và 0.5 gộp cả "đến được trang" lẫn "bước bị lỗi"; concept proposer coi mọi giá trị ≥ 0.5 là demo được (xem mục 1 và 2).
- Mỗi site chỉ chạy một lần, nên thời gian và token là một mẫu, không phải trung bình.
