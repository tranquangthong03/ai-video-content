# Explorer benchmark: lần 1 vs lần 2

Cùng cấu hình chạy cho cả hai lần: `uv run python -m app.pipeline.explore_cli --auto` với câu trả lời có sẵn (`services/api/tests/fixtures/answers/<site>.json`), cache LLM tắt, DeepSeek thật, Chromium 1920x1080, request guard bật.

- **Lần 1** (commit `7538079`): `demo_score` ba mức, định vị phần tử bằng role + tên khớp tuyệt đối, crawl cả domain, không upload, không Enter.
- **Lần 2** (commit này): `demo_kind` + `demo_evidence`, `app/browser/locate.py` 6 tầng, `--scope path`, chấm điểm theo text link, gom trang theo mẫu, giữ chỗ cho trang demo, bước `upload` với file mẫu, `--enter-policy strict`, kiểm tra số từ. Giới hạn token mỗi site: `--max-tokens 200000`.
- Số liệu hai lần cách nhau vài giờ và **nội dung site có thể đã thay đổi** giữa hai lần chạy (đặc biệt plausible.io là site marketing sống), nên chênh lệch không hoàn toàn do code. Mỗi site chỉ chạy một lần mỗi vòng.
- Mô hình: `deepseek-chat` cho classify/analyze/concepts/outline/shortener (chỉ văn bản), `deepseek-flash` cho synthesize có ảnh (vision). Lần 2 có 5 loại bước gọi LLM: analyze=deepseek-chat, classify=deepseek-chat, concepts=deepseek-chat, outline=deepseek-chat, synthesize=deepseek-flash.

## 1. Chỉ số chính (lần 1 → lần 2)

| | plausible | todomvc | squoosh |
|---|---|---|---|
| Loại site | landing page | web app, no login | single-page tool |
| site_type | landing → landing | tool → tool | tool → tool |
| Trang đã xem | 15 → 15 | 6 → 2 | 1 → 1 |
| Trang bỏ qua | 43 urls not visited: max_pages/time limit → https://plausible.io/status redirected_off_site: https://status.plausible.io/; 53 urls not visited: max_pages/time limit | 0 → 0 | 0 → 0 |
| Trang gom theo mẫu | — → {"/*-web-analytics": 3, "/for-*": 2, "/vs-*": 1} | — → {"/examples/*/*": 2} | — → {} |
| Link ngoài phạm vi | — → 0 | — → 2 | — → 0 |
| Section anchor (không crawl) | — → 2 | — → 0 | — → 0 |
| Câu hỏi về phạm vi | — → không | — → có | — → không |
| Số tính năng (đã kiểm chứng / tổng) | 6/8 → 6/8 | 6/8 → 2/2 | 6/7 → 6/6 |
| Kết luận demo | demo_score 1.0: 6, 0.5: 0, 0: 2 → null: 2, showcase: 6 | demo_score 1.0: 2, 0.5: 4, 0: 2 → interaction: 1, showcase: 1 | demo_score 1.0: 0, 0.5: 6, 0: 1 → failed: 2, showcase: 4 |
| Concept recommended | Plausible: Phân tích web đơn giản, không cookie, siêu nhẹ | Ô nhập là đủ — to-do tối giản cho người mới React | Ba giây để ảnh nhẹ hơn một nửa |
| Số lần sửa dàn ý | 1 → 1 | 1 → 1 | 1 → 1 |
| Dàn ý cuối | 5 beat → 5 beat | 6 beat → 6 beat | 5 beat → 5 beat |
| Cảnh báo số từ | — → 0 | — → 0 | — → 0 |
| Click đã làm | 7 → 13 | 4 → 1 | 0 → 2 |
| Click bị từ chối (lý do) | 0 (no reason recorded) → 0  | 1 (no reason recorded) → 0  | 0 (no reason recorded) → 0  |
| Phím Enter | n/a (never pressed) → pressed 0, blocked 0 | n/a (never pressed) → pressed 1, blocked 0 | n/a (never pressed) → pressed 0, blocked 0 |
| Chiến lược định vị | n/a → {"role_exact": 11, "css": 2} failures 0 | n/a → {"css": 2} failures 0 | n/a → {"css_nth": 1, "role_exact": 1} failures 0 |
| Lỗi bước (có ảnh chụp) | — → 0 | — → 0 | — → 1 |
| Request cho qua | {"read_path": 14} → 0 | 0 → 0 | 0 → 0 |
| Request bị chặn | 0 → {"post_default": 2} | 0 → 0 | 0 → 0 |
| Telemetry giả 204 | 0 → 0 | {"telemetry": 13} → {"telemetry": 5} | 0 → 0 |
| Thời gian | 99.5 s → 109.3 s | 94.7 s → 38.5 s | 60.5 s → 63.6 s |
| Token (in + out) | 81970 → 70735 | 24559 → 11003 | 13811 → 14401 |
| Vision | có (synthesize) → có (synthesize) | có (synthesize) → có (synthesize) | có (synthesize) → có (synthesize) |

