"""Copy Critic: a creative director's score of the script, and one round of fixing what is weak.

The model scores five criteria (0-10) with a text-only prompt (role copy_critic). Anything under
the threshold sends the weak scenes back to the Scene Writer once, with the critic's suggestion;
the script is scored again and the better version is kept. Both scores go to the script report.
The critic also tells the two hook options apart: the better-scored one is the default.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from app.llm.json_call import JsonCaller, LLMCallError
from app.llm.prompts import render
from app.schemas.generated.edit_op import EditOp
from app.schemas.generated.script import Script
from app.script.apply import apply_ops
from app.script.scene_writer import write_scene
from app.script.writer import WriterContext, WriterError

CRITERIA = ("hook_strength", "benefit_clarity", "proof_usage", "cta_strength", "flow")
THRESHOLD = 7  # a script that can be posted scores at least this on every criterion
MAX_REWRITES = 3  # scenes sent back to the Scene Writer in one repair round
MAX_ROUNDS = 2  # a second round only while a criterion is still under VERY_WEAK
VERY_WEAK = 6


class Score(BaseModel):
    model_config = ConfigDict(extra="ignore")
    score: int | None = None
    reason: str = ""


class Scores(BaseModel):
    model_config = ConfigDict(extra="ignore")
    hook_strength: Score
    benefit_clarity: Score
    proof_usage: Score = Score()
    cta_strength: Score
    flow: Score


class WeakScene(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scene_id: str
    problem: str = ""
    suggestion: str = ""


class CriticOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scores: Scores
    weak_scenes: list[WeakScene] = []
    issues: list[str] = []
    summary: str = ""


@dataclass
class CriticResult:
    script: Script
    before: dict[str, Any]
    after: dict[str, Any] | None = None
    hook: dict[str, Any] | None = None
    rewritten: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    kept: bool = False  # a rewritten script replaced the first one
    rounds: int = 0  # rewrite rounds that were kept

    def report(self) -> dict[str, Any]:
        final = self.after if self.kept and self.after else self.before
        return {
            "threshold": THRESHOLD,
            "before": self.before,
            "after": self.after,
            "final": final,
            "kept_rewrite": self.kept,
            "rounds": self.rounds,
            "hook": self.hook,
            "rewritten": self.rewritten,
            "notes": self.notes,
            "passed": not below_threshold(final),
        }


def view(out: CriticOutput, proof_empty: bool) -> dict[str, Any]:
    """The report form of one critic answer; proof_usage is null when there was nothing to use."""
    scores = {k: getattr(out.scores, k).model_dump() for k in CRITERIA}
    if proof_empty:
        scores["proof_usage"] = {"score": None, "reason": "Chưa có bằng chứng thật để dùng."}
    return {
        "scores": scores,
        "weak_scenes": [w.model_dump() for w in out.weak_scenes],
        "issues": out.issues,
        "summary": out.summary,
    }


def below_threshold(view_: dict[str, Any]) -> list[str]:
    """Criteria under the threshold (a null score does not count)."""
    return [k for k in CRITERIA if (s := view_["scores"][k]["score"]) is not None and s < THRESHOLD]


def total(view_: dict[str, Any]) -> int:
    return sum(s for k in CRITERIA if (s := view_["scores"][k]["score"]) is not None)


# --- the prompt -----------------------------------------------------------------------------------


def chapters_summary(ctx: WriterContext) -> str:
    flow = ctx.flow
    if flow is None:
        return "; ".join(b.text for b in ctx.outline.beats)
    return "; ".join(f"{c.title}: {c.value_line or '; '.join(c.notes[:2])}" for c in flow.chapters)


def compact_script(script: Script) -> str:
    scenes = []
    for s in (x.root for x in script.scenes):
        item: dict[str, Any] = {"id": s.id, "type": s.type, "voiceover": s.voiceover}
        if s.on_screen_text:
            item["on_screen_text"] = s.on_screen_text
        if s.chapter_id:
            item["chapter"] = s.chapter_id
        if s.stat:
            item["stat"] = s.stat.model_dump()
        scenes.append(item)
    return json.dumps({"headline": script.headline, "scenes": scenes}, ensure_ascii=False)


def prompt_for(ctx: WriterContext, script: Script) -> str:
    flow = ctx.flow
    proof = ctx.proof
    return render(
        "copy_critic",
        persona=flow.persona if flow else ", ".join(ctx.profile.target_users[:2]),
        goal=flow.goal if flow else ctx.outline.title,
        value=flow.value if flow else ctx.profile.one_liner,
        chapters_summary=chapters_summary(ctx),
        proof_bank_json_or_empty=json.dumps(proof.to_dict(), ensure_ascii=False)
        if proof and not proof.is_empty
        else "",
        script_compact_json=compact_script(script),
        brief_text=ctx.brief_text,
    )


def score(caller: JsonCaller, ctx: WriterContext, script: Script) -> dict[str, Any]:
    out = caller.call("copy_critic", prompt_for(ctx, script), CriticOutput)
    return view(out, proof_empty=ctx.proof is None or ctx.proof.is_empty)


# --- hook choice and one repair round ------------------------------------------------------------


def with_hook(script: Script, ctx: WriterContext, option: int) -> Script:
    """The script showing hook option `option` (0-based) on its hook scene, no model involved."""
    hook = script.scenes[0].root
    op = EditOp.model_validate(
        {"op": "set", "scene_id": hook.id, "field": "hook_option", "value": str(option + 1)}
    )
    result = apply_ops(script, [op], ctx)
    return result.script if not result.errors else script


def choose_hook(
    caller: JsonCaller, ctx: WriterContext, script: Script
) -> tuple[Script, dict[str, Any], dict[str, Any] | None]:
    """(script with the better hook, its score view, the hook comparison for the report)."""
    options = script.hook_options
    if len(options) < 2 or script.scenes[0].root.type != "hook":
        return script, score(caller, ctx, script), None
    variants = [with_hook(script, ctx, i) for i in range(2)]
    views = [score(caller, ctx, v) for v in variants]
    hook_scores = [v["scores"]["hook_strength"]["score"] or 0 for v in views]
    # higher hook score wins; on a tie the higher total, then the first
    best = max(range(2), key=lambda i: (hook_scores[i], total(views[i]), -i))
    compare = {"hook_strength": hook_scores, "chosen": best + 1,
               "kinds": [o.kind for o in options]}  # fmt: skip
    return variants[best], views[best], compare


def replace_scene(script: Script, scene: Any) -> Script:
    data = script.model_dump()
    new = scene.model_dump()
    data["scenes"] = [new if s["id"] == new["id"] else s for s in data["scenes"]]
    if new["type"] == "hook" and data.get("hook_options"):  # the chosen option follows its scene
        for option in data["hook_options"]:
            if option["voiceover"] == script.scenes[0].root.voiceover:
                option["voiceover"] = new["voiceover"]
                option["on_screen_text"] = new.get("on_screen_text")
                break
    return Script.model_validate(data)


def rewrite_weak(
    caller: JsonCaller, ctx: WriterContext, script: Script, weak: list[WeakScene | dict[str, Any]]
) -> tuple[Script, list[str], list[str]]:
    """Send the critic's weak scenes back to the Scene Writer (each once). A scene that cannot be
    rewritten validly is left as it was and the reason goes to the notes."""
    ids = {s.root.id for s in script.scenes}
    done: list[str] = []
    notes: list[str] = []
    for item in weak:
        w = item if isinstance(item, WeakScene) else WeakScene.model_validate(item)
        if w.scene_id not in ids or w.scene_id in done or not w.suggestion.strip():
            continue
        if len(done) >= MAX_REWRITES:
            break
        try:
            written = write_scene(
                caller, ctx, script, task="rewrite", instruction=f"{w.problem} → {w.suggestion}",
                fields=["voiceover", "on_screen_text"], scene_id=w.scene_id,
            )  # fmt: skip
            script = replace_scene(script, written.scene.root)
            done.append(w.scene_id)
        except (WriterError, LLMCallError, ValidationError) as e:
            notes.append(f"scene {w.scene_id}: không viết lại được ({str(e)[:80]})")
    return script, done, notes


def improve(
    caller: JsonCaller,
    ctx: WriterContext,
    script: Script,
    writer: JsonCaller | None = None,
) -> CriticResult:
    """Pick the better hook, score, and fix what is under the threshold: one round of rewrites, a
    second only while a criterion is still under VERY_WEAK. `caller` scores (role copy_critic),
    `writer` (default: the same) rewrites the weak scenes. A rewrite is kept only if it scores no
    lower than what it replaces."""
    writer = writer or caller
    script, view_now, hook = choose_hook(caller, ctx, script)
    result = CriticResult(script, view_now, hook=hook)
    for round_no in range(1, MAX_ROUNDS + 1):
        under = below_threshold(view_now)
        if not under or not view_now["weak_scenes"]:
            break
        if round_no > 1 and not any(
            (view_now["scores"][k]["score"] or 10) < VERY_WEAK for k in CRITERIA
        ):
            break
        rewritten, done, notes = rewrite_weak(writer, ctx, script, view_now["weak_scenes"])
        result.notes += notes
        if not done:
            break
        after = score(caller, ctx, rewritten)
        result.after = after
        if total(after) < total(view_now):
            result.notes.append("bản viết lại bị chấm thấp hơn nên giữ bản trước")
            break
        script, view_now = rewritten, after
        result.script, result.kept = script, True
        result.rewritten = [*result.rewritten, *done]
        result.rounds += 1
    return result
