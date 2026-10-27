"""Examples of good benefit and CTA copy by kind of product (shown to the Scene Writer).

They teach the shape (the result for the viewer first, one short action, a real reason to act now);
they contain no numbers and no product facts, so nothing can be copied into a video by mistake.
"""

EXAMPLES: dict[str, list[str]] = {
    # a small tool that does one job in the browser
    "tool": [
        "Thả ảnh vào là xong: file nhỏ đi, chất lượng vẫn giữ, không phải cài gì.",
        "Kéo thanh so sánh để tự thấy khác biệt, rồi tải về ngay.",
        "CTA: Mở thử ngay trên trình duyệt, miễn phí và không cần đăng ký.",
    ],
    # an internal business app (HR, CRM, back office)
    "web_app": [
        "Tạo hồ sơ mới ngay tại danh sách, không phải nhảy qua nhiều trang.",
        "Điền họ tên là đủ, hệ thống tự lo phần còn lại: bạn chỉ cần kiểm tra rồi lưu.",
        "CTA: Cho đội của bạn dùng thử bản demo hôm nay, mã nguồn mở và miễn phí.",
    ],
    # a SaaS / landing-page product
    "saas": [
        "Mọi việc của cả nhóm nằm trên một màn hình, không còn đi hỏi từng người.",
        "Báo cáo tự cập nhật, bạn mở ra là thấy ngay số cần xem.",
        "CTA: Dùng thử miễn phí 14 ngày, không cần thẻ: bắt đầu ngay hôm nay.",
    ],
}  # fmt: skip


def examples_for(site_type: str | None) -> str:
    """The examples for a kind of site as the lines of a prompt block (tool / web_app / saas)."""
    kind = site_type if site_type in ("tool", "web_app") else "saas"
    return "\n".join(f"- {line}" for line in EXAMPLES[kind])
