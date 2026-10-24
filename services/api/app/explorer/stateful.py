"""Stateful discovery: some features only exist after data does (a filter bar needs a todo).

After a feature was verified as an `interaction` that created data, we replay its steps once,
re-extract the page, and treat only the NEW elements as a delta: the Page Analyzer sees just the
delta, the Product Synthesizer gets it with the setup steps, and every feature found this way has
`requires_setup = True` and demo_steps = setup steps + its own steps.

Limits: one re-extract per page, at most MAX_PAGES pages per run. The request guard and the
blacklist apply to every replayed step exactly as in verification.
"""

import re
from collections.abc import Callable
from pathlib import Path

from app.browser.enter_policy import Policy
from app.browser.page_utils import dismiss_cookie_banner, wait_for_settle
from app.browser.session import BrowserSession
from app.browser.urls import normalize_url
from app.explorer.analyze import analyze_page, format_elements
from app.explorer.extract import extract_page, settle
from app.explorer.models import Element, PageData
from app.explorer.report import Deadline, Report
from app.explorer.synthesize import synthesize_delta
from app.explorer.verify import Context, perform_step, verify_features
from app.llm.json_call import JsonCaller, LLMCallError
from app.schemas.generated.page_insight import PageInsight
from app.schemas.generated.product_profile import DemoStep, Feature, ProductProfile

MAX_PAGES = 3
MAX_FEATURES_TOTAL = 12  # ProductProfile.features maxItems


def _head(element: Element) -> tuple[str, str]:
    """Identity of an element across states: tag + visible text (positions move, ids change)."""
    return element.tag, re.sub(r"\s+", " ", (element.text or element.name).lower()).strip()


def delta_elements(old: PageData, new: PageData, prefix: str) -> list[Element]:
    """Elements of `new` that `old` did not have, renumbered `<prefix>e1..` so refs stay unique."""
    seen = {_head(e) for e in old.elements}
    fresh: list[Element] = []
    for element in new.elements:
        head = _head(element)
        if head in seen:
            continue
        seen.add(head)
        copy = element.model_copy(deep=True)
        copy.ref = f"{prefix}e{len(fresh) + 1}"
        fresh.append(copy)
    return fresh


def interaction_setups(
    profile: ProductProfile, pages: list[PageData]
) -> list[tuple[PageData, Feature]]:
    """At most MAX_PAGES (page, feature) pairs: per page the most important interaction that
    created data (new list items / new elements / a big visual change)."""
    lookup = {u: p for p in pages if (u := normalize_url(p.url))}
    chosen: dict[str, tuple[PageData, Feature]] = {}
    for feature in sorted(profile.features, key=lambda f: -f.importance):
        evidence = feature.demo_evidence
        if feature.demo_kind != "interaction" or not feature.demo_steps or feature.requires_setup:
            continue
        if evidence is None or not (
            evidence.new_list_items > 0 or evidence.dom_delta >= 2 or evidence.visual_diff >= 0.05
        ):
            continue
        url = next((s.url for s in feature.demo_steps if s.ref and s.url), None) or next(
            (e.url for e in feature.evidence if e.source == "app_action"), None
        )
        key = normalize_url(url or "") or ""
        page = lookup.get(key)
        if page is not None and key not in chosen:
            chosen[key] = (page, feature)
        if len(chosen) >= MAX_PAGES:
            break
    return list(chosen.values())


def capture_state(
    session: BrowserSession,
    page: PageData,
    feature: Feature,
    ctx: Context,
    out_dir: Path,
    deadline: Deadline,
) -> PageData | None:
    """Replay the feature's steps in a clean context and re-extract the page (once)."""
    context = session.new_context()
    try:
        browser_page = context.new_page()
        browser_page.goto(page.url, wait_until="domcontentloaded")
        settle(browser_page)
        dismiss_cookie_banner(browser_page)
        for step in feature.demo_steps:
            if deadline.expired():
                return None
            perform_step(browser_page, step, ctx)
        wait_for_settle(browser_page)
        return extract_page(browser_page, page.n, out_dir, depth=page.depth, write_files=False)
    except Exception:
        return None
    finally:
        context.close()


PREP_ROLES = ("checkbox", "switch", "option", "textbox", "searchbox")


