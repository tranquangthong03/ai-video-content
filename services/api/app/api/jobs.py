"""REST endpoints for jobs. Everything is read from (and answers are written to) the job dir."""

import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.api.worker import JOB_FILE, JobRunner
from app.core.timing import estimate_speech_ms
from app.pipeline.file_frontend import PENDING, RESPONSES, write_json_atomic
from app.pipeline.state import IO_LOCK, STEP_LABELS, read_state
from app.schemas.generated.user_response import UserResponse

router = APIRouter(prefix="/api")
MAX_AUTH_BYTES = 2_000_000
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
FINAL_STATUSES = ("done", "failed", "cancelled")


def runner_of(request: Request) -> JobRunner:
    runner: JobRunner = request.app.state.runner
    return runner


def job_dir_of(request: Request, job_id: str) -> Path:
    if not ID_RE.match(job_id):
        raise HTTPException(404, "Không tìm thấy công việc")
    directory = runner_of(request).job_dir(job_id)
    if not (directory / "state.json").is_file():
        raise HTTPException(404, "Không tìm thấy công việc")
    return directory


def valid_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(422, "Địa chỉ website phải bắt đầu bằng http:// hoặc https://")
    return url.strip()


def read_json(path: Path) -> Any:
    try:
        with IO_LOCK:
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def thumb_rel(path: str | None) -> str | None:
    """Explorer thumbnails are stored as paths from where the explorer ran: keep the part below
    the job dir (explore/verify/...), which the files endpoint can serve."""
    if not path:
        return None
    flat = path.replace("\\", "/")
    index = flat.rfind("explore/")
    return flat[index:] if index >= 0 else None


def with_thumbnails(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if profile:
        for feature in profile.get("features", []):
            feature["thumbnail_url"] = thumb_rel(feature.get("thumbnail"))
    return profile


# --- job detail ------------------------------------------------------------------------------


def history_of(directory: Path) -> list[dict[str, Any]]:
    file = directory / "interactions.jsonl"
    out: list[dict[str, Any]] = []
    if not file.is_file():
        return out
    for line in file.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        request, response = item.get("request", {}), item.get("response", {})
        out.append(
            {
                "kind": request.get("kind"),
                "interaction_id": request.get("interaction_id"),
                "action": response.get("action"),
                "answers": response.get("answers"),
                "instruction": (response.get("edit") or {}).get("instruction"),
            }
        )
    return out


def scene_view(scene: dict[str, Any]) -> dict[str, Any]:
    visual = scene.get("visual") or {}
    actions = visual.get("actions") or []
    mode = visual.get("mode")
    if mode == "recording":
        pointing = any(a.get("do") == "highlight" and a.get("text") == "group" for a in actions)
        shot = (
            "chỉ vị trí"
            if pointing
            else "cuộn-highlight"
            if any(a.get("do") == "highlight" for a in actions)
            else "thao tác"
        )
    else:
        shot = "ảnh" if mode == "screenshot" else "chữ"
    return {
        "id": scene.get("id"),
        "type": scene.get("type"),
        "shot": shot,
        "feature": scene.get("feature"),
        "key_point": scene.get("key_point"),
        "voiceover": scene.get("voiceover"),
        "on_screen_text": scene.get("on_screen_text"),
        "estimated_ms": estimate_speech_ms(scene.get("voiceover") or ""),
    }


def script_extra(directory: Path, version: int | None) -> dict[str, Any] | None:
    script = read_json(directory / "scripts" / f"v{version}.json") if version else None
    if script is None:
        return None
    report = read_json(directory / "script_report.json") or {}
    scenes = [scene_view(s) for s in script.get("scenes", [])]
    return {
        "version": version,
        "versions": report.get("versions", []),
        "title": script.get("title"),
        "headline": script.get("headline"),
        "headline_highlight": script.get("headline_highlight"),
        "badge": script.get("badge"),
        "theme": script.get("theme"),
        "target_duration_s": script.get("target_duration_s"),
        "scenes": scenes,
        "estimated_ms": sum(s["estimated_ms"] for s in scenes),
        "footage_ratio": report.get("footage_ratio"),
        "footage_min": report.get("footage_min"),
        "recommended_duration_s": report.get("recommended_duration_s"),
        "warnings": report.get("warnings", []),
        "fit": report.get("fit"),
    }


def report_summary(directory: Path) -> dict[str, Any] | None:
    report = read_json(directory / "report.json")
    if report is None:
        return None
    return {
        "headline": report.get("headline"),
        "target_ms": report.get("target_ms"),
        "estimated_ms": report.get("estimated_ms"),
        "actual_ms": report.get("actual_ms"),
        "footage_ratio": report.get("footage_ratio"),
        "idle_ok": report.get("idle_ok"),
        "recommended_duration_s": report.get("recommended_duration_s"),
        "features": report.get("features", []),
        "warnings": [*report.get("script_warnings", []), *report.get("warnings", [])],
        "scenes": [
            {
                k: s.get(k)
                for k in ("id", "type", "kind", "speech_ms", "final_ms", "idle_max_ms", "warnings")
            }
            for s in report.get("scenes", [])
        ],
    }


def detail(runner: JobRunner, job_id: str) -> dict[str, Any]:
    directory = runner.job_dir(job_id)
    state = read_state(directory)
    assert state is not None
    pending = read_json(directory / PENDING)
    extra: dict[str, Any] | None = None
    if pending:
        kind = pending.get("kind")
        if kind == "script_review":
            extra = script_extra(directory, pending.get("script_version"))
        for key in ("profile",):
            if pending.get(key):
                with_thumbnails(pending[key])
    video = directory / "video.mp4"
    done = state.status == "done" and video.is_file()
    return {
        "state": state.as_dict(),
        "steps": [{"id": k, "label": v} for k, v in STEP_LABELS.items()],
        "queue_position": runner.position(job_id),
        "pending": pending,
        "pending_extra": extra,
        "history": history_of(directory),
        "video_url": f"/api/jobs/{job_id}/files/video.mp4" if done else None,
        "report": report_summary(directory) if done else None,
        "can_resume": state.status in ("failed", "cancelled"),
    }


# --- endpoints -------------------------------------------------------------------------------


@router.post("/jobs", status_code=201)
async def create_job(
    request: Request,
    url: Annotated[str, Form()],
    storage_state: Annotated[UploadFile | None, File()] = None,
) -> dict[str, Any]:
    url = valid_url(url)
    runner = runner_of(request)
    auth_bytes: bytes | None = None
    if storage_state is not None and storage_state.filename:
        auth_bytes = await storage_state.read(MAX_AUTH_BYTES + 1)
        try:
            ok = len(auth_bytes) <= MAX_AUTH_BYTES and isinstance(json.loads(auth_bytes), dict)
        except ValueError:
            ok = False
        if not ok:
            raise HTTPException(422, "File đăng nhập phải là JSON (auth.json) hợp lệ, dưới 2 MB")
    job_id = f"j{uuid.uuid4().hex[:10]}"
    directory = runner.create(job_id, url, has_auth=auth_bytes is not None)
    if auth_bytes is not None:
        (directory / "storage_state.json").write_bytes(auth_bytes)
    runner.submit(job_id)
    return detail(runner, job_id)


@router.get("/jobs")
def list_jobs(request: Request) -> list[dict[str, Any]]:
    runner = runner_of(request)
    return [{**s.as_dict(), "queue_position": runner.position(s.job_id)} for s in runner.jobs()]


@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str) -> dict[str, Any]:
    job_dir_of(request, job_id)
    return detail(runner_of(request), job_id)