## 2. Thời gian từng bước (giây, lần 1 → lần 2)

| bước | plausible | todomvc | squoosh |
|---|---|---|---|
| classify | 1.5 → 1.53 | 1.38 → 1.3 | 1.12 → 1.34 |
| map | 20.56 → 55.05 | 20.26 → 11.58 | 3.47 → 5.64 |
| analyze | 13.69 → 10.34 | 6.52 → 1.36 | 1.98 → 2.3 |
| synthesize | 27.33 → 21.92 | 10.48 → 6.26 | 16.39 → 10.8 |
| verify | 28.34 → 13.7 | 48.92 → 10.55 | 29.58 → 34.58 |
| **tổng** | 99.5 → 109.3 | 94.7 → 38.5 | 60.5 → 63.6 |

## 3. Token từng bước (input / output, lần 1 → lần 2)

| bước | model | plausible | todomvc | squoosh |
|---|---|---|---|---|
| classify | deepseek-chat | 466/145 → 466/89 | 367/92 → 367/107 | 379/74 → 379/89 |
| analyze | deepseek-chat | 34340/12005 → 31975/8103 | 5929/2042 → 1691/229 | 782/343 → 901/348 |
| synthesize | deepseek-flash | 18890/6752 → 14431/5305 | 6828/2417 → 2362/1083 | 1755/3818 → 1953/2299 |
| verify | không dùng LLM | 0/0 → 0/0 | 0/0 → 0/0 | 0/0 → 0/0 |
| concepts | deepseek-chat | 6334/1088 → 7673/878 | 4217/833 → 2615/887 | 3866/934 → 5586/1025 |
| outline | deepseek-chat | 1887/63 → 1752/63 | 1773/61 → 1602/60 | 1798/62 → 1759/62 |

## 4.1 plausible: tính năng

`https://plausible.io` (landing page)  
Lần 2 hiểu sản phẩm là **Plausible Analytics**: Công cụ phân tích web nhẹ, đơn giản và thân thiện quyền riêng tư, thay thế Google Analytics: không cookie, không banner đồng ý, toàn bộ số liệu trên một trang.  
Lần 1 hiểu là **Plausible Analytics**: Công cụ phân tích web đơn giản, siêu nhẹ và thân thiện quyền riêng tư — giải pháp thay thế Google Analytics, không cookie, không banner đồng ý, lưu trữ tại EU.

