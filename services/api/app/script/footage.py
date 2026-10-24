"""How much of a video is real footage, and the structural rules that keep it high.

A scene "has a clip" when it is a feature_demo (recorded: interaction, navigation, showcase or
showcase_lite). hook / cta / before_after are text or a still image. The ratio is measured on the
estimated speech time (what the final video will last), so it can be checked before recording.
"""

from dataclasses import dataclass

from app.core.timing import estimate_speech_ms

MIN_RATIO = 0.5
MIN_RATIO_30S = 0.4
MAX_BEFORE_AFTER = 1


@dataclass(frozen=True)
class SceneFacts:
    type: str
    feature: str | None
    voiceover: str
    has_clip: bool


def min_ratio(duration_s: int) -> float:
    return MIN_RATIO_30S if duration_s <= 30 else MIN_RATIO


def footage_ratio(scenes: list[SceneFacts]) -> float:
    total = sum(estimate_speech_ms(s.voiceover) for s in scenes)
    if total <= 0:
        return 0.0
    return sum(estimate_speech_ms(s.voiceover) for s in scenes if s.has_clip) / total


def structure_issues(scenes: list[SceneFacts], duration_s: int) -> list[str]:
    """Soft rules (Vietnamese sentences the writer can act on); empty when the plan is good."""
    issues: list[str] = []
    hooks = [i for i, s in enumerate(scenes) if s.type == "hook"]
    if any(i != 0 for i in hooks):
        issues.append(
            "hook chỉ được dùng cho scene đầu tiên; beat ở giữa có tính năng chưa trình diễn được "
            "phải dùng feature_demo (chỉ vị trí) thay vì hook"
        )
    before_after = [i for i, s in enumerate(scenes) if s.type == "before_after"]
    if len(before_after) > MAX_BEFORE_AFTER:
        issues.append(f"chỉ được tối đa {MAX_BEFORE_AFTER} scene before_after mỗi video")
    for i in range(len(scenes) - 1):
        a, b = scenes[i], scenes[i + 1]
        if not a.has_clip and not b.has_clip:
            issues.append(f"scene {i + 1} và scene {i + 2} đều không có cảnh quay liền nhau")
    seen: set[str] = set()
    for i, s in enumerate(scenes, start=1):
        if s.type == "feature_demo" and s.feature:
            if s.feature in seen:
                issues.append(
                    f"scene {i}: tính năng «{s.feature}» đã được quay ở scene trước; chỉ lặp lại "
                    "khi là bước tiếp nối khác rõ ràng (không quay lại từ đầu)"
                )
            seen.add(s.feature)
    ratio = footage_ratio(scenes)
    if ratio < min_ratio(duration_s):
        issues.append(
            f"tỷ lệ cảnh quay thật chỉ {ratio:.2f}, cần ≥ {min_ratio(duration_s):.1f}: "
            "biến thêm beat thành feature_demo (có thể chỉ vị trí), giảm scene chỉ có chữ"
        )
    return issues
