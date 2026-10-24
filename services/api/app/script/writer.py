"""Script Writer: confirmed profile + approved outline -> Script.

The LLM writes the words (headline, voiceover, key points) and picks layouts, features and
show_setup.
Code does the rest: scene ids, theme, goal, and every `visual` (see visuals.py). The result is
validated (Pydantic, validate_script, length and word limits); errors go back to the LLM, at most
twice, with the list of what is wrong.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.demo_steps import summarize_steps
from app.llm.json_call import JsonCaller
from app.llm.prompts import render
from app.schemas.generated.layouts import LAYOUTS_BY_TYPE
from app.schemas.generated.outline import Outline
from app.schemas.generated.product_profile import Feature, ProductProfile
from app.schemas.generated.script import Script
from app.schemas.generated.theme import Theme
from app.script import catalog as cat
from app.script.validate import validate_script
from app.script.visuals import visual_for_scene

MAX_REPAIRS = 2
SceneType = Literal["hook", "feature_demo", "before_after", "cta"]


class DraftScene(BaseModel):
    """One scene as the LLM writes it (visual is ignored: code fills it)."""

    model_config = ConfigDict(extra="ignore")
    id: str = ""
    type: SceneType
    layout: str = ""
    feature: str | None = None
    before_text: str | None = None
    after_text: str | None = None
    voiceover: str = ""
    on_screen_text: str | None = None
    key_point: str | None = None
    icon: str | None = None
    show_setup: bool | None = None


class DraftScript(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = ""
    badge: str | None = None
    headline: str = ""
    headline_highlight: str | None = None
    scenes: list[DraftScene]


class SummaryItem(BaseModel):
    scene_id: str
    one_liner: str = ""


class WriterOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    script: DraftScript
    summary: list[SummaryItem] = []
    warnings: list[str] = []


@dataclass
class WriterContext:
    profile: ProductProfile
    outline: Outline
    theme: Theme
    home_url: str
    setup_counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)  # tone / audience given by the user (set_global)

    @property
    def features(self) -> dict[str, Feature]:
        return {f.id: f for f in self.profile.features}


@dataclass
class WriterResult:
    script: Script
    summary: list[dict[str, str]]
    warnings: list[str]
    attempts: int
    errors_history: list[list[str]] = field(default_factory=list)


class WriterError(RuntimeError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors[:5]))
        self.errors = errors


# --- prompt inputs --------------------------------------------------------------------------------


def target_words(duration_s: int, scenes: int) -> int:
    """Voiceover words that fill duration_s once each scene's 250 ms pause counts (2.5 words/s)."""
    return max(1, round((duration_s * 1000 - 250 * scenes) / 400))


def profile_for_prompt(ctx: WriterContext) -> dict[str, Any]:
    """The part of the profile the writer needs, with what each demo shows (not raw locators)."""
    p = ctx.profile
    return {
        "product_name": p.product_name,
        "one_liner": p.one_liner,
        "target_users": p.target_users,
        "value_props": getattr(p, "value_props", []),
        "features": [
            {
                "id": f.id,
                "name": f.name,
                "description": f.description,
                "importance": f.importance,
                "demo_kind": f.demo_kind,
                "requires_setup": f.requires_setup,
                "demo_steps": summarize_steps(f),
            }
            for f in p.features
        ],
    }


def build_prompt(ctx: WriterContext) -> str:
    outline = ctx.outline
    prompt = render(
        "script_writer",
        product_profile_json=json.dumps(profile_for_prompt(ctx), ensure_ascii=False, indent=1),
        outline_json=outline.model_dump_json(indent=1),
        theme_json=ctx.theme.model_dump_json(indent=1),
        scene_catalog_json=cat.scene_catalog_json(),
        allowed_icons=", ".join(cat.ICONS),
        duration_s=outline.duration_s,
        target_words=target_words(outline.duration_s, len(outline.beats)),
    )
    if ctx.notes:  # appended after the template so the template itself stays as agreed
        listed = "\n".join(f"- {n}" for n in ctx.notes)
        prompt += f"\n<user_notes>\nNgười dùng yêu cầu thêm:\n{listed}\n</user_notes>\n"
    return prompt


# --- checks ---------------------------------------------------------------------------------------


