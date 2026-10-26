"""Shared fixtures: a local fixture website, and a scripted fake LLM that needs no network."""

import functools
import json
import re
import threading
import time
from collections.abc import Callable, Iterator
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from app.browser.session import BrowserSession
from app.llm.json_call import Completion

SITE_DIR = Path(__file__).parent / "fixtures" / "site"
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489000000"
    "0d49444154789c6360f8cfc0f01f0005000201a2cb3b3d0000000049454e44ae426082"
)


class SiteHandler(SimpleHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        SiteHandler.hits.append(self.path)
        if self.path.startswith("/slow-img.png"):  # an image that takes a while to arrive
            time.sleep(0.8)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(PNG_1X1)
            return
        if self.path.startswith("/hit/"):
            self.send_response(204)
            self.end_headers()
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        SiteHandler.hits.append("POST " + self.path)
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture(scope="session")
def site() -> Iterator[str]:
    """Base URL of the fixture site (tests/fixtures/site) served on a free local port."""
    handler = functools.partial(SiteHandler, directory=str(SITE_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def browser_session(site: str) -> Iterator[BrowserSession]:
    """One Chromium per test module, guard installed like in production.

    Module scope (not session): the CLI tests start their own sync Playwright, and two sync
    Playwright instances cannot be alive in one thread.
    """
    with BrowserSession(site) as s:
        yield s


@pytest.fixture
def hits(site: str) -> list[str]:
    """Paths requested from the fixture site during this test."""
    SiteHandler.hits.clear()
    return SiteHandler.hits


class FakeLLM:
    """ChatLLM whose answers come from `handler(prompt) -> dict | str`."""

    model = "fake-text"

    def __init__(
        self, handler: Callable[[str], Any], vision_model: str | None = "fake-vision"
    ) -> None:
        self.handler = handler
        self.vision_model = vision_model
        self.calls: list[dict[str, Any]] = []

    def complete(self, model: str, messages: list[dict[str, Any]]) -> Completion:
        content = messages[-1]["content"]
        prompt = content if isinstance(content, str) else content[0]["text"]
        has_images = not isinstance(content, str)
        self.calls.append(
            {"model": model, "prompt": prompt, "images": has_images, "n_msgs": len(messages)}
        )
        out = self.handler(prompt)
        return Completion(out if isinstance(out, str) else json.dumps(out), 100, 50)


def _section(prompt: str, tag: str) -> str:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", prompt, re.S)
    return m.group(1).strip() if m else ""


def scripted_handler(prompt: str) -> dict[str, Any]:
    """Deterministic stand-in for the five LLM roles, driven by what the prompt contains."""
    if prompt.startswith("Phân loại một website"):
        return {"site_type": "web_app", "reason": "fake"}

    if prompt.startswith("Bạn là chuyên gia phân tích sản phẩm"):
        url = re.search(r'<page url="([^"]*)"', prompt).group(1)  # type: ignore[union-attr]
        elements = [ln.split(" | ") for ln in _section(prompt, "interactive_elements").splitlines()]
        actions = [
            {"ref": e[0], "name": e[2], "intent": "create" if "new" in e[2].lower() else "other"}
            for e in elements
            if len(e) >= 4 and e[1] in ("button", "link")
        ]
        is_app = "app.html" in url
        return {
            "page_type": "app_dashboard" if is_app else "landing_hero",
            "purpose": "Trang demo",
            "actions": actions,
            "claimed_features": []
            if is_app
            else [{"name": "Bảng Kanban", "quote": "Kéo thả công việc"}],
            "visual_quality": 0.8,
        }

    if prompt.startswith("Bạn là product marketer") and "<state_delta>" in prompt:
        # stateful discovery: nothing new to report
        return {"site_type": "web_app", "product_name": "TaskFlow", "one_liner": "o",
                "target_users": [], "features": [], "open_questions": []}  # fmt: skip

    if prompt.startswith("Bạn là product marketer"):
        insights = json.loads(_section(prompt, "pages"))
        app = next(i for i in insights if i["page_type"] == "app_dashboard")
        landing = next(i for i in insights if i["page_type"] == "landing_hero")
        new_task = next(a for a in app["actions"] if a["name"] == "New task")
        delete = next(a for a in app["actions"] if "Delete" in a["name"])
        return {
            "site_type": "web_app",
            "product_name": "TaskFlow",
            "one_liner": "Quản lý công việc cho nhóm nhỏ",
            "target_users": ["Nhóm nhỏ"],
            "value_props": ["Đơn giản"],
            "features": [
                {
                    "id": "f_new", "name": "Tạo công việc", "description": "Thêm công việc mới",
                    "evidence": [{"source": "app_action", "url": app["url"], "ref": new_task["ref"], "quote": None}],
                    "importance": 0.9,
                    "demo_steps": [{"do": "click", "url": app["url"], "ref": new_task["ref"], "text": None}],
                },
                {
                    "id": "f_kanban", "name": "Bảng Kanban", "description": "Kéo thả công việc",
                    "evidence": [{"source": "landing_claim", "url": landing["url"], "ref": "e999", "quote": "Kéo thả"}],
                    "importance": 0.6, "demo_steps": [],
                },
                {
                    "id": "f_unsafe", "name": "Dọn công việc", "description": "Xóa công việc cũ",
                    "evidence": [{"source": "app_action", "url": app["url"], "ref": delete["ref"], "quote": None}],
                    "importance": 0.4,
                    "demo_steps": [{"do": "click", "url": app["url"], "ref": delete["ref"], "text": None}],
                },
            ],
            "open_questions": ["Đối tượng khách hàng chính là ai?"],
        }  # fmt: skip

    if prompt.startswith("Bạn là biên kịch short video"):
        product = json.loads(_section(prompt, "product"))
        ids = [f["id"] for f in product["features"]]

        def concept(i: int, angle: str, rec: bool) -> dict[str, Any]:
            return {
                "id": f"c{i}", "angle": angle, "title": f"Hướng {angle}", "goal": "awareness",
                "hook_example": "Công việc rối?", "feature_ids": ids[:1], "duration_s": 30,
                "beats": ["Hook: công việc rối", "Demo tạo việc", "Demo kanban", "CTA: dùng thử"],
                "why": "Hợp với sản phẩm", "recommended": rec,
            }  # fmt: skip

        return {"concepts": [concept(1, "overview", True), concept(2, "deep_dive", False),
                             concept(3, "pain_solution", False)]}  # fmt: skip

    if prompt.startswith('Bạn là "Outline Editor"'):
        instruction = _section(prompt, "user_instruction")
        if "bỏ ý 3" in instruction:
            return {"status": "ok", "ops": [{"op": "delete", "beat_id": "b3"}]}
        if "mở đầu" in instruction:
            return {"status": "ok", "ops": [{"op": "set", "beat_id": "b1", "text": "Bạn có đang ngập việc?",
                                              "feature_id": None}]}  # fmt: skip
        if "mơ hồ" in instruction and "Làm rõ" not in instruction:
            return {"status": "needs_clarification",
                    "clarification": {"question": "Sửa beat nào?",
                                      "options": [{"id": "b2", "label": "Beat 2"}, {"id": "b4", "label": "Beat 4"}]}}  # fmt: skip
        if "Làm rõ" in instruction:
            return {
                "status": "ok",
                "ops": [{"op": "set", "beat_id": "b2", "text": "Tạo việc chỉ một cú nhấp"}],
            }
        return {"status": "ok", "ops": []}
    if prompt.startswith("Bạn là trợ lý biên tập video. Nhiệm vụ: gán"):
        outline = json.loads(_section(prompt, "outline"))
        feats = json.loads(_section(prompt, "features").split("   {#")[0])
        mapping = []
        for i, beat in enumerate(outline["beats"]):
            fid = None
            if "Demo" in beat["text"] and feats:
                fid = feats[min(i - 1, len(feats) - 1)]["id"]
            mapping.append(
                {"beat_id": beat["id"], "feature_id": fid, "confidence": 0.9, "reason": "fake"}
            )
        return {"mapping": mapping}
    if prompt.startswith("Bạn là biên tập viên rút gọn"):
        lines = json.loads(_section(prompt, "lines"))
        return {"lines": [{"id": x["id"], "text": " ".join(x["text"].split()[: x["max_words"] - 1])}
                          for x in lines]}  # fmt: skip
    raise AssertionError(f"unexpected prompt: {prompt[:80]!r}")


SLOW_FIXTURES = {"browser_session", "site", "hits"}
SLOW_MODULES = {
    "test_recorder", "test_producer", "test_trim", "test_visual_v2", "test_e2e_explore",
    "test_login_detect", "test_login_gate", "test_login_window", "test_login_form",
    "test_login_secrets", "test_login_privacy", "test_login_session_check",
}  # fmt: skip


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark tests that start Chromium / ffmpeg as slow, so `-m 'not slow'` is a quick loop."""
    for item in items:
        fixtures = set(getattr(item, "fixturenames", ()))
        if fixtures & SLOW_FIXTURES or item.module.__name__.split(".")[-1] in SLOW_MODULES:
            item.add_marker(pytest.mark.slow)
            item.add_marker(pytest.mark.timeout(300))  # browsers / ffmpeg get a longer budget