def check_answer(pending: dict[str, Any] | None, response: UserResponse, job_id: str) -> None:
    if pending is None:
        raise HTTPException(409, "Hiện không có câu hỏi nào đang chờ bạn trả lời")
    if response.job_id != job_id:
        raise HTTPException(422, "Phản hồi này không thuộc công việc đang mở")
    if response.interaction_id != pending["interaction_id"]:
        raise HTTPException(409, "Câu hỏi này đã được trả lời hoặc đã thay đổi, hãy tải lại trang")
    allowed = pending.get("allowed_actions", [])
    if response.action not in allowed:
        raise HTTPException(
            422,
            f"Hành động «{response.action}» không hợp lệ ở bước này "
            f"(cho phép: {', '.join(allowed)})",
        )
    version = pending.get("script_version")
    if (
        response.base_version is not None
        and version is not None
        and response.base_version != version
    ):
        raise HTTPException(
            409, f"Bạn đang xem bản v{response.base_version}, bản mới nhất là v{version}"
        )


@router.post("/jobs/{job_id}/respond")
def respond(request: Request, job_id: str, response: UserResponse) -> dict[str, Any]:
    directory = job_dir_of(request, job_id)
    pending = read_json(directory / PENDING)
    check_answer(pending, response, job_id)
    write_json_atomic(
        directory / RESPONSES / f"{response.interaction_id}.json",
        response.model_dump(mode="json", exclude_none=True),
    )
    return {"ok": True}


@router.post("/jobs/{job_id}/cancel")
def cancel(request: Request, job_id: str) -> dict[str, Any]:
    directory = job_dir_of(request, job_id)
    runner = runner_of(request)
    state = read_state(directory)
    assert state is not None
    if state.status in FINAL_STATUSES:
        raise HTTPException(409, "Công việc này đã kết thúc")
    runner.cancel(job_id)
    return detail(runner, job_id)


@router.post("/jobs/{job_id}/resume")
def resume(request: Request, job_id: str, redo_script: bool = False) -> dict[str, Any]:
    """Run again from what is saved. redo_script reopens the script review (after a video)."""
    directory = job_dir_of(request, job_id)
    runner = runner_of(request)
    state = read_state(directory)
    assert state is not None
    if state.status not in ("failed", "cancelled", "done"):
        raise HTTPException(409, "Công việc đang chạy, chưa thể chạy tiếp")
    approved = (directory / "outline_approved.json").is_file()
    from_step = "script" if approved else "explore"
    if redo_script:
        if not approved:
            raise HTTPException(409, "Chưa có dàn ý đã duyệt để sửa kịch bản")
        for name in ("script_approved.json", "video.mp4", "report.json"):
            (directory / name).unlink(missing_ok=True)
        shutil.rmtree(directory / "responses", ignore_errors=True)
    if not (directory / JOB_FILE).is_file():
        raise HTTPException(409, "Thiếu thông tin công việc, hãy tạo công việc mới")
    runner.submit(job_id, resume=True, from_step=from_step)
    return detail(runner, job_id)


@router.get("/jobs/{job_id}/files/{path:path}")
def get_file(request: Request, job_id: str, path: str) -> FileResponse:
    """Serve a file from inside the job dir only (Range requests are handled by FileResponse)."""
    directory = job_dir_of(request, job_id).resolve()
    target = (directory / path).resolve()
    if not target.is_relative_to(directory) or not target.is_file():
        raise HTTPException(404, "Không tìm thấy tệp")
    if target.name in ("storage_state.json", JOB_FILE) or target.suffix == ".log":
        raise HTTPException(404, "Không tìm thấy tệp")
    return FileResponse(target)