def check_scene(s: DraftScene, label: str, features: dict[str, Feature]) -> list[str]:
    """Limits that hold for every scene, whoever wrote it (writer, scene writer, user edit)."""
    errors: list[str] = []
    if s.layout not in LAYOUTS_BY_TYPE[s.type]:
        errors.append(
            f"{label}: layout «{s.layout}» không hợp lệ cho {s.type} "
            f"(chọn một trong {', '.join(LAYOUTS_BY_TYPE[s.type])})"
        )
    words = cat.word_count(s.voiceover)
    if not cat.VOICEOVER_MIN_WORDS <= words <= cat.VOICEOVER_MAX_WORDS:
        errors.append(
            f"{label}: voiceover có {words} từ, cần "
            f"{cat.VOICEOVER_MIN_WORDS}–{cat.VOICEOVER_MAX_WORDS}"
        )
    if cat.word_count(s.on_screen_text) > cat.ON_SCREEN_MAX_WORDS:
        errors.append(f"{label}: on_screen_text quá {cat.ON_SCREEN_MAX_WORDS} từ")
    if not s.key_point or not s.key_point.strip():
        errors.append(f"{label}: thiếu key_point")
    elif len(s.key_point) > cat.KEY_POINT_MAX:
        errors.append(
            f"{label}: key_point dài {len(s.key_point)} ký tự, tối đa {cat.KEY_POINT_MAX}"
        )
    if s.icon not in cat.ICONS:
        errors.append(f"{label}: icon «{s.icon}» không thuộc danh sách ({', '.join(cat.ICONS)})")
    if s.type == "feature_demo":
        if not s.feature:
            errors.append(f"{label}: feature_demo thiếu feature")
        elif s.feature not in features:
            errors.append(f"{label}: feature «{s.feature}» không có trong product")
    elif s.feature:
        errors.append(f"{label}: chỉ feature_demo mới có field feature")
    if s.type == "before_after":
        for name in ("before_text", "after_text"):
            text = getattr(s, name)
            if not text or not text.strip():
                errors.append(f"{label}: before_after thiếu {name}")
            elif cat.word_count(text) > cat.BEFORE_AFTER_MAX_WORDS:
                errors.append(f"{label}: {name} quá {cat.BEFORE_AFTER_MAX_WORDS} từ")
    elif s.before_text or s.after_text:
        errors.append(f"{label}: chỉ before_after mới có before_text/after_text")
    return errors


def check_draft(draft: DraftScript, ctx: WriterContext) -> list[str]:
    """Everything wrong with a draft, as sentences the LLM can act on."""
    errors: list[str] = []
    features = ctx.features
    beats = ctx.outline.beats
    scenes = draft.scenes
    if draft.badge is not None and len(draft.badge) > cat.BADGE_MAX:
        errors.append(f"badge dài {len(draft.badge)} ký tự, tối đa {cat.BADGE_MAX}")
    if not draft.headline.strip():
        errors.append("thiếu headline")
    elif len(draft.headline) > cat.HEADLINE_MAX:
        errors.append(f"headline dài {len(draft.headline)} ký tự, tối đa {cat.HEADLINE_MAX}")
    if draft.headline_highlight and draft.headline_highlight not in draft.headline:
        errors.append("headline_highlight phải là chuỗi con của headline")

    if len(scenes) != len(beats):
        errors.append(f"cần đúng {len(beats)} scene (mỗi beat một scene), hiện có {len(scenes)}")
    if scenes and scenes[0].type != "hook":
        errors.append("scene đầu phải là hook")
    if scenes and scenes[-1].type != "cta":
        errors.append("scene cuối phải là cta")
    seen: dict[str, str] = {}
    for i, scene in enumerate(scenes):
        label = f"scene {i + 1}"
        errors += check_scene(scene, label, features)
        beat = beats[i] if i < len(beats) else None
        if beat and beat.feature_id:
            feature = features.get(beat.feature_id)
            demoable = feature is not None and feature.demo_kind in cat.DEMOABLE
            if demoable and (scene.type != "feature_demo" or scene.feature != beat.feature_id):
                errors.append(
                    f"{label}: beat {beat.id} trình diễn «{beat.feature_id}» nên phải là "
                    f"feature_demo với feature = {beat.feature_id}"
                )
        key = (scene.key_point or "").strip().lower()
        if key:
            if key in seen:
                errors.append(f"{label}: key_point trùng với {seen[key]}")
            seen[key] = label
    return errors


