"""Flow mode of a job: choose the flow, let the agent run it, review the storyboard, and turn the
approved run into the outline the script step reads. Returns None when the flow route cannot be
used (discovery found nothing, the agent failed outright); the caller then takes the old route,
one feature at a time."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.browser.auth_detect import LoginRequired
from app.browser.session import BrowserSession
from app.core.flow_choice import FlowSelection
from app.core.flow_ctx import FlowCtx, live_inventory
from app.flows.agent import FlowAgent
from app.flows.discovery import PageSummary, summarize_pages
from app.llm.json_call import JsonCaller
from app.llm.router import get_client
from app.pipeline.proposal_run import ProposalRunner
from app.proposal.flow_outline import build_flow_ctx, flow_profile, outline_from_flow
from app.recorder.live import LiveFilm
from app.schemas.generated.core_flow import CoreFlow
from app.schemas.generated.flow_run import FlowRun
from app.schemas.generated.marketing_brief import MarketingBrief
from app.schemas.generated.outline import Outline
from app.schemas.generated.page_insight import PageInsight
from app.schemas.generated.product_profile import ProductProfile

DEFAULT_CAPTURE = (1440, 900)
MAX_SIGN_INS = 2
MAX_FLOW_SWITCHES = 2  # flows given up as impossible here before the old route is taken
INFEASIBLE_KINDS = ("no_data", "no_permission", "feature_missing")
INFEASIBLE_FILE = "flows_infeasible.json"
FALLBACK_FILE = "flow_fallback.json"
NAV_REGIONS = ("nav", "header", "aside")


@dataclass
class FlowJob:
    """What the flow route needs from the job (kept small so it can be faked in tests)."""

    job_dir: Path
    url: str  # the site's start url
    home_url: str  # the app's main page after a sign-in, else the start url
    storage_state: Path | None
    capture: tuple[int, int] | None
    sign_in: Callable[[LoginRequired], Path | None]  # asks the user to sign in again
    film: str = "auto"  # replay: do not film while the agent runs (the steps are replayed later)
    brief: MarketingBrief | None = None  # a marketing brief that came with the job (CLI --brief)


@dataclass
class FlowResult:
    profile: ProductProfile  # the profile as the script writer sees it: one feature per chapter
    outline: Outline
    ctx: FlowCtx
    run: FlowRun


def nav_by_url(pages: list) -> dict[str, list[str]]:  # type: ignore[type-arg]
    """Menu entries seen on each explored page (links in nav / header / sidebar)."""
    out: dict[str, list[str]] = {}
    for page in pages:
        names = [
            e.name for e in page.elements if e.region in NAV_REGIONS and e.role == "link" and e.name
        ]
        out[page.url] = list(dict.fromkeys(names))
    return out


def page_summaries(insights: list[PageInsight], pages: list) -> list[PageSummary]:  # type: ignore[type-arg]
    return summarize_pages(insights, nav_by_url(pages))


def live_film(
    session: BrowserSession, job: FlowJob, start_url: str, capture: tuple[int, int]
) -> LiveFilm | None:
    """The film made while the agent works (None when the job asks for a replay instead)."""
    if job.film == "replay":
        return None
    return LiveFilm(
        session,
        job.job_dir,
        root_url=start_url,
        viewport={"width": capture[0], "height": capture[1]},
    )


def load_infeasible(job_dir: Path) -> dict[str, tuple[CoreFlow, str]]:
    """Flows already found impossible on this account (kept so they are not proposed again)."""
    file = job_dir / INFEASIBLE_FILE
    if not file.is_file():
        return {}
    items = json.loads(file.read_text(encoding="utf-8"))
    return {i["flow"]["id"]: (CoreFlow.model_validate(i["flow"]), i["why"]) for i in items}


def save_infeasible(job_dir: Path, found: dict[str, tuple[CoreFlow, str]]) -> None:
    items = [{"flow": f.model_dump(), "why": why} for f, why in found.values()]
    (job_dir / INFEASIBLE_FILE).write_text(json.dumps(items, ensure_ascii=False, indent=2), "utf-8")


def _write_fallback(job_dir: Path, why: str) -> None:
    (job_dir / FALLBACK_FILE).write_text(json.dumps({"reason": why}, ensure_ascii=False), "utf-8")


def run_core_flow(
    job: FlowJob,
    proposal: ProposalRunner,
    caller: JsonCaller,
    profile: ProductProfile,
    pages: list[PageSummary],
    *,
    say: Callable[[str], None] = lambda _t: None,
    agent_caller: JsonCaller | None = None,
) -> FlowResult | None:
    """The whole flow route. Cancelled, BudgetExceeded and LoginRequired (after retries) pass up."""
    if (job.job_dir / FALLBACK_FILE).is_file():
        return None  # an earlier attempt already fell back; do not ask the same questions again
    infeasible = load_infeasible(job.job_dir)
    agent_llm = agent_caller or get_client("flow_agent", tracker=caller.tracker)
    capture = job.capture or DEFAULT_CAPTURE
    first: list[FlowRun] = []
    for attempt in range(MAX_FLOW_SWITCHES + 1):
        selection = proposal.select_flow(profile, pages, job.url, infeasible or None)
        if selection is None:
            _write_fallback(job.job_dir, "no flow")
            return None
        flow = selection.flows[0]
        for note in selection.warnings:
            proposal.warnings.append(note)
        if len(selection.flows) > 1:
            proposal.warnings.append(
                f"Luồng phụ «{selection.flows[1].title}» chưa được dựng; video chỉ có luồng chính."
            )

        def run_flow(
            notes: str, previous: FlowRun | None, keep: int,
            flow: CoreFlow = flow, selection: FlowSelection = selection,
        ) -> FlowRun:  # fmt: skip
            if first:
                return first.pop()
            for tries in range(MAX_SIGN_INS + 1):
                with BrowserSession(
                    flow.start_url,
                    storage_state=job.storage_state,
                    expect_session=job.storage_state is not None,
                ) as session:
                    agent = FlowAgent(
                        session, agent_llm, flow, job.job_dir,
                        submit_policy=selection.submit_policy, user_notes=notes,
                        authenticated=job.storage_state is not None,
                        viewport={"width": capture[0], "height": capture[1]},
                        previous=previous, keep=keep,
                        film=live_film(session, job, flow.start_url, capture),
                    )  # fmt: skip
                    try:
                        return agent.run()
                    except LoginRequired as e:
                        if tries == MAX_SIGN_INS:
                            raise
                        job.storage_state = job.sign_in(e)
            raise RuntimeError("unreachable")

        say(f"[cyan]\\[flow][/] Agent thực hiện luồng «{flow.title}»...")
        initial = run_flow("", None, 0)
        gave_up = initial.give_up
        if gave_up is None or gave_up.reason_kind not in INFEASIBLE_KINDS:
            break
        # this account cannot do the flow: say why, and ask for another one
        why = gave_up.quote or gave_up.reason
        infeasible[flow.id] = (flow, why)
        save_infeasible(job.job_dir, infeasible)
        (job.job_dir / "selected_flow.json").unlink(missing_ok=True)
        proposal.warnings.append(f"Luồng «{flow.title}» không khả thi trên tài khoản này: {why}")
        if attempt == MAX_FLOW_SWITCHES:
            proposal.warnings.append("Không có luồng nào khả thi; chuyển sang quay từng tính năng.")
            _write_fallback(job.job_dir, "no feasible flow")
            return None
    if initial.status == "failed" or len(initial.steps) < 2:
        proposal.warnings.append(
            "Agent không thực hiện được luồng; chuyển sang quay từng tính năng. "
            + "; ".join(initial.warnings[:2])
        )
        _write_fallback(job.job_dir, "agent failed")
        return None
    first.append(initial)
    approved = proposal.review_storyboard(flow, run_flow)
    proposal.marketing_brief(
        profile, flow, job.brief, approved
    )  # asked once; saved as marketing_brief.json
    ctx = build_flow_ctx(flow, approved, job.home_url, live_inventory(job.job_dir, approved))
    ctx.save(job.job_dir)
    outline = outline_from_flow(flow, approved, ctx)
    (job.job_dir / "outline_approved.json").write_text(
        outline.model_dump_json(indent=2), encoding="utf-8"
    )
    (job.job_dir / "proposal_warnings.json").write_text(
        json.dumps(proposal.warnings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return FlowResult(flow_profile(profile, ctx), outline, ctx, approved)
