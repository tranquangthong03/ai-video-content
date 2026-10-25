"""Screenshots of the two flow cards (select_flow, flow_storyboard_review) in the real web UI.

Starts the fixture site and an API with a small demo pipeline that asks the two cards using real
pictures of the fixture pages. Needs the web app running (`pnpm dev` in apps/web, port 3000).
Usage (from services/api):  uv run python scripts/capture_flow_cards.py
Screenshots go to docs/screenshots/.
"""

import functools
import http.server
import re
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.api.main import create_app  # noqa: E402
from app.core.flow_choice import build_request  # noqa: E402
from app.flows.storyboard import build_request as storyboard_request  # noqa: E402
from app.pipeline.asker import ask as ask_user  # noqa: E402
from app.pipeline.file_frontend import FileFrontend  # noqa: E402
from app.pipeline.runner import JobConfig, JobResult  # noqa: E402
from app.pipeline.state import update_state  # noqa: E402
from app.schemas.generated.core_flow import CoreFlow  # noqa: E402
from app.schemas.generated.flow_run import FlowRun  # noqa: E402

SITE_DIR = ROOT / "tests" / "fixtures" / "site"
OUT = ROOT.parents[1] / "docs" / "screenshots"
WEB = "http://localhost:3000"
API = "http://localhost:8000"
SHARED = "https://opensource-demo.orangehrmlive.com/web/index.php/dashboard"


def serve_site() -> str:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE_DIR))
    handler.log_message = lambda *a, **k: None  # type: ignore[method-assign]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}"


def pictures(site: str, folder: Path) -> list[str]:
    """Real viewport pictures of the fixture pages, in the order of the demo steps."""
    folder.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        def snap(n: int) -> None:
            path = folder / f"s{n}.jpg"
            page.screenshot(path=str(path), type="jpeg", quality=75)
            names.append(f"flow/steps/s{n}.jpg")

        page.goto(site + "/flow_home.html")
        snap(1)
        page.goto(site + "/flow_apply.html")
        snap(2)
        page.select_option("#kind", "Annual")
        snap(3)
        page.fill("#from", "05/03/2027")
        page.fill("#comment", "Family event")
        snap(4)
        page.click("#apply")
        snap(5)
        browser.close()
    return names


def demo_run(site: str, shots: list[str]) -> dict:  # type: ignore[type-arg]
    def step(i: int, do: str, note: str, chapter: str, url: str, **kw: object) -> dict:  # type: ignore[type-arg]
        return {
            "i": i, "action": {"do": do}, "note": note, "chapter_id": chapter, "url_after": url,
            "screenshot": shots[min(i, len(shots)) - 1], **kw,
        }  # fmt: skip

    apply_url = site + "/flow_apply.html"
    return {
        "flow_id": "leave", "status": "stopped_before_submit", "submit_policy": "stop",
        "stop_ref": "Apply",
        "steps": [
            step(1, "goto", "Mở trang tổng quan", "c1", site + "/flow_home.html"),
            step(2, "navigate", "Vào mục Leave để xin nghỉ", "c1", apply_url),
            step(3, "select", "Chọn loại nghỉ «Annual»", "c2", apply_url),
            step(4, "pick_date", "Chọn ngày bắt đầu nghỉ", "c2", apply_url),
            step(5, "type", "Ghi lý do: Family event", "c2", apply_url),
            step(6, "hover", "Sẵn sàng bấm «Apply»", "c3", apply_url),
            step(7, "highlight", "Nút Apply sẵn sàng, dừng trước khi gửi", "c3", apply_url),
        ],
        "chapters": [
            {"id": "c1", "title": "Mở form", "step_ids": [1, 2]},
            {"id": "c2", "title": "Điền thông tin", "step_ids": [3, 4, 5]},
            {"id": "c3", "title": "Gửi và theo dõi", "step_ids": [6, 7]},
        ],
        "warnings": ["Không lặp lại được bước 4 lần trước; agent làm tiếp từ đây."],
        "report": {
            "model": "deepseek-flash", "used_images": True, "llm_calls": 7,
            "prompt_tokens": 12000, "completion_tokens": 900, "seconds": 41.5,
            "write_requests": [], "invented_refs": 0, "repeat_warnings": 0,
        },
    }  # fmt: skip


