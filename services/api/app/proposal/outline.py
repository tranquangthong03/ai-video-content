"""outline_review: beat sheet, LLM-planned edits and deterministic application of ops."""

import re
from dataclasses import dataclass, field

from app.core.interaction import make_request
from app.llm.json_call import JsonCaller
from app.llm.prompts import render
from app.schemas.generated.beat_op import (
    DeleteBeatOp,
    InsertBeatOp,
    MoveBeatOp,
    SetBeatOp,
    SetMetaOp,
)
from app.schemas.generated.interaction import InteractionRequest
from app.schemas.generated.outline import Beat, Outline
from app.schemas.generated.outline_edit_plan import OutlineEditPlan
from app.schemas.generated.product_profile import ProductProfile
from app.schemas.generated.video_concept import VideoConcept

GOALS = ("awareness", "conversion", "tutorial", "recruitment")
DURATIONS = (30, 45, 60)
MIN_BEATS, MAX_BEATS = 4, 6


@dataclass
class ApplyResult:
    outline: Outline
    changes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def outline_from_concept(concept: VideoConcept, profile: ProductProfile) -> Outline:
    """Beats come straight from the concept (b1..bn); a beat links to a feature it names."""
    by_name = {f.name.lower(): f.id for f in profile.features}
    beats = []
    for i, text in enumerate(concept.beats, start=1):
        linked = next((fid for name, fid in by_name.items() if name in text.lower()), None)
        beats.append(Beat(id=f"b{i}", text=text, feature_id=linked))
    return Outline(
        concept_id=concept.id,
        title=concept.title,
        goal=concept.goal,
        duration_s=concept.duration_s,
        feature_ids=concept.feature_ids,
        beats=beats,
        version=1,
    )


def profile_summary(profile: ProductProfile) -> str:
    lines = [f"{profile.product_name}: {profile.one_liner}", "Tính năng (id | tên | demo_kind):"]
    lines += [f"- {f.id} | {f.name} | {f.demo_kind or 'chưa kiểm chứng'}" for f in profile.features]
    return "\n".join(lines)


def edit_outline(
    caller: JsonCaller,
    profile: ProductProfile,
    concept: VideoConcept,
    outline: Outline,
    instruction: str,
) -> OutlineEditPlan:
    prompt = render(
        "outline_editor",
        confirmed_profile_summary=profile_summary(profile),
        concept_json=concept.model_dump_json(indent=1),
        version=outline.version,
        outline_json=outline.model_dump_json(indent=1),
        instruction=instruction,
    )
    return caller.call("outline", prompt, OutlineEditPlan)


def _index(beats: list[Beat], beat_id: str) -> int | None:
    return next((i for i, b in enumerate(beats) if b.id == beat_id), None)


def _next_id(beats: list[Beat], used: set[str]) -> str:
    numbers = [int(m.group(1)) for b in beats if (m := re.fullmatch(r"b(\d+)", b.id))]
    numbers += [int(m.group(1)) for u in used if (m := re.fullmatch(r"b(\d+)", u))]
    return f"b{max(numbers, default=0) + 1}"


def apply_ops(
    outline: Outline,
    ops: list,
    valid_feature_ids: set[str] | None = None,  # type: ignore[type-arg]
) -> ApplyResult:
    """Apply BeatOps deterministically. Beats that no op mentions are left exactly as they were."""
    result = ApplyResult(outline=outline.model_copy(deep=True))
    out = result.outline
    used_ids = {b.id for b in out.beats}  # ids are never reused, even after a delete

    def feature(fid: str | None) -> str | None:
        if fid and valid_feature_ids is not None and fid not in valid_feature_ids:
            result.warnings.append(f"feature_id '{fid}' không có trong sản phẩm, đã bỏ liên kết")
            return None
        return fid

    for wrapped in ops:
        op = getattr(wrapped, "root", wrapped)
        if isinstance(op, SetBeatOp):
            i = _index(out.beats, op.beat_id)
            if i is None:
                result.errors.append(f"set: không có beat {op.beat_id}")
                continue
            old = out.beats[i].text
            out.beats[i] = Beat(id=op.beat_id, text=op.text, feature_id=feature(op.feature_id))
            result.changes.append(f"Sửa {op.beat_id}: «{old}» → «{op.text}»")
        elif isinstance(op, DeleteBeatOp):
            i = _index(out.beats, op.beat_id)
            if i is None:
                result.errors.append(f"delete: không có beat {op.beat_id}")
                continue
            removed = out.beats.pop(i)
            result.changes.append(f"Xóa {op.beat_id}: «{removed.text}»")
        elif isinstance(op, InsertBeatOp):
            at = 0
            if op.after_beat_id is not None:
                j = _index(out.beats, op.after_beat_id)
                if j is None:
                    result.errors.append(f"insert: không có beat {op.after_beat_id}")
                    continue
                at = j + 1
            new_id = _next_id(out.beats, used_ids)
            used_ids.add(new_id)
            out.beats.insert(at, Beat(id=new_id, text=op.text, feature_id=feature(op.feature_id)))
            result.changes.append(f"Thêm {new_id}: «{op.text}»")
        elif isinstance(op, MoveBeatOp):
            i = _index(out.beats, op.beat_id)
            if i is None:
                result.errors.append(f"move: không có beat {op.beat_id}")
                continue
            beat = out.beats.pop(i)
            at = 0
            if op.after_beat_id is not None:
                j = _index(out.beats, op.after_beat_id)
                if j is None:
                    out.beats.insert(i, beat)  # restore
                    result.errors.append(f"move: không có beat {op.after_beat_id}")
                    continue
                at = j + 1
            out.beats.insert(at, beat)
            result.changes.append(f"Chuyển {op.beat_id} sang vị trí {at + 1}")
        elif isinstance(op, SetMetaOp):
            _apply_meta(out, op, result)

    if result.changes:
        out.version += 1
    if not MIN_BEATS <= len(out.beats) <= MAX_BEATS:
        result.warnings.append(f"Dàn ý có {len(out.beats)} beat (nên {MIN_BEATS}–{MAX_BEATS})")
    return result


def _apply_meta(out: Outline, op: SetMetaOp, result: ApplyResult) -> None:
    value = op.value
    if op.field == "title":
        out.title = str(value)
    elif op.field == "goal":
        if value not in GOALS:
            result.errors.append(f"set_meta: goal '{value}' không hợp lệ")
            return
        out.goal = value  # type: ignore[assignment]
    elif op.field == "duration_s":
        try:
            seconds = int(float(value))
        except (TypeError, ValueError):
            seconds = -1
        if seconds not in DURATIONS:
            result.errors.append(f"set_meta: duration_s '{value}' không hợp lệ (30/45/60)")
            return
        out.duration_s = seconds  # type: ignore[assignment]
    result.changes.append(f"Đổi {op.field} thành «{value}»")


def build_request(
    job_id: str,
    outline: Outline,
    *,
    changes: list[str] | None = None,
    notice: str = "",
    profile: ProductProfile | None = None,
) -> InteractionRequest:
    message = (
        "Đây là dàn ý video. Bạn duyệt, hoặc nhập yêu cầu sửa bằng câu tự do "
        "(ví dụ: «đổi mở đầu thành câu hỏi», «bỏ ý 3»)."
    )
    return make_request(
        job_id,
        "outline_review",
        f"{notice}\n{message}" if notice else message,
        outline=outline.model_dump(),
        profile=profile.model_dump() if profile else None,  # lets the UI show feature names
        changes=changes,
        script_version=outline.version,
    )
