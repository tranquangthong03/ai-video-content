"""Product Synthesizer: pages + insights (+ screenshots) -> ProductProfile, sanitised."""

import json
from pathlib import Path

from app.browser.auth_detect import is_logout_url
from app.browser.blacklist import is_blocked, is_blocked_href
from app.browser.urls import normalize_url, same_site
from app.core.samples import CATALOG, catalog_text, pick_sample
from app.core.subpages import is_sensitive, is_subpage, is_subpage_text
from app.explorer.extract import describe_layout
from app.explorer.models import Element, PageData
from app.explorer.report import Report
from app.llm.json_call import JsonCaller
from app.llm.prompts import render
from app.schemas.generated.page_insight import PageInsight
from app.schemas.generated.product_profile import DemoStep, Feature, ProductProfile

MAX_FEATURES = 8
MAX_STEPS = 5
REF_STEPS = {"click", "type", "hover", "upload", "dblclick", "right_click"}
CLICK_LIKE = {"click", "dblclick", "right_click"}
TEXT_ROLES = {"textbox", "searchbox", "combobox"}
TYPE_WEIGHT = {"landing_hero": 3.0, "landing_features": 3.0, "pricing": 1.5}


def select_key_pages(
    pages: list[PageData], insights: list[PageInsight], limit: int = 5
) -> list[PageData]:
    """3-5 most informative pages: landing hero/features and app pages with many actions."""
    by_url = {i.url: i for i in insights}

    def is_app(p: PageData) -> bool:
        i = by_url.get(p.url)
        return bool(i and i.page_type.startswith("app_"))

    def score(p: PageData) -> float:
        i = by_url.get(p.url)
        if not i:
            return 0.0
        weight = TYPE_WEIGHT.get(i.page_type, 2.5 if i.page_type.startswith("app_") else 0.5)
        return (
            weight + i.visual_quality + min(1.0, 0.05 * len(i.actions)) + (1.0 if p.n == 1 else 0.0)
        )

    ranked = sorted(pages, key=score, reverse=True)
    picked = ranked[:limit]
    apps = [p for p in ranked if is_app(p)]
    if apps and not any(is_app(p) for p in picked):
        picked = picked[:-1] + [apps[0]]  # make sure the in-app view is represented
    return sorted(picked, key=lambda p: p.n)


def build_prompt(
    root_url: str,
    site_type: str,
    pages: list[PageData],
    insights: list[PageInsight],
    key_pages: list[PageData],
    *,
    with_layout_text: bool,
    delta_json: str = "",
    known_features: str = "",
    known_intents: str = "",
) -> str:
    first = pages[0]
    slim = [
        i.model_dump(
            include={"url", "title", "page_type", "purpose", "actions", "claimed_features"}
        )
        for i in insights
    ]
    prompt = render(
        "product_synthesizer",
        root_url=root_url,
        site_type=site_type,
        title=first.title,
        meta_description=first.meta_description,
        og_description=first.og_description,
        page_insights_json=json.dumps(slim, ensure_ascii=False, indent=1),
        sample_files=catalog_text(),
        delta_json=delta_json,
        known_features=known_features,
        known_intents=known_intents,
    )
    if (
        with_layout_text
    ):  # no vision model: describe the layout from the DOM instead of attaching images
        lines = "\n".join(f"- {p.url}: {describe_layout(p.layout)}" for p in key_pages)
        prompt += f"\n<layout_descriptions>\n{lines}\n</layout_descriptions>\n"
    return prompt


def _page_lookup(pages: list[PageData]) -> dict[str, PageData]:
    return {u: p for p in pages if (u := normalize_url(p.url))}


