# Spike: quay 2x (2880×1800) cho viewport 1440×900

Trang thử: https://aisoeasy.co/ (Chromium headless, Playwright). Ảnh so sánh: `compare-crops.png`
(cùng vùng 600×300 px CSS, phóng về 1200×600): trên-trái screenshot 2x (chuẩn), trên-phải **A**, dưới-trái **B**, dưới-phải **C**.

| | Cách | Kết quả thật | Kết luận |
|---|---|---|---|
| A | `record_video` + `device_scale_factor=2`, `record_video_size=2880×1800` | File 2880×1800, 25 fps, nhưng nội dung **không phải ảnh 2x của viewport**: trang bị vẽ lệch tỉ lệ (vùng nhìn rộng gấp đôi, chữ nhỏ bằng nửa screenshot 2x); SSIM với screenshot 2x chỉ 0,34 (frame đầu còn trắng). | Không đạt |
| B | CDP `Page.startScreencast` (jpeg q90, `maxWidth/Height 2880×1800`) trên context dsf 2, ghép bằng ffmpeg 30 fps | Frame vẫn **1440×900** (screencast trả kích thước viewport, không nâng theo dsf). fps thực 38,6 (khoảng cách lớn nhất 83 ms) nên ổn định, nhưng độ nét = quay 1x (SSIM 0,961 so với 0,962 của C). | Không đạt (không có lợi về độ nét) |
| C | `record_video` 1440×900, dsf 1 | 1440×900, 25 fps, sạch. | **Dùng** |

Kết luận: quay **1440×900** (viewport nhỏ hơn 1920×1080 nên UI to hơn tương đối 1,33 lần; camera crop sát sẽ làm
chữ to hơn nữa). Hạn chế: chữ khi zoom 1,0–1,6 cover bị phóng khoảng 1,4–2,2 lần từ nguồn 1440 px nên mềm hơn
bản 2x thật; không khắc phục được bằng Playwright/CDP hiện tại.

Script thử nằm ngoài repo (thư mục scratchpad của phiên làm việc); số liệu thô ở trên.
