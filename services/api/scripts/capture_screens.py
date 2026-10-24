"""Drive the web UI with Playwright through the whole flow and save a screenshot of every state.

Needs `pnpm dev:all` running. Usage (from services/api):
  uv run python scripts/capture_screens.py            # all flows
  uv run python scripts/capture_screens.py todomvc    # only the first flow
Screenshots go to docs/screenshots/.
"""

import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = os.environ.get("CAPTURE_BASE", "http://localhost:3000")
OUT = Path(__file__).resolve().parents[3] / "docs" / "screenshots"
LONG = 15 * 60_000  # the explorer and the render are slow


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def shot(page: Page, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    log(f"screenshot {name}")


def button(page: Page, name: str | re.Pattern[str]):  # type: ignore[no-untyped-def]
    return page.get_by_role("button", name=name).first


def create_job(page: Page, sample: str) -> str:
    page.goto(BASE)
    page.get_by_role("button", name=sample).click()
    button(page, "Tạo video").click()
    page.wait_for_url(re.compile(r"/jobs/"), timeout=30_000)
    return page.url.rsplit("/", 1)[-1]


def drive(page: Page, tag: str) -> None:
    """From a freshly created job to a downloaded video, with one outline and one script edit."""
    button(page, "Xác nhận").wait_for(timeout=LONG)
    log(f"{tag}: confirm_understanding")
    shot(page, f"{tag}-04-confirm")
    button(page, "Xác nhận").click()

    button(page, "Chọn hướng này").wait_for(timeout=LONG)
    shot(page, f"{tag}-05-concept")
    button(page, re.compile(r"^60s")).click()
    shot(page, f"{tag}-06-concept-duration-warning")
    button(page, re.compile(r"đề xuất\)")).click()
    button(page, "Chọn hướng này").click()

    button(page, "Duyệt dàn ý").wait_for(timeout=LONG)
    shot(page, f"{tag}-07-outline")
    page.get_by_placeholder(re.compile("đổi mở đầu")).fill(
        "Đổi câu mở đầu thành câu hỏi về nỗi đau của người dùng"
    )
    button(page, "Gửi yêu cầu sửa").click()
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        if page.get_by_text("Cần làm rõ một chút").count():
            shot(page, f"{tag}-08-clarify")
            page.locator("main button.border").first.click()
        if page.get_by_text("v2", exact=True).count():
            break
        time.sleep(1.5)
    shot(page, f"{tag}-08-outline-edited")
    button(page, "Duyệt dàn ý").click()

    page.get_by_text(re.compile("Đang viết kịch bản")).first.wait_for(timeout=60_000)
    shot(page, f"{tag}-09-running-script")
    button(page, re.compile("Duyệt & sản xuất")).wait_for(timeout=LONG)
    shot(page, f"{tag}-10-script")
    page.get_by_placeholder(re.compile("scene 2")).fill(
        "Scene 1: viết lại lời đọc ngắn gọn, vào thẳng vấn đề hơn"
    )
    button(page, "Gửi yêu cầu sửa").click()
    page.get_by_text("Kịch bản v2").wait_for(timeout=240_000)
    page.get_by_label("Sửa cảnh 1").click()
    shot(page, f"{tag}-11-script-edited-quick-edit")
    page.get_by_role("button", name="Hủy", exact=True).last.click()  # the card's, not the header's
    button(page, re.compile("Duyệt & sản xuất")).click()

    page.get_by_text(re.compile("Đang quay cảnh")).first.wait_for(timeout=LONG)
    shot(page, f"{tag}-12-running-produce")
    page.locator("video").wait_for(timeout=LONG)
    shot(page, f"{tag}-13-video")
    with page.expect_download() as info:
        page.get_by_role("link", name=re.compile("Tải MP4")).click()
    path = info.value.path()
    log(f"{tag}: downloaded {Path(path).stat().st_size} bytes")
    assert Path(path).stat().st_size > 100_000


def main(which: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            page.goto(BASE)
            button(page, "Tạo video").wait_for()
            shot(page, "01-home")
            page.get_by_text("Website cần đăng nhập?").click()
            shot(page, "02-home-login-help")

            if which in ("all", "todomvc"):
                job = create_job(page, "TodoMVC (React)")
                log(f"todomvc job {job}")
                page.get_by_text(re.compile("Đang phân tích trang")).first.wait_for(timeout=LONG)
                page.locator("img[alt='Trang vừa phân tích']").wait_for(timeout=LONG)
                shot(page, "03-running-explore")
                drive(page, "todomvc")

            if which in ("all", "queue"):
                first = create_job(page, "Plausible")
                log(f"second-url job {first}")
                second = create_job(page, "TodoMVC (React)")
                page.get_by_text("Đang xếp hàng").first.wait_for(timeout=30_000)
                shot(page, "14-queued")
                page.goto(f"{BASE}/jobs/{first}")
                drive(page, "second")
                page.goto(f"{BASE}/jobs/{second}")
                page.get_by_text(
                    re.compile("Đang phân tích trang|Đang khám phá|Xác nhận")
                ).first.wait_for(timeout=120_000)
                shot(page, "15-queued-job-started-by-itself")
                button(page, "Hủy").click()
                button(page, "Chạy tiếp").wait_for(timeout=60_000)
                shot(page, "16-cancelled")

            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(BASE)
            page.get_by_text("Công việc gần đây").wait_for()
            shot(page, "17-mobile-home")
        except Exception:
            shot(page, "error")
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "all")
