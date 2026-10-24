# Làm nét nhẹ video cuối

`apps/render/src/pixelFormat.ts` → `finalizeVideo`: sau khi render, ffmpeg chạy lại một lượt
`-vf "scale=out_range=tv,unsharp=5:5:0.5:5:5:0.0" -pix_fmt yuv420p -crf 18 -preset veryfast`
(chỉ làm nét luma, chroma amount 0). Chỉnh bằng biến môi trường `SHARPEN_AMOUNT` (0 = tắt).

Ảnh lấy từ video aisoeasy.co đã có (`out/jobs/j234d75f6e4/video.mp4`, giây thứ 9,5), phóng 2× bằng nearest-neighbor
để dễ thấy viền:

- `compare-text-before_0.5_0.35.png`: chữ nhỏ trên trang, ba cột = gốc | amount 0,5 | amount 0,35.
- `compare-heading-before-after_0.5.png`: chữ lớn trắng trên nền tối, trên = gốc, dưới = amount 0,5.

Nhận xét: ở 0,5 nét chữ rõ hơn một chút, không thấy viền răng cưa hay quầng sáng (halo) quanh chữ trắng trên nền tối
(trường hợp dễ lộ halo nhất). Giữ 0,5; nếu video khác lộ halo thì hạ xuống 0,35 bằng `SHARPEN_AMOUNT=0.35`.
