"""confirm_understanding: show what we understood about the product and let the user correct it."""

from dataclasses import dataclass, field

from app.core.interaction import make_request
from app.schemas.generated.interaction import InteractionRequest
from app.schemas.generated.product_profile import Feature, ProductProfile
from app.schemas.generated.user_response import UserResponse


def score_dots(feature: Feature) -> str:
    """●●● / ●●○ / ○○○ for demo_score; unverified features are marked as such."""
    if not feature.verified and feature.source == "site":
        return "○○○ (chưa kiểm chứng)"
    if feature.source == "user" and not feature.verified:
        return "○○○ (bạn thêm, chưa xác minh)"
    if feature.demo_score >= 1:
        return "●●●"
    return "●●○" if feature.demo_score >= 0.5 else "○○○"


@dataclass
class ProfileEdits:
    """Cumulative user corrections applied on top of the explorer profile (left untouched)."""

    exclude: set[str] = field(default_factory=set)
    one_liner: str | None = None
    target_users: list[str] | None = None
    added: list[tuple[str, str]] = field(default_factory=list)  # (name, description)
    answers: dict[str, str | list[str]] = field(default_factory=dict)


def merge_response(edits: ProfileEdits, response: UserResponse) -> ProfileEdits:
    """Fold one UserResponse (action edit/answer) into the cumulative edits."""
    if response.answers:
        edits.answers.update(response.answers)
    pe = response.profile_edit
    if pe is not None:
        edits.exclude |= set(pe.exclude_feature_ids)  # cumulative: ids dropped so far
        if pe.one_liner:
            edits.one_liner = pe.one_liner
        if pe.target_users is not None:
            edits.target_users = pe.target_users
        edits.added += [(f.name, f.description) for f in pe.added_features]
    return edits


def apply_edits(base: ProductProfile, edits: ProfileEdits) -> ProductProfile:
    profile = base.model_copy(deep=True)
    profile.features = [f for f in profile.features if f.id not in edits.exclude]
    if edits.one_liner:
        profile.one_liner = edits.one_liner
    if edits.target_users is not None:
        profile.target_users = edits.target_users
    taken = {f.id for f in profile.features}
    for i, (name, description) in enumerate(edits.added, start=1):
        fid = f"u{i}"
        while fid in taken:
            fid += "_"
        taken.add(fid)
        profile.features.append(
            Feature(
                id=fid,
                name=name,
                description=description,
                evidence=[],
                importance=0.5,
                demo_steps=[],
                demo_score=0.0,
                verified=False,
                source="user",
            )
        )
    return profile


def build_request(
    job_id: str, profile: ProductProfile, *, round_no: int = 1, notice: str = ""
) -> InteractionRequest:
    message = (
        f"Mình hiểu sản phẩm là «{profile.product_name}»: {profile.one_liner}. "
        "Bạn kiểm tra danh sách tính năng bên dưới rồi xác nhận, hoặc sửa/bổ sung."
    )
    if notice:
        message = f"{notice}\n{message}"
    questions = [
        {"id": f"oq{i}", "text": q, "type": "text", "options": [], "allow_custom": True}
        for i, q in enumerate(profile.open_questions, start=1)
    ]
    return make_request(
        job_id,
        "confirm_understanding",
        message,
        profile=profile.model_dump(),
        questions=questions,
        script_version=round_no,
    )
