"""Ask the user one question: check the answer, keep a log without secrets, honour "cancel"."""

import json
from pathlib import Path
from typing import Any

from app.core.interaction import check_response
from app.pipeline.frontend import Frontend
from app.schemas.generated.interaction import InteractionRequest
from app.schemas.generated.user_response import UserResponse

SECRET_KEYS = {"password", "passwd", "username", "email", "otp", "token", "secret", "credentials"}


class Cancelled(RuntimeError):
    """The user chose cancel."""


def redact(value: Any) -> Any:
    """Copy of `value` with every secret field blanked (credentials never reach a log)."""
    if isinstance(value, dict):
        return {
            k: ("***" if k.lower() in SECRET_KEYS and v else redact(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def ask(frontend: Frontend, job_dir: Path, request: InteractionRequest) -> UserResponse:
    while True:
        response = frontend.ask(request)
        errors = check_response(request, response)
        if not errors:
            break
        frontend.info(f"[red]Phản hồi không hợp lệ: {'; '.join(errors)}[/]")
    with (job_dir / "interactions.jsonl").open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "request": request.model_dump(mode="json", exclude_none=True),
                    "response": redact(response.model_dump(mode="json", exclude_none=True)),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    if response.action == "cancel":
        raise Cancelled(request.kind)
    return response
