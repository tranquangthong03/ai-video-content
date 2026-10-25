"""Flow mode: the approved flow run becomes the outline (hook, one beat per chapter, the call to
action) and the pseudo-features the script writer works with. No concept step: the user already
chose and approved the flow."""

from typing import Any

from app.core.flow_ctx import ChapterCtx, FlowCtx
from app.schemas.generated.core_flow import CoreFlow
from app.schemas.generated.flow_run import FlowRun
from app.schemas.generated.outline import Beat, Outline
from app.schemas.generated.product_profile import Feature, ProductProfile

DURATIONS = (30, 45, 60)
STEP_S = 2.5  # one step on screen, before the hold
HOLD_S = 1.5
HOOK_S, CTA_S = 3.0, 4.0
NO_PICTURE = ("scroll", "wait")


def chapter_steps(run: FlowRun) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {c.id: [] for c in run.chapters}
    for step in run.steps:
        if step.chapter_id in out:
            out[step.chapter_id].append(step)
    return out


def estimate_duration_s(run: FlowRun) -> int:
    """The shortest of 30/45/60 s that fits the chapters (steps x 2.5 s + a hold), hook and CTA."""
    total = HOOK_S + CTA_S
    for steps in chapter_steps(run).values():
        visual = [s for s in steps if s.action.do not in NO_PICTURE]
        total += len(visual) * STEP_S + HOLD_S
    return next((d for d in DURATIONS if total <= d), DURATIONS[-1])


def chapter_visual(steps: list[Any], first: bool, start_url: str) -> dict[str, Any]:
    """A recording of the chapter's own steps. (A flow is filmed in one go; this is what the
    chapter shows, kept in the script so it can be read and checked.)"""
    actions: list[dict[str, Any]] = []
    if not first and steps and steps[0].url_before:
        actions.append({"do": "goto", "url": steps[0].url_before})
    for s in steps:
        action = s.action.model_dump(exclude_none=True)
        if s.locator is not None:
            action["locator"] = s.locator.model_dump(exclude_none=True)
        actions.append(action)
    page = steps[0].url_before if steps and steps[0].url_before else start_url
    return {"mode": "recording", "page": page or start_url, "actions": actions}


def plain_visual(url: str) -> dict[str, Any]:
    return {"mode": "recording", "page": url, "actions": [{"do": "goto", "url": url}]}


def build_flow_ctx(flow: CoreFlow, run: FlowRun, home_url: str) -> FlowCtx:
    steps_by = chapter_steps(run)
    chapters = [
        ChapterCtx(
            id=c.id,
            title=c.title,
            notes=[s.note for s in steps_by[c.id] if s.note and s.action.do not in NO_PICTURE],
            steps=len(steps_by[c.id]),
        )
        for c in run.chapters
    ]
    visuals = {
        c.id: chapter_visual(steps_by[c.id], n == 0, flow.start_url)
        for n, c in enumerate(run.chapters)
    }
    return FlowCtx(
        flow_id=flow.id, title=flow.title, persona=flow.persona, goal=flow.goal,
        success_signal=flow.success_signal, value=flow.value, needs_submit=flow.needs_submit,
        status=run.status, chapters=chapters, visuals=visuals,
        hook_visual=plain_visual(flow.start_url),
        cta_visual=plain_visual(home_url or flow.start_url),
    )  # fmt: skip


def flow_profile(profile: ProductProfile, ctx: FlowCtx) -> ProductProfile:
    """The product as the script writer sees it in flow mode: one feature per chapter."""
    features = [
        Feature(
            id=c.id,
            name=c.title,
            description="; ".join(c.notes[:4]) or ctx.value,
            evidence=[],
            importance=1.0,
            demo_kind="interaction",
            demo_score=1.0,
        )
        for c in ctx.chapters
    ]
    return profile.model_copy(update={"features": features})


def outline_from_flow(flow: CoreFlow, run: FlowRun, ctx: FlowCtx) -> Outline:
    """hook -> one beat per chapter -> cta. The result is the last chapter's beat: a scene without
    a feature could not be filmed, and the same chapter must not appear in two scenes."""
    beats = [Beat(id="b1", text=f"Nỗi đau hoặc kết quả của {flow.persona}: {flow.goal}")]
    for n, c in enumerate(ctx.chapters):
        what = c.notes[0] if c.notes else c.title
        text = f"{c.title}: {what}"
        if n == len(ctx.chapters) - 1:
            text += f" → kết quả: {flow.success_signal}"
        beats.append(Beat(id=f"b{len(beats) + 1}", text=text, feature_id=c.id))
    beats.append(Beat(id=f"b{len(beats) + 1}", text=f"Kêu gọi hành động: {flow.value}"))
    return Outline(
        concept_id=f"flow:{flow.id}",
        title=flow.title,
        goal="tutorial",
        duration_s=estimate_duration_s(run),  # type: ignore[arg-type]
        feature_ids=[c.id for c in ctx.chapters],
        beats=beats,
        version=1,
    )
