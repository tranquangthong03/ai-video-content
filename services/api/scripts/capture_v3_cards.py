"""Screenshots of the V3 flow cards in the real web UI, from the saved aisoeasy snapshot:
the select_flow card (describe-your-own box first, value actions per flow, empty-account warning)
and the storyboard card (navigation-only / empty-pages warning before the Approve button).

Needs the web app running (`pnpm dev` in apps/web, port 3000). Usage (from services/api):
  uv run python scripts/capture_v3_cards.py
Screenshots go to docs/screenshots/ (50-select-flow-v3.png, 51-storyboard-warning.png).
"""

import json
import shutil
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
from app.core.flow_value import empty_signals, empty_warning, explored_texts, quality_of_run  # noqa: E402
from app.flows.storyboard import build_request as storyboard_request  # noqa: E402
from app.pipeline.asker import ask as ask_user  # noqa: E402
from app.pipeline.file_frontend import FileFrontend  # noqa: E402
from app.pipeline.runner import JobConfig, JobResult  # noqa: E402
from app.pipeline.state import update_state  # noqa: E402
from app.schemas.generated.core_flow import CoreFlow  # noqa: E402
from app.schemas.generated.flow_run import FlowRun  # noqa: E402

GOLDEN = ROOT / "tests" / "golden" / "aisoeasy"
MEDIA = ROOT / "tests" / "golden-media" / "aisoeasy"
OUT = ROOT.parents[1] / "docs" / "screenshots"
WEB = "http://localhost:3000"
API = "http://localhost:8000"


def pipeline(cfg: JobConfig, frontend: FileFrontend) -> JobResult:
    job_id = cfg.job_dir.name
    flows = [
        CoreFlow.model_validate(f)
        for f in json.loads((GOLDEN / "selected_flow.json").read_text(encoding="utf-8"))["flows"]
    ]
    # the job dir looks like the real one: explored pages, the live logs, the step pictures
    for sub in ("explore/pages", "flow/live"):
        shutil.copytree(GOLDEN / sub, cfg.job_dir / sub, dirs_exist_ok=True)
    if (MEDIA / "flow" / "steps").is_dir():
        shutil.copytree(
            MEDIA / "flow" / "steps", cfg.job_dir / "flow" / "steps", dirs_exist_ok=True
        )
    warning = empty_warning(empty_signals(explored_texts(cfg.job_dir)))
    ask_user(
        frontend, cfg.job_dir,
        build_request(job_id, flows, "https://aisoeasy.co/", empty_warning=warning),
    )  # fmt: skip
    run = FlowRun.model_validate_json(
        (GOLDEN / "flow" / "flow_run.json").read_text(encoding="utf-8")
    )
    quality = quality_of_run(run, cfg.job_dir)
    ask_user(
        frontend, cfg.job_dir,
        storyboard_request(job_id, flows[0], run, version=1, quality=quality),
    )  # fmt: skip
    update_state(cfg.job_dir, status="done", step="done", progress_pct=100)
    (cfg.job_dir / "video.mp4").write_bytes(b"0" * 100)
    return JobResult(0, "done")


def shot(page: Page, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    print("screenshot", name, flush=True)


def main() -> int:
    jobs_root = Path(tempfile.mkdtemp(prefix="v3-jobs-"))
    app = create_app(jobs_root, pipeline)
    app.state.poll = 0.1
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    time.sleep(1.5)
    r = httpx.post(f"{API}/api/jobs", data={"url": "https://aisoeasy.co/"}, timeout=20)
    r.raise_for_status()
    job_id = r.json()["state"]["job_id"]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{WEB}/jobs/{job_id}")
        page.get_by_role("heading", name="Chọn luồng chính để quay").wait_for(timeout=60_000)
        page.get_by_text("thao tác tạo kết quả").first.wait_for(timeout=10_000)
        shot(page, "50-select-flow-v3")
        page.get_by_role("button", name="Quay luồng", exact=False).click()
        page.get_by_role("heading", name="Storyboard luồng", exact=False).wait_for(timeout=60_000)
        page.get_by_label("Cảnh báo chất lượng luồng").wait_for(timeout=10_000)
        page.wait_for_load_state("networkidle")
        shot(page, "51-storyboard-warning")
        browser.close()
    server.should_exit = True
    return 0


if __name__ == "__main__":
    sys.exit(main())