def prep_len(own: list[DemoStep], page: PageData) -> int:
    """Leading steps of a filter/tab-style feature that only prepare data (typing, ticking a box).

    They make the result differ, so their own effect is not evidence of the feature: the evidence is
    what the first real trigger (a link, tab or button) changes afterwards.
    """
    n = 0
    for step in own:
        element = page.element(step.ref or "") if step.ref else None
        if step.do == "type" or (
            step.do == "click" and element is not None and element.role in PREP_ROLES
        ):
            n += 1
        else:
            break
    return n


def is_replaceable(feature: Feature) -> bool:
    """A feature that could not be demonstrated (failed, or its steps were removed as invalid).

    The delta step may propose it again with steps that work; it must not count as already known.
    """
    return feature.demo_kind == "failed" or (
        feature.demo_kind is None and feature.verified and not feature.demo_steps
    )


def run_stateful(
    session: BrowserSession,
    profile: ProductProfile,
    pages: list[PageData],
    insights: list[PageInsight],
    *,
    root_url: str,
    site_type: str,
    caller: JsonCaller,
    out_dir: Path,
    report: Report,
    deadline: Deadline,
    enter_policy: Policy = "strict",
    scope_prefix: str | None = None,
    progress: Callable[[str, str], None] | None = None,
) -> list[Feature]:
    """Find, add and verify data-dependent features. Returns the features that were added."""
    say = progress or (lambda step, msg: None)
    added: list[Feature] = []
    setup_counts: dict[str, int] = {}
    log = report.data.setdefault("stateful", [])
    for k, (page, setup) in enumerate(interaction_setups(profile, pages), start=1):
        if deadline.expired() or len(profile.features) + len(added) >= MAX_FEATURES_TOTAL:
            break
        say("stateful", f"Mở lại trạng thái sau «{setup.name}» ({page.url})")
        lookup = {u: p for p in pages if (u := normalize_url(p.url))}
        ctx = Context(
            lookup, root_url, scope_prefix, report, setup.id, enter_policy,
            guard_on=not session.guard.allow_mutations,
        )  # fmt: skip
        state = capture_state(session, page, setup, ctx, out_dir, deadline)
        entry = {
            "page": page.url,
            "setup_feature": setup.id,
            "delta_elements": 0,
            "new_features": [],
        }
        log.append(entry)
        if state is None:
            report.warn(f"stateful: could not recreate the state after {setup.id!r}")
            continue
        delta = delta_elements(page, state, f"s{k}")
        entry["delta_elements"] = len(delta)
        if not delta:
            continue
        setup_steps = [s.model_copy(deep=True) for s in setup.demo_steps]
        page.elements += delta  # so refs sNeM resolve like any other element of the page
        page.setup_steps = setup_steps
        delta_page = PageData(
            n=page.n,
            url=page.url,
            title=f"{page.title} (sau khi đã thao tác: {setup.name})",
            key_texts=[t for t in state.key_texts if t not in page.key_texts],
            elements=delta,
            signals=state.signals,
        )
        try:
            delta_insight = analyze_page(caller, delta_page, step="delta")
            fresh = synthesize_delta(
                caller, root_url, site_type, pages, page, delta_insight,
                format_elements(delta_page), setup_steps,
                [f.name for f in [*profile.features, *added] if not is_replaceable(f)],
            )  # fmt: skip
        except LLMCallError as e:
            report.warn(f"stateful: delta analysis failed for {page.url}: {e}")
            continue
        used = {f.id for f in [*profile.features, *added]}
        for feature in fresh[: MAX_FEATURES_TOTAL - len(profile.features) - len(added)]:
            while feature.id in used:
                feature.id += "-s"
            used.add(feature.id)
            setup_counts[feature.id] = len(setup_steps) + prep_len(
                feature.demo_steps[len(setup_steps) :], page
            )
            added.append(feature)
            entry["new_features"].append(feature.id)

    if added:
        only_new = profile.model_copy(update={"features": added})  # shares the Feature objects
        verify_features(
            session, only_new, pages, root_url, out_dir, report, deadline,
            insights=insights, limit=len(added), enter_policy=enter_policy,
            scope_prefix=scope_prefix, setup_counts=setup_counts,
        )  # fmt: skip
        # a failed feature is replaced by the new one that covers the same claim
        names = {f.name.strip().lower() for f in added if f.demo_kind not in (None, "failed")}
        profile.features[:] = [
            f
            for f in profile.features
            if not (is_replaceable(f) and f.name.strip().lower() in names)
        ]
        profile.features.extend(added)
    return added
