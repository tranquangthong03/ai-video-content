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
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.demo_steps import summarize_steps
from app.core.flow_ctx import FlowCtx
from app.llm.json_call import JsonCaller
from app.llm.prompts import render
from app.schemas.generated.layouts import LAYOUTS_BY_TYPE
from app.schemas.generated.outline import Outline
from app.schemas.generated.product_profile import Feature, ProductProfile
from app.schemas.generated.script import Script
from app.schemas.generated.theme import Theme
from app.script import catalog as cat
from app.script import narrative as nar
from app.script.autotrim import trim_draft
from app.script.footage import SceneFacts, structure_issues
from app.script.lite import MIN_WORDS as MIN_LITE_WORDS
from app.script.lite import LiteContext
from app.script.proof import (
    ProofBank,
    numbers_in,
    proof_used,
    strip_numbers,
    unsupported_numbers,
)
from app.script.signature import visual_signature
from app.script.tour import apply_tour, is_landing_only
from app.script.validate import validate_script
from app.script.visuals import visual_for_scene

MAX_REPAIRS = 2
SceneType = Literal["hook", "feature_demo", "before_after", "cta"]


class DraftStat(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: str = ""
    label: str = ""


class DraftHook(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: str = ""
    voiceover: str = ""
    on_screen_text: str | None = None


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
    stat: DraftStat | None = None


class DraftScript(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = ""
    badge: str | None = None
    headline: str = ""
    headline_highlight: str | None = None
    hook_options: list[DraftHook] = []
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
    lite: LiteContext | None = None  # lets failed/unverified features be pointed at (showcase_lite)
    flow: FlowCtx | None = None  # flow mode: each chapter is a pseudo-feature with its own visual

    # the video is longer than the product can fill with real footage and the user insisted
    forced: bool = False
    capture: tuple[int, int] | None = None  # recording size; None = the schema default (1440x900)
    proof: ProofBank | None = None  # real numbers / quotes / offers the words may lean on
    inventory: list[dict[str, Any]] = field(default_factory=list)  # frames of the filmed flow

    @property
    def framework(self) -> str | None:
        """Flow video: pain, journey, result. One-page tool: before, after, bridge."""
        if self.flow is not None:
            return "pain_journey_result"
        return "before_after_bridge" if self.profile.site_type == "tool" else None

    def given_numbers(self) -> list[str]:
        """Numbers the brief itself contains (product name, approved flow, duration, counts)."""
        texts = [self.profile.product_name, *self.outline.title.split()]
        flow = self.flow
        counts = [str(self.outline.duration_s)]
        if flow is not None:
            texts += [flow.title, flow.goal, flow.success_signal, flow.value, *flow.hero_texts]
            for c in flow.chapters:
                texts += [c.title, c.value_line or "", *c.notes]
            counts += [str(len(flow.chapters)), str(sum(c.steps for c in flow.chapters))]
        return counts + [v for t in texts for v, *_ in numbers_in(t)]

    @property
    def home_domain(self) -> str:
        return (urlparse(self.home_url).hostname or "").removeprefix("www.")

    @property
    def demo_max_words(self) -> int:
        return cat.FORCED_DEMO_MAX_WORDS if self.forced else cat.DEMO_VOICEOVER_MAX_WORDS

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
        flow_json=ctx.flow.prompt_json() if ctx.flow else "",
        proof_json=json.dumps(ctx.proof.to_dict(), ensure_ascii=False, indent=1)
        if ctx.proof and not ctx.proof.is_empty
        else "",
        framework=ctx.framework or "",
        product_name=ctx.profile.product_name,
        home_domain=ctx.home_domain,
        forbidden_phrases=", ".join(cat.FORBIDDEN_PHRASES),
        hook_kinds=", ".join(cat.HOOK_KINDS),
        hook_max_words=cat.HOOK_MAX_WORDS,
        on_screen_max_words=cat.ON_SCREEN_MAX_WORDS,
    )
    if ctx.notes:  # appended after the template so the template itself stays as agreed
        listed = "\n".join(f"- {n}" for n in ctx.notes)
        prompt += f"\n<user_notes>\nNgười dùng yêu cầu thêm:\n{listed}\n</user_notes>\n"
    return prompt


# --- checks ---------------------------------------------------------------------------------------


def check_scene(
    s: DraftScene,
    label: str,
    features: dict[str, Feature],
    demo_max: int = cat.VOICEOVER_MAX_WORDS,
    *,
    strict_min: bool = True,
) -> list[str]:
    """Limits that hold for every scene, whoever wrote it (writer, scene writer, user edit).

    strict_min=False: a voiceover that is too short is not an error (it cannot be fixed by code)."""
    errors: list[str] = []
    max_words = demo_max if s.type == "feature_demo" else cat.VOICEOVER_MAX_WORDS
    if s.layout not in LAYOUTS_BY_TYPE[s.type]:
        errors.append(
            f"{label}: layout «{s.layout}» không hợp lệ cho {s.type} "
            f"(chọn một trong {', '.join(LAYOUTS_BY_TYPE[s.type])})"
        )
    words = cat.word_count(s.voiceover)
    if words > max_words or (strict_min and words < cat.VOICEOVER_MIN_WORDS):
        errors.append(
            f"{label}: voiceover có {words} từ, cần {cat.VOICEOVER_MIN_WORDS}–{max_words}"
        )
    if cat.word_count(s.on_screen_text) > cat.ON_SCREEN_MAX_WORDS:
        errors.append(f"{label}: on_screen_text quá {cat.ON_SCREEN_MAX_WORDS} từ")
    for field_name, text in nar.scene_texts(s).items():
        if hits := nar.forbidden_in(text):
            errors.append(f"{label}: {field_name} dùng cụm sáo rỗng «{hits[0]}», hãy nói cụ thể")
    if s.stat and (
        not s.stat.value.strip()
        or not s.stat.label.strip()
        or len(s.stat.value) > cat.STAT_VALUE_MAX
        or len(s.stat.label) > cat.STAT_LABEL_MAX
    ):
        errors.append(
            f"{label}: stat cần value ≤ {cat.STAT_VALUE_MAX} và label ≤ {cat.STAT_LABEL_MAX} ký tự"
        )
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
        elif features[s.feature].demo_kind not in cat.DEMOABLE and words < MIN_LITE_WORDS:
            errors.append(
                f"{label}: scene chỉ vị trí quay khoảng 5 giây, voiceover cần ≥ {MIN_LITE_WORDS} từ"
            )
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


def check_draft(draft: DraftScript, ctx: WriterContext, *, strict_min: bool = True) -> list[str]:
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
    errors += narrative_errors(draft, ctx)
    seen: dict[str, str] = {}
    for i, scene in enumerate(scenes):
        label = f"scene {i + 1}"
        errors += check_scene(scene, label, features, ctx.demo_max_words, strict_min=strict_min)
        beat = beats[i] if i < len(beats) else None
        if beat and beat.feature_id:
            feature = features.get(beat.feature_id)
            # failed / unverified features are pointed at, so their beats are feature_demo too
            demoable = feature is not None and (
                feature.demo_kind in cat.DEMOABLE or ctx.lite is not None
            )
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


def narrative_errors(draft: DraftScript, ctx: WriterContext) -> list[str]:
    """Hook, hook options, CTA and headline rules that are checked by code."""
    errors: list[str] = []
    name = ctx.profile.product_name
    if hits := nar.forbidden_in(draft.headline):
        errors.append(f"headline dùng cụm sáo rỗng «{hits[0]}»")
    errors += nar.hook_option_issues(
        draft.hook_options,
        name,
        has_numbers=bool(ctx.proof and ctx.proof.numbers),
        required=ctx.flow is not None,
    )
    if draft.scenes and draft.scenes[0].type == "hook":
        first = draft.scenes[0]
        errors += nar.hook_line_issues("scene 1", first.voiceover, first.on_screen_text, name)
    for i, scene in enumerate(draft.scenes, start=1):
        if scene.type == "cta" and any(
            nar.reads_a_url(t) for t in (scene.voiceover, scene.on_screen_text)
        ):
            errors.append(f"scene {i}: cta không đọc URL; nói tên miền ngắn ({ctx.home_domain})")
    return errors


def draft_numbers(draft: DraftScript, ctx: WriterContext) -> dict[str, list[str]]:
    """Unsourced numbers per place ("scene 2 voiceover" ...). Empty when all have a source."""
    proof = ctx.proof
    if proof is None:
        return {}
    given = ctx.given_numbers()
    found: dict[str, list[str]] = {}

    def look(where: str, text: str) -> None:
        bad = unsupported_numbers(text, proof, ctx.inventory, given)
        if bad:
            found[where] = bad

    look("headline", draft.headline)
    for n, option in enumerate(draft.hook_options, start=1):
        look(f"hook_options[{n}]", f"{option.voiceover} {option.on_screen_text or ''}")
    for n, scene in enumerate(draft.scenes, start=1):
        for field_name, text in nar.scene_texts(scene, nar.CLAIM_FIELDS).items():
            look(f"scene {n} {field_name}", text)
    return found


def number_errors(found: dict[str, list[str]]) -> list[str]:
    return [
        f"{where}: con số «{'», «'.join(bad)}» không có trong proof_bank/hình quay — bỏ hoặc "
        "thay bằng con số có nguồn"
        for where, bad in found.items()
    ]


def strip_draft_numbers(draft: DraftScript, found: dict[str, list[str]]) -> DraftScript:
    """Last resort: remove the numbers nobody can source (the duration fit runs afterwards)."""
    data = draft.model_copy(deep=True)

    def fix(where: str, text: str) -> str:
        return strip_numbers(text, found[where]) if where in found else text

    data.headline = fix("headline", data.headline)
    for n, option in enumerate(data.hook_options, start=1):
        option.voiceover = fix(f"hook_options[{n}]", option.voiceover)
        option.on_screen_text = fix(f"hook_options[{n}]", option.on_screen_text or "") or None
    for n, scene in enumerate(data.scenes, start=1):
        for name in ("voiceover", "on_screen_text"):
            value = getattr(scene, name)
            if value:
                setattr(scene, name, fix(f"scene {n} {name}", value) or None)
        if scene.stat and f"scene {n} stat" in found:
            scene.stat = None  # a callout without its number is meaningless
    return data


def scene_facts(draft: DraftScript, ctx: WriterContext) -> list[SceneFacts]:
    """What each draft scene will show: a recorded clip or not, and where (its visual signature).

    Built from the real visuals the scenes will get, so a hook or CTA that is footage counts as
    footage and a tour of a landing page counts its different sections."""
    scenes = build_scenes(draft, ctx, [])
    return [
        SceneFacts(
            s["type"],
            s.get("feature"),
            s["voiceover"],
            s["visual"]["mode"] == "recording",
            visual_signature(s["visual"]),
        )
        for s in scenes
    ]


def build_scenes(
    draft: DraftScript, ctx: WriterContext, warnings: list[str]
) -> list[dict[str, Any]]:
    """Scene dicts with their visuals; a landing-only product gets a tour of its page sections."""
    used: set[str] = set()
    scenes = [
        scene_dict(s, f"s{i}", ctx, warnings, used) for i, s in enumerate(draft.scenes, start=1)
    ]
    if ctx.lite is not None and is_landing_only(ctx.profile):
        apply_tour(scenes, ctx.lite, warnings)
    return scenes


def soft_issues(draft: DraftScript, ctx: WriterContext) -> list[str]:
    """Quality rules (footage ratio, scene mix): asked to fix twice, then only warned about."""
    issues = structure_issues(scene_facts(draft, ctx), ctx.outline.duration_s)
    if ctx.flow is not None and ctx.proof is not None and not ctx.proof.is_empty:
        said = " ".join(t for s in draft.scenes for t in nar.scene_texts(s).values())
        if not proof_used(said, ctx.proof):
            issues.append(
                "chưa dùng bằng chứng thật (số liệu, ưu đãi hoặc câu trích) từ proof_bank"
            )
    return issues


# --- building -------------------------------------------------------------------------------------


def flow_visual_for(s: DraftScene, ctx: WriterContext) -> dict[str, Any] | None:
    """Flow mode: the scene shows its chapter of the flow (or the opening / closing page)."""
    flow = ctx.flow
    if flow is None:
        return None
    if s.type == "feature_demo":
        return flow.visuals.get(s.feature or "")
    if s.type == "hook":
        return flow.hook_visual or None
    if s.type == "cta":
        return flow.cta_visual or None
    return None


def scene_dict(
    s: DraftScene,
    scene_id: str,
    ctx: WriterContext,
    warnings: list[str],
    used: set[str] | None = None,
) -> dict[str, Any]:
    flow_visual = flow_visual_for(s, ctx)
    feature = ctx.features.get(s.feature) if s.feature else None
    again = bool(used is not None and s.feature in used)  # a repeat continues the earlier scene
    visual = flow_visual or visual_for_scene(
        s.type,
        feature,
        ctx.home_url,
        setup_len=ctx.setup_counts.get(s.feature or ""),
        show_setup=bool(s.show_setup) and not again,
        scene_id=scene_id,
        lite=ctx.lite,
        cta_hint=" ".join(filter(None, [s.on_screen_text, s.voiceover])) if s.type == "cta" else "",
    )
    if used is not None and s.feature:
        used.add(s.feature)
    warnings += [] if flow_visual else visual.warnings
    out: dict[str, Any] = {
        "id": scene_id,
        "type": s.type,
        "layout": s.layout,
        "voiceover": s.voiceover.strip(),
        "on_screen_text": (s.on_screen_text or None) and s.on_screen_text.strip(),
        "key_point": s.key_point.strip() if s.key_point else None,
        "icon": s.icon,
        "visual": visual if flow_visual else visual.visual,
    }
    if s.stat and s.stat.value.strip():
        out["stat"] = {"value": s.stat.value.strip(), "label": s.stat.label.strip()}
    if s.type == "feature_demo":
        out["feature"] = s.feature
        if ctx.flow is not None and s.feature in ctx.flow.visuals:
            out["chapter_id"] = s.feature
    if s.type == "before_after":
        out["before_text"] = (s.before_text or "").strip()
        out["after_text"] = (s.after_text or "").strip()
    return out


def build_script(draft: DraftScript, ctx: WriterContext) -> tuple[Script, list[str]]:
    """Assemble the Script (code-made ids, theme, goal and visuals). Raises WriterError."""
    warnings: list[str] = []
    scenes = build_scenes(draft, ctx, warnings)
    data: dict[str, Any] = {
        "title": draft.title.strip() or ctx.outline.title,
        "goal": ctx.outline.goal,
        "aspect_ratio": "9:16",
        "target_duration_s": ctx.outline.duration_s,
        "template": "desktop_focus",
        "badge": draft.badge,
        "headline": draft.headline.strip(),
        "headline_highlight": draft.headline_highlight or None,
        "theme": ctx.theme.model_dump(),
        "scenes": scenes,
    }
    if ctx.flow is not None:
        data["flow_id"] = ctx.flow.flow_id
    data["framework"] = ctx.framework
    data["hook_options"] = [
        {"kind": o.kind, "voiceover": o.voiceover.strip(), "on_screen_text": o.on_screen_text}
        for o in draft.hook_options
    ]
    if data["hook_options"] and scenes and scenes[0]["type"] == "hook":
        first = data["hook_options"][0]  # the hook scene shows the default (first) option
        scenes[0]["voiceover"] = first["voiceover"]
        scenes[0]["on_screen_text"] = first["on_screen_text"]
    if ctx.capture is not None:
        data["capture"] = {"viewport": "desktop", "width": ctx.capture[0], "height": ctx.capture[1]}
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
    best: tuple[WriterOutput, Script, list[str], list[str], int] | None = None
    numbers_asked = False
    stripped: list[str] = []
    for attempt in range(1, MAX_REPAIRS + 2):
        output = caller.call("script", prompt, WriterOutput)
        found = draft_numbers(output.script, ctx)
        if found and numbers_asked:  # asked once already: the code removes what has no source
            output.script = strip_draft_numbers(output.script, found)
            stripped += [f"auto_stripped: {w} «{'», «'.join(b)}»" for w, b in found.items()]
            found = {}
        errors = check_draft(output.script, ctx) + number_errors(found)
        numbers_asked = numbers_asked or bool(found)
        script: Script | None = None
        warnings: list[str] = []
        if not errors:
            try:
                script, warnings = build_script(output.script, ctx)
            except WriterError as e:
                errors = e.errors
        soft = soft_issues(output.script, ctx) if script is not None else []
        history.append(errors or soft)
        if script is not None and not soft:
            return WriterResult(
                script,
                summary_for(script, output.summary),
                [*output.warnings, *warnings, *stripped],
                attempt,
                history,
            )
        if script is not None and (best is None or len(soft) <= len(best[3])):
            best = (output, script, warnings, soft, attempt)  # valid, but not yet good
        prompt = repair_prompt(base, output, errors or soft)
    if best is not None:  # still not good after the repairs: keep the best one and say so
        out, script, warnings, soft, attempt = best
        return WriterResult(
            script,
            summary_for(script, out.summary),
            [*out.warnings, *warnings, *stripped, *[f"chưa đạt: {s}" for s in soft]],
            attempt,
            history,
        )
    # the repairs are used up: formal limits are fixed by code, only structure can still fail
    assert output is not None
    found = draft_numbers(output.script, ctx)
    if found:
        output.script = strip_draft_numbers(output.script, found)
        stripped += [f"auto_stripped: {w} «{'», «'.join(b)}»" for w, b in found.items()]
    fixed, trims = trim_draft(output.script, ctx)
    errors = check_draft(fixed, ctx, strict_min=False)
    if not errors:
        try:
            script, warnings = build_script(fixed, ctx)
        except WriterError as e:
            errors = e.errors
        else:
            return WriterResult(
                script,
                summary_for(script, output.summary),
                [*output.warnings, *warnings, *trims, *stripped],
                MAX_REPAIRS + 1,
                history,
            )
    raise WriterError(errors)
