"""Demo verification: replay each important feature's demo_steps in a clean context, safely.

Safety rules (enforced here, in addition to the request guard):
- never click an element whose text/aria/title matches the blacklist or a submit/save intent;
- never click a control that submits a form, never press Enter;
- only navigate within the same site.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops
from playwright.sync_api import Page

from app.core.safety import is_blocked, is_blocked_href
from app.explorer.browser import BrowserSession, dismiss_cookie_banner
from app.explorer.extract import settle
from app.explorer.mapper import _locate, normalize_url, same_site
from app.explorer.models import PageData
from app.explorer.report import Deadline, Report
from app.explorer.synthesize import is_submit
from app.schemas.generated.product_profile import DemoStep, Feature, ProductProfile

MAX_FEATURES = 6
IMAGE_DIFF_THRESHOLD = 0.01  # fraction of pixels that changed noticeably

SIGNATURE_JS = """
() => ({
  url: location.href,
  title: document.title,
  dialogs: document.querySelectorAll('[role=dialog],dialog[open],[aria-modal=true]').length,
  visible: [...document.querySelectorAll('a,button,input,select,textarea,[role=button]')]
    .filter((e) => {
      const r = e.getBoundingClientRect();
      return r.width > 1 && r.height > 1;
    }).length,
})
"""


class UnsafeStep(RuntimeError):
    """The step would click something the safety rules forbid; the run stops here."""


@dataclass
class FeatureRun:
    reached: bool = False
    steps_total: int = 0
    steps_done: int = 0
    any_change: bool = False
    note: str = ""
    thumbnail: str | None = None


def compute_demo_score(run: FeatureRun) -> float:
    """1.0: all steps ran with a visible change; 0.5: page reached only; 0: nothing worked."""
    if not run.reached:
        return 0.0
    if run.steps_total and run.steps_done == run.steps_total and run.any_change:
        return 1.0
    return 0.5


def images_differ(before: Path, after: Path) -> bool:
    a = Image.open(before).convert("L").resize((480, 270))
    b = Image.open(after).convert("L").resize((480, 270))
    diff = ImageChops.difference(a, b).point(lambda v: 255 if v > 30 else 0)
    changed = diff.histogram()[255]  # pixels that differ noticeably (mapped to 255 above)
    return changed / (480 * 270) >= IMAGE_DIFF_THRESHOLD


def signature_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return (
        normalize_url(before["url"]) != normalize_url(after["url"])
        or before["dialogs"] != after["dialogs"]
        or abs(before["visible"] - after["visible"]) >= 1
    )


def _shot(page: Page, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(path))
    return path


def _check_clickable(element: Any, root_url: str) -> None:
    if is_blocked(element.name, element.selector, element.locator_name, strict=True):
        raise UnsafeStep(f"blacklisted element {element.name!r}")
    if is_blocked_href(element.href):
        raise UnsafeStep(f"blocked link {element.href}")
    if is_submit(element):
        raise UnsafeStep(f"{element.name!r} submits a form")
    if (
        element.href
        and normalize_url(element.href, root_url)
        and not same_site(element.href, root_url)
    ):
        raise UnsafeStep(f"{element.name!r} leaves the site")


def perform_step(
    page: Page,
    step: DemoStep,
    lookup: dict[str, PageData],
    root_url: str,
    report: Report,
    feature_id: str,
) -> None:
    """Run one step. Raises UnsafeStep (nothing was clicked) or a Playwright error (step failed)."""
    if step.do == "goto":
        target = normalize_url(step.url or "", root_url)
        if not target or not same_site(target, root_url):
            raise UnsafeStep(f"goto outside the site: {step.url}")
        page.goto(target, wait_until="domcontentloaded")
        settle(page)
        return
    if step.do == "wait":
        page.wait_for_timeout(800)
        return
    if step.do == "scroll" and not step.ref:
        page.mouse.wheel(0, 700)
        page.wait_for_timeout(300)
        return

    step_url = normalize_url(step.url or page.url) or page.url
    source = lookup.get(step_url)
    element = source.element(step.ref or "") if source else None
    if element is None:
        raise RuntimeError(f"ref {step.ref} unknown on {step_url}")
    if normalize_url(page.url) != step_url:  # the ref belongs to another page: go there first
        page.goto(step_url, wait_until="domcontentloaded")
        settle(page)

    if step.do in ("click", "type"):
        try:
            _check_clickable(element, root_url) if step.do == "click" else _check_typeable(
                element, step
            )
        except UnsafeStep:
            report.data["clicks_blocked"].append(
                {"phase": "verify", "feature": feature_id, "ref": step.ref, "name": element.name}
            )
            raise
    target = _locate(page, element)
    if target is None:
        raise RuntimeError(f"cannot locate {element.name!r}")
    if step.do == "click":
        report.data["clicks"].append(
            {
                "phase": "verify",
                "feature": feature_id,
                "ref": step.ref,
                "name": element.name,
                "selector": element.selector,
            }
        )
        target.click(timeout=4000)
    elif step.do == "type":
        target.fill(step.text or "", timeout=4000)  # fill only: Enter is never pressed
    elif step.do == "hover":
        target.hover(timeout=4000)
    elif step.do == "scroll":
        target.scroll_into_view_if_needed(timeout=4000)
    page.wait_for_timeout(500)


def _check_typeable(element: Any, step: DemoStep) -> None:
    if is_blocked(element.name, element.selector, element.locator_name, strict=True):
        raise UnsafeStep(f"blacklisted field {element.name!r}")
    if element.input_type == "password":
        raise UnsafeStep("never type into password fields")


def run_feature(
    session: BrowserSession,
    feature: Feature,
    lookup: dict[str, PageData],
    root_url: str,
    out_dir: Path,
    report: Report,
    deadline: Deadline,
) -> FeatureRun:
    run = FeatureRun(steps_total=len(feature.demo_steps))
    shots = out_dir / "verify" / re.sub(r"[^\w-]", "_", feature.id)
    context = session.new_context()
    try:
        page = context.new_page()
        start = next((s.url for s in feature.demo_steps if s.do == "goto" and s.url), None) or next(
            (e.url for e in feature.evidence), root_url
        )
        try:
            response = page.goto(start, wait_until="domcontentloaded")
            settle(page)
            run.reached = response is None or response.status < 400
        except Exception as e:
            run.note = f"cannot open {start}: {type(e).__name__}"
            return run
        dismiss_cookie_banner(page)

        for k, step in enumerate(feature.demo_steps):
            if deadline.expired():
                run.note = "time budget exhausted"
                break
            before_sig = page.evaluate(SIGNATURE_JS)
            before_img = _shot(page, shots / f"step{k + 1}_before.png")
            try:
                perform_step(page, step, lookup, root_url, report, feature.id)
            except UnsafeStep as e:
                run.note = f"stopped: {e}"
                break
            except Exception as e:
                run.note = f"step {k + 1} ({step.do}) failed: {type(e).__name__}"
                break
            run.steps_done += 1
            after_img = _shot(page, shots / f"step{k + 1}_after.png")
            run.thumbnail = str(after_img)
            if step.do != "goto" and (
                signature_changed(before_sig, page.evaluate(SIGNATURE_JS))
                or images_differ(before_img, after_img)
            ):
                run.any_change = True
        if not run.thumbnail:
            run.thumbnail = str(_shot(page, shots / "page.png"))
    finally:
        context.close()
    return run


def verify_features(
    session: BrowserSession,
    profile: ProductProfile,
    pages: list[PageData],
    root_url: str,
    out_dir: Path,
    report: Report,
    deadline: Deadline,
    *,
    limit: int = MAX_FEATURES,
    on_feature: Any = None,
) -> None:
    """Fill demo_score/thumbnail/verified for the `limit` most important features (in place)."""
    lookup = {u: p for p in pages if (u := normalize_url(p.url))}
    ranked = sorted(profile.features, key=lambda f: -f.importance)[:limit]
    for i, feature in enumerate(ranked, start=1):
        if deadline.expired():
            report.warn("verify stopped: time budget exhausted")
            break
        if not feature.demo_steps:
            feature.verified, feature.demo_score, feature.demo_note = True, 0.0, "no demo steps"
        else:
            run = run_feature(session, feature, lookup, root_url, out_dir, report, deadline)
            feature.verified = True
            feature.demo_score = compute_demo_score(run)
            feature.demo_note = run.note or None
            feature.thumbnail = run.thumbnail if feature.demo_score > 0 else None
        if on_feature:
            on_feature(i, len(ranked), feature)
