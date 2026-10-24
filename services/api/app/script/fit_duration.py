"""Make the estimated speech time match the video length the user chose (30/45/60 s).

estimated_ms is the sum of estimate_speech_ms over all voiceovers. More than 10% under the
target: ask for longer voiceovers in the feature_demo scenes, then add one feature_demo scene
if still short. More than 10% over: ask for shorter voiceovers, least important scenes first.
Never deletes hook/cta.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.core.demo_steps import summarize_steps
from app.core.timing import estimate_speech_ms
from app.llm.json_call import JsonCaller, LLMCallError
from app.llm.prompts import render
from app.schemas.generated.script import Script
from app.script import catalog as cat
from app.script.scene_writer import product_summary, write_scene
from app.script.writer import WriterContext, WriterError

TOLERANCE = 0.10
MAX_SCENES = 6
MIN_FIT_WORDS = 6  # hook and cta may be shortened but not below this
MAX_SHORTEN_ROUNDS = 2
MIN_REAL_ACTIONS = 2  # a 45/60 s feature_demo should show at least this many real operations
REAL_ACTIONS = ("click", "dblclick", "type", "hover", "upload", "right_click")


class VoiceoverItem(BaseModel):
    scene_id: str
    voiceover: str


class FitOutput(BaseModel):
    voiceovers: list[VoiceoverItem]
    notes: str | None = None


@dataclass
class FitReport:
    target_ms: int
    estimated_ms: int  # after fitting
    initial_ms: int
    rounds: int = 0
    actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def deviation(self) -> float:
        return (self.estimated_ms - self.target_ms) / self.target_ms

    @property
    def within(self) -> bool:
        return abs(self.deviation) <= TOLERANCE

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_ms": self.target_ms,
            "estimated_ms": self.estimated_ms,
            "initial_ms": self.initial_ms,
            "deviation": round(self.deviation, 3),
            "within_tolerance": self.within,
            "rounds": self.rounds,
            "actions": self.actions,
            "warnings": self.warnings,
        }


def estimated_ms(script: Script) -> int:
    return sum(estimate_speech_ms(s.root.voiceover) for s in script.scenes)


def total_words(script: Script) -> int:
    return sum(cat.word_count(s.root.voiceover) for s in script.scenes)


def _target_words(script: Script) -> int:
    """Words at which the estimate equals the target (2.5 words/s plus 250 ms per scene)."""
    target = script.target_duration_s * 1000 - 250 * len(script.scenes)
    return max(1, round(target / 400))


def _with_voiceovers(script: Script, changes: dict[str, str]) -> Script:
    data = script.model_dump()
    for scene in data["scenes"]:
        if scene["id"] in changes:
            scene["voiceover"] = changes[scene["id"]]
    return Script.model_validate(data)


def apply_voiceovers(
    script: Script, items: list[VoiceoverItem], *, extend: bool
) -> tuple[Script, list[str]]:
    """Accept only voiceover changes that follow the rules; returns (script, refusal notes)."""
    notes: list[str] = []
    by_id = {s.root.id: s.root for s in script.scenes}
    accepted: dict[str, str] = {}
    for item in items:
        scene = by_id.get(item.scene_id)
        words = cat.word_count(item.voiceover)
        if scene is None:
            notes.append(f"bỏ qua scene không tồn tại: {item.scene_id}")
        elif item.voiceover.strip() == scene.voiceover.strip():
            continue
        elif extend and scene.type != "feature_demo":
            notes.append(f"{item.scene_id}: chỉ được kéo dài scene feature_demo")
        elif words > cat.DEMO_VOICEOVER_MAX_WORDS:
            notes.append(f"{item.scene_id}: {words} từ vượt {cat.DEMO_VOICEOVER_MAX_WORDS}, bỏ qua")
        elif not extend and words < MIN_FIT_WORDS:
            notes.append(f"{item.scene_id}: rút xuống {words} từ là quá ngắn, bỏ qua")
        elif extend and words <= cat.word_count(scene.voiceover):
            notes.append(f"{item.scene_id}: không dài hơn bản cũ, bỏ qua")
        elif not extend and words >= cat.word_count(scene.voiceover):
            notes.append(f"{item.scene_id}: không ngắn hơn bản cũ, bỏ qua")
        else:
            accepted[item.scene_id] = item.voiceover.strip()
    return (_with_voiceovers(script, accepted) if accepted else script), notes


def _ask_fit(caller: JsonCaller, script: Script, ctx: WriterContext, direction: str) -> FitOutput:
    prompt = render(
        "duration_fit",
        direction=direction,
        target_words=_target_words(script),
        current_words=total_words(script),
        script_json=_script_for_prompt(script, ctx),
        product_profile_summary=product_summary(ctx),
    )
    return caller.call("fit", prompt, FitOutput)


def _script_for_prompt(script: Script, ctx: WriterContext) -> str:
    """Scenes without their (long) visuals; demo scenes carry the importance of their feature."""
    scenes = []
    for s in script.scenes:
        d = s.root.model_dump(exclude={"visual", "duration_ms"})
        feature = ctx.features.get(getattr(s.root, "feature", None) or "")
        d["importance"] = feature.importance if feature else None
        scenes.append(d)
    return json.dumps(
        {
            "headline": script.headline,
            "target_duration_s": script.target_duration_s,
            "scenes": scenes,
        },
        ensure_ascii=False,
        indent=1,
    )


def _unused_feature(script: Script, ctx: WriterContext) -> str | None:
    used = {getattr(s.root, "feature", None) for s in script.scenes}
    candidates = [
        f for f in ctx.profile.features if f.demo_kind in cat.DEMOABLE and f.id not in used
    ]
    candidates.sort(key=lambda f: f.importance, reverse=True)
    return candidates[0].id if candidates else None


def _insert_demo(
    caller: JsonCaller, script: Script, ctx: WriterContext, feature_id: str, report: FitReport
) -> Script:
    feature = ctx.features[feature_id]
    cta = script.scenes[-1].root.id
    before_cta = script.scenes[-2].root.id if len(script.scenes) > 1 else None
    result = write_scene(
        caller,
        ctx,
        script,
        task="insert",
        instruction=(
            f"Thêm một đoạn demo cho tính năng «{feature.name}» (feature = {feature_id}). "
            f"Người xem thấy: {summarize_steps(feature) or feature.description}"
        ),
        scene_type="feature_demo",
        after_scene_id=before_cta,
    )
    data = script.model_dump()
    index = next(i for i, s in enumerate(data["scenes"]) if s["id"] == cta)
    data["scenes"].insert(index, result.scene.root.model_dump())
    report.warnings += result.warnings
    return Script.model_validate(data)


def enrich_demos(script: Script, report: FitReport) -> Script:
    """45/60 s: a demo with fewer than two real operations shows its setup when it has one."""
    if script.target_duration_s < 45:
        return script
    data = script.model_dump()
    for scene in data["scenes"]:
        visual = scene["visual"]
        if scene["type"] != "feature_demo" or visual["mode"] != "recording":
            continue
        real = [a for a in visual["actions"] if a["do"] in REAL_ACTIONS]
        if len(real) >= MIN_REAL_ACTIONS:
            continue
        if visual["setup"] and not visual["show_setup"]:
            visual["show_setup"] = True
            report.actions.append(f"{scene['id']}: bật show_setup để có thêm thao tác thật")
        elif (
            len(real) + len([a for a in visual["setup"] if a["do"] in REAL_ACTIONS])
            < MIN_REAL_ACTIONS
        ):
            report.warnings.append(f"{scene['id']}: chỉ có {len(real)} thao tác thật (nên ≥ 2)")
    return Script.model_validate(data)


def fit_duration(
    caller: JsonCaller, script: Script, ctx: WriterContext, *, adjust: bool = True
) -> tuple[Script, FitReport]:
    """Fit the voiceovers to the target. With adjust=False only measures (used after user edits)."""
    target = script.target_duration_s * 1000
    report = FitReport(target, estimated_ms(script), estimated_ms(script))

    def short() -> bool:
        return estimated_ms(script) < target * (1 - TOLERANCE)

    def long() -> bool:
        return estimated_ms(script) > target * (1 + TOLERANCE)

    if adjust and short():
        report.rounds += 1
        try:
            out = _ask_fit(caller, script, ctx, "ngắn hơn")
            script, notes = apply_voiceovers(script, out.voiceovers, extend=True)
            report.warnings += notes
            report.actions.append("kéo dài voiceover các scene feature_demo")
        except LLMCallError as e:
            report.warnings.append(f"không kéo dài được voiceover: {e}")
        if short() and len(script.scenes) < MAX_SCENES:
            feature_id = _unused_feature(script, ctx)
            if feature_id:
                report.rounds += 1
                try:
                    script = _insert_demo(caller, script, ctx, feature_id, report)
                    report.actions.append(f"thêm scene demo «{feature_id}»")
                except (WriterError, LLMCallError) as e:
                    report.warnings.append(f"không thêm được scene demo: {e}")
    elif adjust and long():
        for _ in range(MAX_SHORTEN_ROUNDS):
            if not long():
                break
            report.rounds += 1
            try:
                out = _ask_fit(caller, script, ctx, "dài hơn")
                script, notes = apply_voiceovers(script, out.voiceovers, extend=False)
                report.warnings += notes
                report.actions.append("rút gọn voiceover")
            except LLMCallError as e:
                report.warnings.append(f"không rút gọn được voiceover: {e}")
                break

    if adjust:
        script = enrich_demos(script, report)
    report.estimated_ms = estimated_ms(script)
    if not report.within:
        side = "thiếu" if report.deviation < 0 else "thừa"
        report.warnings.append(
            f"ước tính {report.estimated_ms / 1000:.1f}s so với mục tiêu {target / 1000:.0f}s "
            f"({side} {abs(report.deviation) * 100:.0f}%)"
        )
    return script, report
