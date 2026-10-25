"""Builders and checks for the InteractionRequest / UserResponse pair (frontend-agnostic)."""

import uuid
from typing import Any

from app.core.features import check_selection
from app.schemas.generated.interaction import InteractionRequest
from app.schemas.generated.user_response import UserResponse

ALLOWED_ACTIONS: dict[str, list[str]] = {
    "confirm_understanding": ["answer", "edit", "explore_more", "cancel"],
    "login_required": ["login_done", "answer", "cancel"],
    "select_features": ["answer", "explore_more", "cancel"],
    "choose_concept": ["answer", "regenerate", "cancel"],
    "outline_review": ["approve", "edit", "regenerate", "cancel"],
    "script_review": ["approve", "edit", "regenerate", "revert", "cancel"],
}


def make_request(job_id: str, kind: str, message: str, **fields: Any) -> InteractionRequest:
    """Build a request; allowed_actions defaults from ALLOWED_ACTIONS for the proposal kinds."""
    fields.setdefault("allowed_actions", ALLOWED_ACTIONS.get(kind, ["cancel"]))
    return InteractionRequest.model_validate(
        {
            "interaction_id": f"int_{uuid.uuid4().hex[:8]}",
            "job_id": job_id,
            "kind": kind,
            "message": message,
            **fields,
        }
    )


def make_response(request: InteractionRequest, action: str, **fields: Any) -> UserResponse:
    return UserResponse.model_validate(
        {
            "interaction_id": request.interaction_id,
            "job_id": request.job_id,
            "action": action,
            **fields,
        }
    )


def check_response(request: InteractionRequest, response: UserResponse) -> list[str]:
    """Errors when a response does not belong to the request or uses a disallowed action."""
    errors: list[str] = []
    if response.interaction_id != request.interaction_id:
        errors.append("interaction_id does not match the request")
    if response.action not in request.allowed_actions:
        errors.append(
            f"action '{response.action}' not allowed for {request.kind} "
            f"(allowed: {', '.join(request.allowed_actions)})"
        )
    if request.kind == "select_features" and response.action == "answer" and request.profile:
        selected = (response.answers or {}).get("selected_features")
        errors += check_selection(request.profile, selected)
    return errors