| tính năng (lần 2) | importance | demo_kind | demo_score | evidence | ghi chú |
|---|---|---|---|---|---|
| Bảng điều khiển một trang với các chỉ số cốt lõi (`single-page-dashboard`) | 0.95 | showcase | 0.71 | 4 | showcase: body > main > article > div > p:nth-of-type(9) |
| Không cookie, không banner đồng ý (`cookieless-privacy`) | 0.92 | showcase | 0.63 | 4 | showcase: body > main > article > div > p:nth-of-type(14) |
| Script siêu nhẹ, không làm chậm website (`lightweight-script`) | 0.88 | showcase | 0.63 | 3 | showcase: main > div:nth-of-type(5) > div > div > h3:nth-of-type(2) |
| Mục tiêu và sự kiện tùy chỉnh để đo chuyển đổi (`goals-events`) | 0.85 | showcase | 0.79 | 4 | showcase: html > body > main > div:nth-of-type(3) |
| Phân tích phễu và hành trình người dùng (`funnels-journeys`) | 0.82 | showcase | 0.74 | 4 | showcase: #markdown-toc > li:nth-of-type(5) |
| Theo dõi chiến dịch marketing bằng UTM (`utm-campaign-tracking`) | 0.78 | showcase | 0.95 | 3 | showcase: body > main > article > div > p:nth-of-type(6) |
| Theo dõi doanh thu và quy doanh thu cho thương mại điện tử (`ecommerce-revenue`) | 0.75 | chưa kiểm chứng | 0.0 | 4 |  |
| Nhập dữ liệu lịch sử từ Google Analytics (`ga-migration-import`) | 0.72 | chưa kiểm chứng | 0.0 | 4 |  |

Lần 1 (demo_score): Dashboard một trang với các chỉ số cốt l = 1.0; Phân tích không cookie, không cần banner = 1.0; Script theo dõi siêu nhẹ, giữ tốc độ tải = 1.0; Mục tiêu, sự kiện tùy chỉnh, phễu và hàn = 1.0; Lưu trữ tại EU và bộ tài liệu tuân thủ = 1.0; Theo dõi doanh thu thương mại điện tử và = 1.0; Nhập lịch sử Google Analytics và chuyển  = 0.0; Chia sẻ dashboard và xuất số liệu cho độ = 0.0

Concepts lần 2: `overview` ★ Plausible: Phân tích web đơn giản, không cookie, siêu nhẹ; `deep_dive` Mổ xẻ dashboard một trang của Plausible; `pain_solution` Hết mất dữ liệu vì banner đồng ý

Dàn ý được duyệt (lần 2):

1. Bạn thật sự cần biết gì từ số liệu website của mình?
2. Plausible cho bạn mọi số liệu quan trọng trên một trang duy nhất.
3. Không cookie, không banner, mọi lượt truy cập đều là thật.
4. Script chỉ 2.5KB, nhẹ hơn 54 lần, không làm chậm web.
5. Dùng thử 30 ngày, không cần thẻ tín dụng.

## 4.2 todomvc: tính năng

`https://todomvc.com/examples/react/dist/` (web app, no login)  
Lần 2 hiểu sản phẩm là **TodoMVC: React**: Ứng dụng to-do list tối giản viết bằng React, cho phép nhập nhanh việc cần làm và chỉnh sửa từng mục ngay tại chỗ.  
Lần 1 hiểu là **TodoMVC (React)**: Ứng dụng todo mẫu viết bằng React, đồng thời là bộ so sánh cùng một ứng dụng Todo được triển khai trên nhiều framework JavaScript.

| tính năng (lần 2) | importance | demo_kind | demo_score | evidence | ghi chú |
|---|---|---|---|---|---|
| Tạo việc cần làm mới (`create-todo`) | 0.95 | interaction | 0.75 | 2 |  |
| Chỉnh sửa todo bằng nhấp đúp (`edit-todo-double-click`) | 0.70 | showcase | 0.95 | 2 | showcase: html > body > footer > p:nth-of-type(1) |

