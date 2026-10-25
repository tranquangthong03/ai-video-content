"""select_features: the user picks (and orders) the 1-4 features the video will show."""

from app.core.features import MAX_SELECTED, MIN_SELECTED, RECOMMENDED_MAX
from app.core.interaction import make_request
from app.schemas.generated.interaction import InteractionRequest
from app.schemas.generated.product_profile import ProductProfile


def build_request(
    job_id: str,
    profile: ProductProfile,
    default: list[str],
    *,
    new_ids: list[str] | None = None,
    notice: str = "",
) -> InteractionRequest:
    message = (
        f"Chọn {MIN_SELECTED}–{MAX_SELECTED} tính năng sẽ xuất hiện trong video "
        f"(khuyến nghị 2–{RECOMMENDED_MAX}), theo thứ tự ưu tiên. "
        "Thiếu tính năng bạn cần? Mô tả hoặc dán URL để mình xem thêm."
    )
    return make_request(
        job_id,
        "select_features",
        f"{notice}\n{message}" if notice else message,
        profile=profile.model_dump(),
        selection={
            "min": MIN_SELECTED,
            "max": MAX_SELECTED,
            "recommended_max": RECOMMENDED_MAX,
            "default": default,
            "new_ids": new_ids or [],
        },
    )