def make_pipeline(site: str, shots: list[str]):  # type: ignore[no-untyped-def]
    def pipeline(cfg: JobConfig, frontend: FileFrontend) -> JobResult:
        job_id = cfg.job_dir.name
        flows = [
            CoreFlow.model_validate(
                {
                    "id": "leave",
                    "title": "Nhân viên xin nghỉ phép",
                    "persona": "Nhân viên văn phòng",
                    "goal": "Xin nghỉ 2 ngày và xem trạng thái đơn",
                    "start_url": site + "/flow_home.html",
                    "expected_steps": [
                        "Mở mục Leave",
                        "Chọn loại nghỉ",
                        "Chọn ngày nghỉ",
                        "Ghi lý do",
                        "Bấm Apply",
                    ],
                    "success_signal": "Đơn hiện trong danh sách «My Leave»",
                    "needs_submit": True,
                    "value": "Xin nghỉ trong một phút, không cần giấy tờ.",
                    "confidence": 0.85,
                }
            ),
            CoreFlow.model_validate(
                {
                    "id": "balance",
                    "title": "Xem số ngày phép còn lại",
                    "persona": "Nhân viên",
                    "goal": "Biết mình còn bao nhiêu ngày phép",
                    "start_url": site + "/flow_home.html",
                    "expected_steps": ["Mở trang tổng quan", "Đọc số ngày phép", "Mở My Leave"],
                    "success_signal": "Thấy «12 days of annual leave left»",
                    "needs_submit": False,
                    "value": "Không cần hỏi nhân sự.",
                    "confidence": 0.7,
                }
            ),
        ]
        root = SHARED if "orangehrm" in cfg.url else cfg.url
        ask_user(frontend, cfg.job_dir, build_request(job_id, flows, root))
        steps = cfg.job_dir / "flow" / "steps"
        steps.mkdir(parents=True, exist_ok=True)
        for rel in shots:
            (cfg.job_dir / rel).write_bytes((OUT_TMP / Path(rel).name).read_bytes())
        run = FlowRun.model_validate(demo_run(site, shots))
        ask_user(frontend, cfg.job_dir, storyboard_request(job_id, flows[0], run, version=1))
        update_state(cfg.job_dir, status="done", step="done", progress_pct=100)
        (cfg.job_dir / "video.mp4").write_bytes(b"0" * 100)
        return JobResult(0, "done")

    return pipeline


OUT_TMP = Path(tempfile.mkdtemp(prefix="flow-shots-"))


def shot(page: Page, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    print("screenshot", name, flush=True)


def new_job(url: str) -> str:
    r = httpx.post(f"{API}/api/jobs", data={"url": url}, timeout=20)
    r.raise_for_status()
    return str(r.json()["state"]["job_id"])


def main() -> int:
    site = serve_site()
    names = pictures(site, OUT_TMP)
    jobs_root = Path(tempfile.mkdtemp(prefix="flow-jobs-"))
    app = create_app(jobs_root, make_pipeline(site, names))
    app.state.poll = 0.1
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    time.sleep(1.5)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        own = new_job(site + "/")
        page.goto(f"{WEB}/jobs/{own}")
        page.get_by_role("heading", name="Chọn luồng chính để quay").wait_for(timeout=60_000)
        page.get_by_text("Nhân viên xin nghỉ phép").first.wait_for(timeout=10_000)
        shot(page, "20-select-flow")
        page.get_by_label("Mô tả luồng muốn quay").fill(
            "Nhân viên xin nghỉ phép 2 ngày rồi xem trạng thái đơn"
        )
        page.get_by_text("Cho phép hệ thống bấm Gửi/Lưu").first.click()
        page.get_by_text("Hệ thống sẽ tạo dữ liệu thật").wait_for()
        shot(page, "21-select-flow-submit-warning")
        page.get_by_text("Đây là tài khoản thử nghiệm của tôi").first.click()
        page.get_by_text("Cho phép hệ thống bấm Gửi/Lưu").first.click()  # back to the default (off)
        page.get_by_role("button", name=re.compile("Quay luồng")).click()
        page.get_by_role("heading", name=re.compile("Storyboard luồng")).wait_for(timeout=60_000)
        page.get_by_alt_text("Bước 3").wait_for()
        page.wait_for_load_state("networkidle")
        shot(page, "22-flow-storyboard")
        page.get_by_role("button", name="Chọn loại nghỉ Annual thay vì Personal").click()
        shot(page, "23-flow-storyboard-edit")

        page.get_by_role("button", name="Duyệt luồng này").click()  # one job at a time: finish it
        page.get_by_text("Hoàn tất").first.wait_for(timeout=30_000)

        shared = new_job(SHARED)
        page.goto(f"{WEB}/jobs/{shared}")
        page.get_by_role("heading", name="Chọn luồng chính để quay").wait_for(timeout=60_000)
        page.get_by_text("Không thể bật").wait_for()
        shot(page, "24-select-flow-shared-demo")
        browser.close()
    server.should_exit = True
    return 0


if __name__ == "__main__":
    sys.exit(main())