def sanitize_profile(
    profile: ProductProfile,
    pages: list[PageData],
    root_url: str,
    typed: set[str] | None = None,
    *,
    authenticated: bool = False,
) -> tuple[ProductProfile, list[str]]:
    """Drop what the data does not support: unknown refs/pages and unsafe or invalid demo steps.

    Returns the cleaned profile and human-readable notes about everything removed.
    """
    notes: list[str] = []
    lookup = _page_lookup(pages)
    kept: list[Feature] = []
    used_ids: set[str] = set()

    for feature in sorted(profile.features, key=lambda f: -f.importance):
        fid = feature.id or feature.name.lower().replace(" ", "-")
        while fid in used_ids:
            fid += "-2"
        used_ids.add(fid)
        feature.id = fid

        if is_subpage_text(feature.name) or is_subpage_text(
            fid.replace("_", " ").replace("-", " ")
        ):
            notes.append(
                f"{fid}: feature dropped, it is about a side page (sign in / register / pay)"
            )
            continue
        evidence = []
        for ev in feature.evidence:
            page = lookup.get(normalize_url(ev.url) or "")
            if page is None:
                notes.append(f"{fid}: evidence dropped, unknown page {ev.url}")
                continue
            if is_subpage(page.url, getattr(page, "title", None)):
                notes.append(f"{fid}: evidence dropped, {ev.url} is a side page")
                continue
            if ev.ref and page.element(ev.ref) is None:
                notes.append(f"{fid}: evidence ref {ev.ref} not on {ev.url}, ref removed")
                ev.ref = None
            ev.url = page.url
            evidence.append(ev)
        if not evidence:
            notes.append(f"{fid}: feature dropped, no valid evidence")
            continue
        feature.evidence = evidence

        feature.demo_steps = _clean_steps(
            feature, lookup, root_url, notes, set(typed or ()), authenticated
        )
        kept.append(feature)

    profile.features = kept[:MAX_FEATURES]
    return profile, notes


def _clean_steps(
    feature: Feature,
    lookup: dict[str, PageData],
    root_url: str,
    notes: list[str],
    typed: set[str],
    authenticated: bool = False,
) -> list[DemoStep]:
    current = next(
        (e.url for e in feature.evidence if e.source == "app_action"), feature.evidence[0].url
    )
    clean: list[DemoStep] = []
    for i, step in enumerate(feature.demo_steps[:MAX_STEPS]):
        problem = _step_problem(step, current, lookup, root_url, typed, authenticated)
        if step.do == "type" and step.text:
            typed = typed | {step.text.strip().lower()}
        if problem:
            notes.append(f"{feature.id}: demo_steps truncated at step {i + 1}: {problem}")
            if step.do == "dblclick":  # the steps before it show some other feature, not the edit
                notes.append(f"{feature.id}: demo_steps cleared (the edit step was invalid)")
                return []
            break
        if step.do == "goto":
            current = normalize_url(step.url or "", root_url) or current
        if step.do in REF_STEPS:
            page = lookup[normalize_url(step.url or current) or ""]
            element = page.element(step.ref or "")
            assert element is not None  # _step_problem checked it
            step.url = page.url
            step.locator = element.spec()  # the recorder resolves this first
            if step.do == "upload" and step.file not in CATALOG:
                step.file = pick_sample(element.accept, f"{feature.name} {element.name}")
        clean.append(step)
    return clean


def _step_problem(
    step: DemoStep,
    current: str,
    lookup: dict[str, PageData],
    root_url: str,
    typed: set[str] = frozenset(),  # type: ignore[assignment]
    authenticated: bool = False,
) -> str | None:
    if step.do == "goto":
        target = normalize_url(step.url or "", root_url)
        if not target or not same_site(target, root_url):
            return "goto without a same-site url"
        if is_logout_url(target):
            return "goto to a sign-out page"
        if authenticated and is_sensitive(target):
            return "goto to a settings/account/billing page"
        return None
    if step.do not in REF_STEPS:
        return None
    page = lookup.get(normalize_url(step.url or current) or "")
    if page is None:
        return f"unknown page {step.url or current}"
    element = page.element(step.ref or "")
    if element is None:
        return f"ref {step.ref} does not exist"
    # the blacklist applies to the element being operated on, not to sample text typed into it
    if is_blocked(element.name, element.text, element.selector, strict=True, ignore=typed):
        return f"blacklisted element/text ({element.name!r})"
    if step.do == "upload" and "upload" not in element.caps:
        return f"{element.name!r} is not an upload field"
    if is_blocked_href(element.href):
        return f"blocked link target {element.href}"
    if step.do in CLICK_LIKE and is_submit(element):
        return f"{element.name!r} would submit a form"
    if step.do == "dblclick" and not is_dblclick_target(element):
        return f"{element.name!r} is not an item that can be edited by double-click"
    if step.do == "type":
        if element.role not in TEXT_ROLES or element.input_type == "password" or not step.text:
            return f"cannot type into {element.name!r}"
    return None


DBLCLICK_NEVER_TAGS = ("input", "textarea", "button", "select")
DBLCLICK_NEVER_ROLES = ("textbox", "searchbox", "button", "combobox", "checkbox", "file")
DBLCLICK_ITEM_TAGS = ("li", "tr", "td")
DBLCLICK_ITEM_ROLES = ("listitem", "row", "cell", "gridcell")


