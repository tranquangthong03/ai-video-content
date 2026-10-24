"""beat_feature_mapper: link middle beats of an outline to the features they demonstrate.

The LLM proposes a mapping; code enforces the rules (features must exist and belong to the concept,
hook and CTA stay unlinked, one feature per at most two beats, low confidence means no link).
"""

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.core.demo_steps import summarize_steps
from app.llm.json_call import JsonCaller
from app.llm.prompts import render
from app.schemas.generated.outline import Outline
from app.schemas.generated.product_profile import ProductProfile

MAX_BEATS_PER_FEATURE = 2
MIN_CONFIDENCE = 0.5


class MappingItem(BaseModel):
    beat_id: str
    feature_id: str | None = None
    confidence: float = 0.0
    reason: str = ""


class BeatMapping(BaseModel):
    mapping: list[MappingItem]


@dataclass
class MapResult:
    outline: Outline
    mapping: list[dict[str, Any]] = field(default_factory=list)  # what was decided, for the report
    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def feature_catalog(
    profile: ProductProfile, allowed: set[str] | None = None
) -> list[dict[str, Any]]:
    return [
        {
            "id": f.id,
            "name": f.name,
            "description": f.description,
            "demo_kind": f.demo_kind,
            "demo_steps_summary": summarize_steps(f),
        }
        for f in profile.features
        if allowed is None or f.id in allowed
    ]


def needs_mapping(outline: Outline) -> bool:
    """True when a middle beat has no feature link (an outline from before the mapper)."""
    middle = outline.beats[1:-1]
    return any(b.feature_id is None for b in middle)


def map_beats(
    caller: JsonCaller,
    profile: ProductProfile,
    outline: Outline,
    *,
    only_missing: bool = True,
    only_beats: set[str] | None = None,
) -> MapResult:
    """Fill in feature_id on middle beats. Links already set by the user are kept (only_missing).

    only_beats limits the changes to those beats (e.g. the ones an edit just added or reworded).
    """
    result = MapResult(outline=outline.model_copy(deep=True))
    out = result.outline
    if len(out.beats) < 3:
        return result
    known = {f.id for f in profile.features}
    allowed = {fid for fid in out.feature_ids if fid in known} or known
    catalog = feature_catalog(profile, allowed)
    prompt = render(
        "beat_feature_mapper",
        outline_json=out.model_dump_json(indent=1),
        features_json=json.dumps(catalog, ensure_ascii=False, indent=1),
    )
    proposal = caller.call("beat_map", prompt, BeatMapping)

    beat_ids = {b.id for b in out.beats}
    first, last = out.beats[0].id, out.beats[-1].id
    chosen: dict[str, MappingItem] = {}
    for item in proposal.mapping:
        if item.beat_id not in beat_ids:
            result.warnings.append(f"bỏ qua gán cho beat không tồn tại: {item.beat_id}")
            continue
        if only_beats is not None and item.beat_id not in only_beats:
            continue
        if item.feature_id is None:
            continue
        if item.beat_id in (first, last):
            result.warnings.append(f"{item.beat_id} là mở đầu/kết nên không gắn tính năng")
            continue
        if item.feature_id not in allowed:
            result.warnings.append(
                f"{item.beat_id}: tính năng «{item.feature_id}» không thuộc hướng video, bỏ qua"
            )
            continue
        if item.confidence < MIN_CONFIDENCE:
            result.warnings.append(
                f"{item.beat_id}: độ chắc chắn thấp ({item.confidence:.2f}), để trống"
            )
            continue
        chosen[item.beat_id] = item

    # existing links count toward the per-feature limit; hook and CTA never keep a link
    used: dict[str, int] = {}
    for beat in out.beats:
        if beat.id in (first, last):
            if beat.feature_id:
                result.changes.append(f"Bỏ liên kết tính năng ở {beat.id} (mở đầu/kết)")
                beat.feature_id = None
        elif beat.feature_id:
            used[beat.feature_id] = used.get(beat.feature_id, 0) + 1

    by_feature: dict[str, list[MappingItem]] = {}
    for beat in out.beats:
        item = chosen.get(beat.id)
        if item and item.feature_id and (beat.feature_id is None or not only_missing):
            by_feature.setdefault(item.feature_id, []).append(item)
    for fid, items in by_feature.items():
        room = MAX_BEATS_PER_FEATURE - used.get(fid, 0)
        items.sort(key=lambda i: i.confidence, reverse=True)
        for dropped in items[max(room, 0) :]:
            result.warnings.append(
                f"{dropped.beat_id}: «{fid}» đã dùng cho {MAX_BEATS_PER_FEATURE} beat, bỏ qua"
            )
            chosen.pop(dropped.beat_id, None)

    names = {f.id: f.name for f in profile.features}
    for beat in out.beats:
        item = chosen.get(beat.id)
        if item and item.feature_id and (beat.feature_id is None or not only_missing):
            beat.feature_id = item.feature_id
            result.changes.append(
                f"Gắn {beat.id} với «{names.get(item.feature_id, item.feature_id)}»"
            )
    result.mapping = [
        {
            "beat_id": b.id,
            "feature_id": b.feature_id,
            "confidence": chosen[b.id].confidence if b.id in chosen else None,
            "reason": chosen[b.id].reason if b.id in chosen else "",
        }
        for b in out.beats
    ]
    return result
