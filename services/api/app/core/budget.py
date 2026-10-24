"""How much real content a product can fill, and the video length that follows from it.

content_budget_s = HOOK + CTA (+ one before_after) + the time each demonstrable feature earns:
  interaction  ~10 s (8-12)   navigation  6 s   showcase  5 s
Features that cannot be demonstrated (failed, unverified without evidence) earn nothing: they would
only be talked about. recommended_duration_s is the largest of 30/45/60 that the budget covers
(never below 30). A longer video is possible but then it has scenes without real footage.
"""

from dataclasses import dataclass

from app.schemas.generated.product_profile import Feature, ProductProfile

HOOK_S = 4
CTA_S = 4
BEFORE_AFTER_S = 5
FEATURE_S = {"interaction": 10, "navigation": 6, "showcase": 5}
DURATIONS = (30, 45, 60)
FORMULA = (
    "content_budget_s = 4 (hook) + 4 (cta) + 5 (one before_after) + sum over demonstrable "
    "features: interaction 10, navigation 6, showcase 5"
)


@dataclass(frozen=True)
class Budget:
    content_budget_s: int
    recommended_duration_s: int
    demonstrable: int  # features that earn footage
    formula: str = FORMULA


def feature_seconds(feature: Feature) -> int:
    return FEATURE_S.get(feature.demo_kind or "", 0)


def content_budget_s(profile: ProductProfile) -> int:
    return HOOK_S + CTA_S + BEFORE_AFTER_S + sum(feature_seconds(f) for f in profile.features)


def recommended_duration_s(budget_s: int) -> int:
    """Largest of 30/45/60 that does not exceed the budget; 30 when even that is more than it."""
    fitting = [d for d in DURATIONS if d <= budget_s]
    return max(fitting) if fitting else DURATIONS[0]


def budget_for(profile: ProductProfile) -> Budget:
    seconds = content_budget_s(profile)
    return Budget(
        seconds,
        recommended_duration_s(seconds),
        sum(1 for f in profile.features if feature_seconds(f) > 0),
    )


def oversize_warning(requested_s: int, budget: Budget) -> str | None:
    """Warning (Vietnamese) when a video is longer than the product can fill with real footage."""
    if requested_s <= budget.recommended_duration_s:
        return None
    return (
        f"Sản phẩm có {budget.demonstrable} tính năng trình diễn được, video {requested_s}s "
        f"sẽ có nhiều cảnh không quay thao tác (đề xuất {budget.recommended_duration_s}s)."
    )