def is_dblclick_target(element: Element) -> bool:
    """Double-click edits an item (list entry, row, text marked for it), never a control."""
    if element.tag in DBLCLICK_NEVER_TAGS or element.role in DBLCLICK_NEVER_ROLES:
        return False
    return (
        "dblclick" in element.caps
        or element.tag in DBLCLICK_ITEM_TAGS
        or element.role in DBLCLICK_ITEM_ROLES
    )


def drop_redundant_goto(own: list[DemoStep], current_url: str) -> list[DemoStep]:
    """A feature's own steps must not start by reloading the page the setup left us on.

    The fragment counts: a goto to another hash route is a real step and is kept.
    """
    if own and own[0].do == "goto":
        a = normalize_url(own[0].url or "", keep_anchor=True)
        if a and a == normalize_url(current_url, keep_anchor=True):
            return own[1:]
    return own


def is_submit(element: Element) -> bool:
    """True for controls that submit a form (clicking them could write data)."""
    if element.input_type in ("submit", "image"):
        return True
    return element.tag == "button" and element.in_form and element.button_type == "submit"


def describe_steps(steps: list[DemoStep], page: PageData) -> list[dict[str, str | None]]:
    """Human-readable steps (which element, what text/file) for prompts about a stateful page."""
    out: list[dict[str, str | None]] = []
    for s in steps:
        element = page.element(s.ref or "")
        out.append(
            {"do": s.do, "url": s.url, "element": element.name if element else None,
             "text": s.text, "file": s.file}
        )  # fmt: skip
    return out


def synthesize_delta(
    caller: JsonCaller,
    root_url: str,
    site_type: str,
    pages: list[PageData],
    page: PageData,
    delta_insight: PageInsight,
    new_elements_text: str,
    setup_steps: list[DemoStep],
    known_names: list[str],
) -> list[Feature]:
    """Features that only exist after `setup_steps` ran. Their demo_steps start with those steps."""
    delta_json = json.dumps(
        {
            "url": page.url,
            "setup_steps": describe_steps(setup_steps, page),
            "new_elements": new_elements_text,
        },
        ensure_ascii=False,
        indent=1,
    )
    prompt = build_prompt(
        root_url,
        site_type,
        pages,  # pages[0] supplies the site title/description; `page` is among them
        [delta_insight],
        [],
        with_layout_text=False,
        delta_json=delta_json,
        known_features="; ".join(known_names) or "(chưa có)",
    )
    profile = caller.call("delta", prompt, ProductProfile)
    typed = {s.text.strip().lower() for s in setup_steps if s.do == "type" and s.text}
    profile, _ = sanitize_profile(profile, pages, root_url, typed)  # `page` holds the delta
    known = {n.strip().lower() for n in known_names}
    fresh = [f for f in profile.features if f.name.strip().lower() not in known]
    for feature in fresh:
        feature.requires_setup = True
        own = drop_redundant_goto(feature.demo_steps, page.url)
        feature.demo_steps = [s.model_copy(deep=True) for s in setup_steps] + own
    return fresh


def synthesize(
    caller: JsonCaller,
    root_url: str,
    site_type: str,
    pages: list[PageData],
    insights: list[PageInsight],
    report: Report,
    *,
    existing: ProductProfile | None = None,
    authenticated: bool = False,
) -> ProductProfile:
    """Product profile from page insights. With `existing`, `pages`/`insights` hold only the NEW
    part: the model is told which features (and intent keys) exist and should reuse the keys."""
    key_pages = select_key_pages(pages, insights)
    images = [
        Path(p.screenshot) for p in key_pages if p.screenshot and Path(p.screenshot).is_file()
    ]
    use_images = caller.can_see_images and bool(images)
    if not caller.can_see_images:
        report.warn(
            "no vision model configured: layout described from the DOM instead of screenshots"
        )
    known = (
        "; ".join(f"{f.name} [{f.intent_key or '-'}]" for f in existing.features)
        if existing
        else ""
    )
    prompt = build_prompt(
        root_url,
        site_type,
        pages,
        insights,
        key_pages,
        with_layout_text=not use_images,
        known_intents=known,
    )
    profile = caller.call("synthesize", prompt, ProductProfile, images=images if use_images else ())
    profile, notes = sanitize_profile(profile, pages, root_url, authenticated=authenticated)
    report.data["synthesis_dropped"] = notes
    return profile