# --- building -------------------------------------------------------------------------------------


def scene_dict(
    s: DraftScene, scene_id: str, ctx: WriterContext, warnings: list[str]
) -> dict[str, Any]:
    feature = ctx.features.get(s.feature) if s.feature else None
    visual = visual_for_scene(
        s.type,
        feature,
        ctx.home_url,
        setup_len=ctx.setup_counts.get(s.feature or ""),
        show_setup=bool(s.show_setup),
        scene_id=scene_id,
    )
    warnings += visual.warnings
    out: dict[str, Any] = {
        "id": scene_id,
        "type": s.type,
        "layout": s.layout,
        "voiceover": s.voiceover.strip(),
        "on_screen_text": (s.on_screen_text or None) and s.on_screen_text.strip(),
        "key_point": s.key_point.strip() if s.key_point else None,
        "icon": s.icon,
        "visual": visual.visual,
    }
    if s.type == "feature_demo":
        out["feature"] = s.feature
    if s.type == "before_after":
        out["before_text"] = (s.before_text or "").strip()
        out["after_text"] = (s.after_text or "").strip()
    return out


def build_script(draft: DraftScript, ctx: WriterContext) -> tuple[Script, list[str]]:
    """Assemble the Script (code-made ids, theme, goal and visuals). Raises WriterError."""
    warnings: list[str] = []
    scenes = [scene_dict(s, f"s{i}", ctx, warnings) for i, s in enumerate(draft.scenes, start=1)]
    data: dict[str, Any] = {
        "title": draft.title.strip() or ctx.outline.title,
        "goal": ctx.outline.goal,
        "aspect_ratio": "9:16",
        "target_duration_s": ctx.outline.duration_s,
        "template": "desktop_showcase",
        "badge": draft.badge,
        "headline": draft.headline.strip(),
        "headline_highlight": draft.headline_highlight or None,
        "theme": ctx.theme.model_dump(),
        "scenes": scenes,
    }
    try:
        script = Script.model_validate(data)
    except ValidationError as e:
        raise WriterError(
            [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:8]]
        ) from e
    problems = validate_script(script)
    if problems:
        raise WriterError(problems)
    return script, warnings


def summary_for(script: Script, given: list[SummaryItem]) -> list[dict[str, str]]:
    """One line per scene: the LLM's, matched by id or position, else the key point."""
    by_id = {g.scene_id: g.one_liner for g in given}
    out = []
    for i, scene in enumerate(script.scenes):
        s = scene.root
        text = (
            by_id.get(s.id) or (given[i].one_liner if i < len(given) else "") or s.key_point or ""
        )
        out.append({"scene_id": s.id, "one_liner": text})
    return out


def repair_prompt(base: str, previous: WriterOutput, errors: list[str]) -> str:
    listed = "\n".join(f"- {e}" for e in errors)
    return (
        f"{base}\n\n<previous_output>\n{previous.model_dump_json(indent=1)}\n</previous_output>\n\n"
        f"Kịch bản trên còn lỗi sau, hãy sửa đúng các lỗi này (giữ nguyên phần đã ổn) và trả lại "
        f"json đầy đủ cùng cấu trúc:\n{listed}"
    )


def write_script(caller: JsonCaller, ctx: WriterContext) -> WriterResult:
    """Ask for a script, validate, and send the errors back (at most MAX_REPAIRS times)."""
    base = build_prompt(ctx)
    prompt = base
    history: list[list[str]] = []
    output: WriterOutput | None = None
    for attempt in range(1, MAX_REPAIRS + 2):
        output = caller.call("script", prompt, WriterOutput)
        errors = check_draft(output.script, ctx)
        script: Script | None = None
        warnings: list[str] = []
        if not errors:
            try:
                script, warnings = build_script(output.script, ctx)
            except WriterError as e:
                errors = e.errors
        history.append(errors)
        if script is not None:
            return WriterResult(
                script,
                summary_for(script, output.summary),
                [*output.warnings, *warnings],
                attempt,
                history,
            )
        prompt = repair_prompt(base, output, errors)
    raise WriterError(history[-1])