Lần 1 (demo_score): Tạo việc cần làm mới = 0.5; Chỉnh sửa todo bằng nhấp đúp = 0.5; Lọc danh sách theo trạng thái (All / Act = 0.5; Duyệt cùng một app Todo trên nhiều frame = 1.0; Bản demo cập nhật theo framework ổn định = 1.0; Dùng trong benchmark đa trình duyệt (Spe = 0.5; Thử framework hoặc AI coding agent với t = 0.0; Đóng góp một framework mới qua pull requ = 0.0

Concepts lần 2: `overview` ★ Ô nhập là đủ — to-do tối giản cho người mới React; `deep_dive` Sửa todo tại chỗ chỉ bằng nhấp đúp; `pain_solution` Hết cảnh ghi chú rối — một ô nhập, một danh sách

Dàn ý được duyệt (lần 2):

1. Bạn có hay quên việc cần làm mỗi ngày?
2. Mở app, gõ việc vào ô 'What needs to be done?' là xong
3. Danh sách hiện ngay, mỗi mục gọn trong một dòng
4. Cuộn xuống footer, highlight dòng 'Double-click to edit a todo'
5. Đây cũng là demo React gọn để đọc và học theo
6. CTA: Mở TodoMVC React và thử ngay hôm nay

## 4.3 squoosh: tính năng

`https://squoosh.app` (single-page tool)  
Lần 2 hiểu sản phẩm là **Squoosh**: Công cụ nén và tối ưu ảnh chạy hoàn toàn trong trình duyệt: kéo ảnh vào, so sánh chất lượng trước–sau và tải về tệp nhẹ hơn ngay lập tức.  
Lần 1 hiểu là **Squoosh**: Trình tối ưu ảnh chạy ngay trong trình duyệt: nén ảnh, so sánh chất lượng và lưu file nhỏ hơn mà vẫn đẹp.

| tính năng (lần 2) | importance | demo_kind | demo_score | evidence | ghi chú |
|---|---|---|---|---|---|
| Nén và giảm dung lượng ảnh (`f_compress`) | 0.95 | showcase | 0.95 | 2 | showcase: #app |
| Mở ảnh bằng kéo thả hoặc dán (`f_open_image`) | 0.90 | failed | 0.0 | 2 | step 2 (click) timeout: Locator.click: Timeout 4000ms exceeded.
Call log:
  - waiting for  |
| So sánh trước–sau và lưu kết quả tức thì (`f_compare_save`) | 0.85 | showcase | 0.95 | 1 | showcase: div > div > div > div:nth-of-type(1) > p |
| Tinh chỉnh cài đặt nén để có tệp nhỏ hơn (`f_tune_settings`) | 0.75 | showcase | 0.95 | 1 | showcase: div > div > div > div:nth-of-type(1) > p |
| Xử lý cục bộ, ảnh không rời khỏi thiết bị (`f_privacy_local`) | 0.70 | showcase | 0.95 | 1 | showcase: div > div > div > div:nth-of-type(1) > p |
| Thử ngay bằng ảnh mẫu có sẵn (`f_samples`) | 0.60 | failed | 0.0 | 3 |  |

Lần 1 (demo_score): Nén ảnh, giảm dung lượng file = 0.5; So sánh trước/sau và lưu tức thì = 0.5; Xử lý cục bộ, ảnh không rời thiết bị = 0.5; Đưa ảnh vào bằng kéo-thả hoặc dán = 0.5; Chỉnh cài đặt nén để có file nhỏ hơn nữa = 0.5; Nén và so sánh ảnh với nhiều codec khác  = 0.5; Thử nhanh bằng ảnh mẫu có sẵn = 0.0

Concepts lần 2: `overview` ★ Ba giây để ảnh nhẹ hơn một nửa; `deep_dive` Nén ảnh không cần cài gì, không cần upload; `pain_solution` Landing page chậm vì ảnh nặng?

Dàn ý được duyệt (lần 2):

1. Ảnh quá nặng có đang làm trang web của bạn chậm?
2. Mở squoosh.app, bấm thử ảnh mẫu Large photo để xem máy nén ngay.
3. Cuộn tới khối mô tả để highlight: xem khác biệt rồi lưu tức thì.
4. Nhấn mạnh: ảnh không rời thiết bị, mọi thứ chạy trong trình duyệt.
5. CTA: Mở squoosh.app, kéo ảnh của bạn vào và tải bản nhẹ hơn.

## 5. Kỳ vọng so với kết quả lần 2

| Kỳ vọng | Kết quả | Nguyên nhân (đã xác nhận trong dữ liệu trừ khi ghi "dự đoán") |
|---|---|---|
| todomvc: create là `interaction` | **Đạt** (`interaction`, 0.75: 1 lần Enter, +4 mục list) | Enter được phép vì ô nhập nằm ngoài `<form>` (policy strict). Lần 1 chỉ đạt 0.5 vì không bao giờ nhấn Enter |
| todomvc: edit là `interaction` | **Không đạt** (`showcase` 0.95, câu "Double-click to edit a todo" ở footer) | Schema chưa có thao tác `dblclick`, nên chỉ có bằng chứng dạng text |
| todomvc: filter là `interaction` | **Không đạt**: tính năng này không còn trong profile | Link `#/active`, `#/completed` chỉ hiện sau khi đã có một todo, mà explorer chỉ xem trạng thái ban đầu (2 trang). Lần 1 thấy chúng nhờ crawl ra ngoài app |
| todomvc: product là app todo, không lẫn dự án | **Đạt**: "TodoMVC: React", 2 tính năng đều về app; 2 URL ngoài phạm vi được liệt kê; câu hỏi "ứng dụng tại /examples/react/dist hay toàn bộ todomvc.com?" đã thêm vào `open_questions` | `--scope path` mặc định cho URL có đường dẫn sâu |
| squoosh: nén ảnh là `interaction` nhờ upload | **Không đạt**: không bước `upload` nào được chạy; "nén ảnh" là `showcase` (#app), "mở ảnh" là `failed`, "ảnh mẫu" là `failed` | (a) LLM sinh `click` lên `input[type=file]` ẩn thay vì `upload`, bước click quá hạn 4s. (b) Click ảnh mẫu 2.9MB được định vị đúng (`role_exact`) nhưng chỉ chờ 500ms, ảnh còn đang tải nên `visual_diff` 0.009 < 0.02, nên bị coi là không đổi (dự đoán: ảnh tải qua mạng) |
| plausible: có phân tích trang live demo/dashboard | **Không đạt**: 15 trang là marketing + docs + `/login` + `/register`; trang demo không được xem | Link "View live demo" nằm ở vùng `main`; khi đã có ≥3 link nav/header/footer thì `candidates_from_links` bỏ hết link vùng `main`. Các slot "demo" bị chiếm bởi `/login`, `/register`, `/docs` vì khớp từ "Get Started"/"app" |
| plausible: tính năng marketing là `showcase`/`navigation`, không còn 1.0 giả | **Đạt**: 6 `showcase` (0.63–0.95), 0 `interaction`, 0 `navigation`, 2 chưa kiểm chứng (vượt top 6) | Tính năng chỉ có bằng chứng text chuyển sang tìm section thay vì giả demo bằng click link |

## 6. Trạng thái 11 vấn đề của lần 1

| # | Vấn đề lần 1 | Lần 2 |
|---|---|---|
| 1 | `demo_score` 1.0 giả vì đổi URL | **Đã sửa**: không còn tính năng nào "1.0 giả"; điều hướng thuần túy là `navigation` (0.5–0.8), chỉ thay đổi trong trang mới là `interaction` |
| 2 | squoosh: lỗi định vị `RuntimeError` | **Đã sửa phần định vị**: 0 lỗi định vị ở cả 3 site, chiến lược dùng: `css`, `role_exact`, `css_nth`. Còn lỗi mới: click vào input file ẩn (xem 7.1) |
| 3 | plausible chưa thấy giao diện thật | **Chưa sửa** (xem 7.2) |
| 4 | squoosh không upload được | **Đã cài đặt, chưa được dùng trong lần chạy thật** (xem 7.1); có unit test trên fixture |
| 5 | todomvc lẫn app với dự án | **Đã sửa** |
| 6 | todomvc: Enter, hash-route `goto` | **Đã sửa Enter** (1 lần, tạo todo). Hash-route `goto` đã tính được nhưng không có tính năng nào dùng đến (xem 7.4) |
| 7 | `clicks_blocked` thiếu lý do | **Đã thêm** trường `reason`; lần chạy này không site nào có click bị từ chối nên chưa quan sát được trên site thật (có test) |
| 8 | beat > 15 từ | **Đã sửa**: beat dài nhất 13 (plausible), 13 (todomvc), 14 (squoosh); hook ≤ 10 từ. LLM tự tuân thủ ở 2/3 site; squoosh gọi thêm 1 lần rút gọn |
| 9 | UI chỉ hiện sau khi mở ảnh | **Chưa sửa** (xem 7.4) |
| 10 | plausible tốn 56% token cho 15 trang giống nhau | **Giảm nhẹ**: gom 6 trang theo mẫu (`/*-web-analytics` 3, `/for-*` 2, `/vs-*` 1); token phân tích 46.3k → 40.1k (-13%), tổng 82.0k → 70.7k |
| 11 | không biết POST nào được cho qua | **Đã thêm** `first_passed_urls` theo luật (todomvc: 5 POST telemetry giả 204 có URL đầy đủ); plausible không có POST nào được cho qua lần này |

## 7. Vấn đề mới hoặc còn lại, xếp theo mức ảnh hưởng (chưa sửa, chờ bạn duyệt)

Theo yêu cầu "không lặp sửa quá 1 vòng", tôi dừng ở đây và chỉ liệt kê. Mỗi đề xuất nhỏ và độc lập.

1. **Upload và chờ kết quả (squoosh, ảnh hưởng cao).**
   - Trong `sanitize`, đổi tự động mọi bước `click`/`hover` lên phần tử có capability `upload` thành bước `upload`, để không phụ thuộc việc LLM chọn đúng loại bước.
   - Sau `click`/`upload`, chờ `networkidle` tối đa 3 giây trước khi chụp ảnh "sau". Hiện chờ cố định 500ms nên thao tác tải ảnh mẫu bị coi là không đổi.
2. **Link CTA ở vùng `main` bị bỏ (plausible, ảnh hưởng cao).** Luôn đưa vào danh sách link có văn bản khớp `DEMO_TEXT` bất kể vùng; loại `/login`, `/register`, `/docs` khỏi nhóm "demo" (cộng điểm âm hoặc `NEGATIVE_PATH`).
3. **Chất lượng `showcase_target` (plausible, ảnh hưởng trung bình).** Bộ chọn "phần tử nhỏ nhất đủ từ" cho ra mục lục (`#markdown-toc > li:nth-of-type(5)`), một thẻ `h3`, hoặc `p:nth-of-type(14)`. Điểm 0.63–0.95 chỉ phản ánh độ khớp từ, không phản ánh khối có đáng highlight hay không. Đề xuất: loại nav/toc/footer, ưu tiên `section`/`article` có heading, đặt độ dài tối thiểu.
4. **Trạng thái và thao tác còn thiếu (todomvc).** Thêm `dblclick` vào thao tác; sau một bước `interaction` thành công, trích xuất lại trang để thấy phần tử mới (ví dụ bộ lọc All/Active/Completed).
5. **Chưa quan sát trên site thật:** click bị từ chối (có `reason`), Enter bị chặn, và bước `upload`. Các trường hợp này chỉ có unit test trên fixture site.
6. **Trang `/login` và `/register` được phân tích như trang thường (plausible).** Chúng tốn 2 trong 15 slot mà không có nội dung sản phẩm; liên quan đề xuất 2.

### Hạn chế chung còn lại

- Mỗi site chỉ chạy một lần mỗi vòng; thời gian và token là một mẫu. Nội dung site có thể đã thay đổi giữa hai lần chạy.
- `demo_score` giờ là độ tin cậy của kết luận, nhưng công thức còn đơn giản (đếm số tín hiệu thay đổi), chưa được hiệu chuẩn trên nhiều site.
- Cơ chế Enter chặt (`strict`) chỉ được thử trên một ô nhập đơn lẻ; các nhánh chặn dựa vào `<form>` mới được kiểm chứng bằng fixture.
