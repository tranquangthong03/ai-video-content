"""Demo verdicts: replay each important feature's steps in a clean context and decide demo_kind.

interaction  something changed *inside* the page (new dialog, list items, elements, main-area pixels)
navigation   the step led to another page (path changed) whose quality is acceptable
showcase     only text/images support it: the section containing the claim is found to highlight
failed       nothing worked and no section was found

Safety (in addition to the request guard): elements are resolved first and the blacklist is checked
on the element that was really found; never click form-submitting controls; Enter only under the
Enter policy; typed text is never checked (the blacklist guards clicked/hovered elements).
"""

import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image, ImageChops
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from app.browser.enter_policy import Policy, enter_decision
from app.browser.locate import (
    ElementInfo,
    Target,
    Unsafe,
    check_clickable,
    check_typeable,
    resolve,
)
from app.browser.page_utils import dismiss_cookie_banner, wait_for_settle
from app.browser.session import BrowserSession
from app.browser.urls import in_scope, normalize_url, same_site
from app.explorer.extract import settle
from app.explorer.models import Element, PageData
from app.explorer.report import Deadline, Report
from app.explorer.samples import CATALOG, pick_sample, sample_path
from app.schemas.generated.page_insight import PageInsight
from app.schemas.generated.product_profile import (
    DemoEvidence,
    DemoStep,
    Feature,
    ProductProfile,
    ShowcaseTarget,
)

MAX_FEATURES = 6
IN_PAGE_DIFF = 0.02  # fraction of main-area pixels that must change (beyond background noise)

SIGNATURE_JS = """
() => {
  const vis = (e) => {
    const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const main = document.querySelector('main');
  const b = main ? main.getBoundingClientRect() : null;
  const x = b ? Math.max(0, b.x) : 0, y = b ? Math.max(0, b.y) : 0;
  const bigMain = b && b.width > 200 && b.height > 200;
  return {
    url: location.href,
    dialogs: document.querySelectorAll('[role=dialog],dialog[open],[aria-modal=true]').length,
    visible: [...document.querySelectorAll('a,button,input,select,textarea,[role=button]')].filter(vis).length,
    items: [...document.querySelectorAll('li,tr,[role=listitem],[role=row]')].filter(vis).length,
    scrollY: Math.round(scrollY),
    editing: (() => {
      const a = document.activeElement;
      const editable = a && (['INPUT', 'TEXTAREA'].includes(a.tagName) || a.isContentEditable);
      return editable ? a.tagName + '#' + (a.id || '') + '.' + (a.className || '') : null;
    })(),
    box: bigMain
      ? { x, y, w: Math.max(1, Math.min(b.width, innerWidth - x)), h: Math.max(1, Math.min(b.height, innerHeight - y)) }
      : { x: 0, y: 0, w: innerWidth, h: innerHeight },
  };
}
"""

# Smallest visible block whose text contains most of the given words; returns a selector for it
SHOWCASE_JS = r"""
(tokens) => {
  const clean = (t) => (t || '').replace(/\s+/g, ' ').trim();
  // navigation-like blocks are never worth highlighting
  const SKIP = 'nav,footer,[role=navigation],[role=contentinfo],#toc,#markdown-toc,[class*=toc],' +
    '[class*=breadcrumb],[aria-label*=breadcrumb i],[class*=sidebar],[class*=menu]';
  const sized = (el) => {
    const r = el.getBoundingClientRect();
    return r.height >= 120 && r.height <= 900 && r.width >= innerWidth * 0.4;
  };
  const usable = (el) => !el.closest(SKIP) && sized(el);
  const fraction = (el) => {
    const text = clean(el.innerText).toLowerCase();
    return text.length < 10 || text.length > 2000 ? 0 : tokens.filter((w) => text.includes(w)).length / tokens.length;
  };
  const hasHeadingAndText = (el) => !!el.querySelector('h1,h2,h3,h4') && !!el.querySelector('p');

  let best = null;
  const consider = (el, score) => {
    if (score < 0.6 || !usable(el)) return;
    const rank = [score >= 0.95 ? 1 : 0, hasHeadingAndText(el) ? 1 : 0];
    const len = clean(el.innerText).length;
    const better = !best || rank[0] > best.rank[0] || (rank[0] === best.rank[0] && (
      rank[1] > best.rank[1] || (rank[1] === best.rank[1] && len < best.len)));
    if (better) best = { el, score, rank, len };
  };
  document.querySelectorAll('section,article,div,main > *').forEach((el) => consider(el, fraction(el)));

  if (!best) {
    // only a small element (heading, paragraph) matches: take the block around it instead
    document.querySelectorAll('h1,h2,h3,h4,p,li').forEach((el) => {
      const score = fraction(el);
      if (score < 0.6 || el.closest(SKIP)) return;
      let block = el.closest('section,article') || el.parentElement;
      while (block && !sized(block) && block.parentElement && block.tagName !== 'BODY') block = block.parentElement;
      if (block && usable(block)) consider(block, Math.max(score, fraction(block)));
    });
  }
  if (!best) return null;
  const pathTo = (el) => {
    const parts = [];
    for (let n = el; n && n.nodeType === 1 && parts.length < 5; n = n.parentElement) {
      if (n.id && /^[A-Za-z][\w-]*$/.test(n.id)) { parts.unshift('#' + n.id); break; }
      const same = n.parentElement ? [...n.parentElement.children].filter((c) => c.tagName === n.tagName) : [n];
      parts.unshift(n.tagName.toLowerCase() + (same.length > 1 ? `:nth-of-type(${same.indexOf(n) + 1})` : ''));
    }
    return parts.join(' > ');
  };
  best.el.scrollIntoView({ block: 'center' });
  const h = best.el.querySelector('h1,h2,h3,h4');
  return {
    selector: pathTo(best.el), score: best.score,
    snippet: clean((h ? h.innerText + ' - ' : '') + best.el.innerText).slice(0, 160),
  };
}
"""


@dataclass
class Evidence:
    """What changed while a feature's steps ran. In-page signals come only from steps that stayed on one path."""

    url_changed: bool = False
    path_changed: bool = False
    dom_delta: int = 0
    new_dialog: bool = False
    new_list_items: int = 0
    visual_diff: float = 0.0
    editing: bool = False  # a double-click turned an element into an input
    notes: list[str] = field(default_factory=list)

    def in_page_signals(self) -> int:
        return sum(
            [
                self.editing,
                self.new_dialog,
                self.new_list_items > 0,
                self.dom_delta >= 2,
                self.visual_diff >= 0.05,
            ]
        )

    def has_in_page_change(self) -> bool:
        return (
            self.editing
            or self.new_dialog
            or self.new_list_items > 0
            or self.dom_delta >= 2
            or self.visual_diff >= IN_PAGE_DIFF
        )


@dataclass
class FeatureRun:
    reached: bool = False
    steps_total: int = 0
    steps_done: int = 0
    evidence: Evidence = field(default_factory=Evidence)
    error: str | None = None
    thumbnail: str | None = None
    final_url: str = ""


def classify_demo(
    ev: Evidence,
    *,
    reached: bool,
    steps_done: int,
    steps_total: int,
    target_quality: float | None = None,
    target_type: str | None = None,
) -> tuple[str | None, float]:
    """(demo_kind, confidence) from what changed, or (None, 0) when nothing conclusive happened.

    interaction wins over navigation; navigation needs an acceptable target page (visual_quality
    >= 0.5 when known) and is more convincing when the target is an app page.
    """
    if not reached:
        return None, 0.0
    if ev.has_in_page_change():
        score = 0.55 + 0.1 * ev.in_page_signals()
        if steps_done < steps_total:
            score -= 0.2
        return "interaction", round(min(0.95, max(0.3, score)), 2)
    if ev.path_changed:
        if target_quality is not None and target_quality < 0.5:
            return None, 0.0
        return "navigation", 0.8 if (target_type or "").startswith("app_") else 0.5
    return None, 0.0


def showcase_score(ratio: float) -> float:
    """Confidence of a showcase from the fraction of claim words found in the section."""
    return round(min(0.95, ratio * 0.95), 2)


def diff_fraction(before: bytes, after: bytes, box: dict[str, int] | None = None) -> float:
    """Fraction of pixels (in `box`, viewport coordinates) that differ noticeably."""
    a = Image.open(io.BytesIO(before)).convert("L")
    b = Image.open(io.BytesIO(after)).convert("L")
    if box:
        x, y = int(box["x"]), int(box["y"])
        crop = (x, y, min(a.width, x + int(box["w"])), min(a.height, y + int(box["h"])))
        a, b = a.crop(crop), b.crop(crop)
    size = (480, max(1, int(480 * a.height / max(1, a.width))))
    diff = ImageChops.difference(a.resize(size), b.resize(size)).point(
        lambda v: 255 if v > 30 else 0
    )
    return diff.histogram()[255] / (size[0] * size[1])


def _snap(page: Page, path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = page.screenshot()
    path.write_bytes(data)
    return data


def _path(url: str) -> str:
    return urlparse(url).path.rstrip("/") or "/"


class StepFailure(RuntimeError):
    """A step could not be carried out. kind: not_found | unsafe | timeout | error."""

    def __init__(self, kind: str, message: str, tried: list[str] | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.tried = tried or []


@dataclass
class Context:
    """Everything a step needs besides the page."""

    lookup: dict[str, PageData]
    root_url: str
    scope_prefix: str | None
    report: Report
    feature_id: str
    enter_policy: Policy
    guard_on: bool
    setup_len: int = 0  # leading steps that only recreate a state; their effects are not evidence
    typed: set[str] = field(default_factory=set)  # sample texts typed so far (data, not labels)


def perform_step(page: Page, step: DemoStep, ctx: Context) -> None:
    """Run one step. Raises StepFailure; never clicks anything the safety rules forbid."""
    report = ctx.report
    if step.do == "goto":
        target = normalize_url(step.url or "", ctx.root_url)
        if not target or not same_site(target, ctx.root_url):
            raise StepFailure("unsafe", f"goto outside the site: {step.url}")
        if not in_scope(target, ctx.root_url, ctx.scope_prefix):
            report.block("verify", target, "out_of_scope", "goto", feature=ctx.feature_id)
            raise StepFailure("unsafe", f"goto outside the scope: {target}")
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
    source = ctx.lookup.get(step_url)
    element: Element | None = source.element(step.ref or "") if source else None
    spec = step.locator or (element.spec() if element else None)
    if spec is None:
        raise StepFailure("not_found", f"ref {step.ref} unknown on {step_url}")
    if normalize_url(page.url) != step_url:  # the ref belongs to another page: go there first
        page.goto(step_url, wait_until="domcontentloaded")
        settle(page)

    name = element.name if element else (step.ref or "?")
    resolution = resolve(page, spec)
    report.record_locate(
        f"{ctx.feature_id}:{step.do}:{name}", resolution.strategy, resolution.tried
    )
    if resolution.target is None:
        report.block(
            "verify", name, "not_found", "; ".join(resolution.tried), feature=ctx.feature_id
        )
        raise StepFailure("not_found", f"cannot locate {name!r}", resolution.tried)
    target = resolution.target
    info = target.info()
    if step.do == "hover" and info.input_type == "file":
        return  # hovering a (usually hidden) file input does nothing: skip without waiting
    try:
        if info.input_type == "file" and step.do in ("click", "dblclick", "type"):
            pass  # becomes an upload in _act; the file input itself is never a blacklist target
        elif step.do in ("click", "dblclick", "right_click", "hover"):
            check_clickable(
                info, ctx.root_url, scope_prefix=ctx.scope_prefix, ignore_texts=ctx.typed
            )
        elif step.do == "type":
            check_typeable(info)
        elif step.do == "upload" and not (info.input_type == "file" or info.file_input):
            raise Unsafe("other", "upload target is not a file input")
    except Unsafe as e:
        report.block("verify", name, e.reason, e.detail, feature=ctx.feature_id)
        raise StepFailure("unsafe", str(e)) from e

    record = {
        "phase": "verify",
        "feature": ctx.feature_id,
        "ref": step.ref,
        "name": name,
        "strategy": resolution.strategy,
    }
    _act(page, step, ctx, target, info, element, name, record)
    wait_for_settle(page)  # network idle + quiet DOM + viewport images loaded


def _sample_for(
    step: DemoStep, info: ElementInfo, element: Element | None, name: str
) -> tuple[str, str]:
    """(sample file name, absolute path) for an upload: the step's file, else chosen by `accept`."""
    accept = info.file_accept or (element.accept if element else None)
    file_name = step.file if step.file in CATALOG else pick_sample(accept, name)
    return file_name, str(sample_path(file_name))


def _auto_upload(ctx: Context, name: str, via: str, file_name: str, step: DemoStep) -> None:
    ctx.report.data["auto_upload"].append(
        {"feature": ctx.feature_id, "ref": step.ref, "name": name, "via": via, "file": file_name}
    )


def _act(
    page: Page,
    step: DemoStep,
    ctx: Context,
    target: Target,
    info: ElementInfo,
    element: Element | None,
    name: str,
    record: dict[str, Any],
) -> None:
    """Carry out a step on the resolved (and already safety-checked) element."""
    report = ctx.report
    if step.do in ("click", "dblclick", "type") and (info.file_input or info.input_type == "file"):
        # a file input, its label or its drop zone: never open a native dialog, upload a sample
        handle = target.file_input()
        if handle:
            report.data["clicks"].append(record)
            file_name, path = _sample_for(step, info, element, name)
            handle.set_input_files(path)
            _auto_upload(ctx, name, "direct", file_name, step)
            return
    if step.do == "click":
        report.data["clicks"].append(record)
        chooser = target.click_catching_file_chooser(page)  # some buttons open a chooser via JS
        if chooser:
            file_name, path = _sample_for(step, info, element, name)
            chooser.set_files(path)
            _auto_upload(ctx, name, "chooser", file_name, step)
    elif step.do == "dblclick":
        report.data["clicks"].append({**record, "kind": "dblclick"})
        target.dblclick()
    elif step.do == "right_click":
        report.data["clicks"].append({**record, "kind": "right_click"})
        target.right_click()
    elif step.do == "hover":
        target.hover()
    elif step.do == "type":
        target.fill(step.text or "")  # typed text is never checked against the blacklist
        if step.text:
            ctx.typed.add(step.text.strip().lower())
        allowed, reason = enter_decision(
            info, page.url, guard_on=ctx.guard_on, policy=ctx.enter_policy
        )
        if allowed:
            target.press("Enter")
            report.data["enter"]["pressed"] += 1
            wait_for_settle(page)
            if not same_site(page.url, ctx.root_url):  # Enter navigated away: come back
                page.go_back()
        else:
            report.data["enter"]["blocked"].append(
                {"feature": ctx.feature_id, "ref": step.ref, "reason": f"enter_blocked: {reason}"}
            )
    elif step.do == "scroll":
        target.scroll_into_view()
    elif step.do == "upload":
        file_name, path = _sample_for(step, info, element, name)
        handle = target.file_input()
        if handle:
            handle.set_input_files(path)
        else:
            target.set_input_files(path)
        report.data["clicks"].append({**record, "file": file_name})


def _fail(
    run: FeatureRun, ctx: Context, page: Page, shots: Path, k: int, step: DemoStep, e: Exception
) -> None:
    """Record why step k failed: kind, strategies tried, and a screenshot of the page at that moment."""
    if isinstance(e, StepFailure):
        kind, tried = e.kind, e.tried
    elif isinstance(e, PlaywrightTimeout):
        kind, tried = "timeout", [str(e)[:200]]
    else:
        kind, tried = "error", [f"{type(e).__name__}: {str(e)[:200]}"]
    shot = shots / f"step{k}_error.png"
    try:
        _snap(page, shot)
    except Exception:
        shot = None  # type: ignore[assignment]
    run.error = f"step {k} ({step.do}) {kind}: {str(e)[:120]}"
    ctx.report.step_error(ctx.feature_id, k, kind, tried, str(shot) if shot else None)


def run_feature(
    session: BrowserSession, feature: Feature, ctx: Context, out_dir: Path, deadline: Deadline
) -> FeatureRun:
    run = FeatureRun(steps_total=len(feature.demo_steps) - ctx.setup_len)
    shots = out_dir / "verify" / re.sub(r"[^\w-]", "_", feature.id)
    context = session.new_context()
    try:
        page = context.new_page()
        start = next((s.url for s in feature.demo_steps if s.do == "goto" and s.url), None) or next(
            (e.url for e in feature.evidence), ctx.root_url
        )
        try:
            response = page.goto(start, wait_until="domcontentloaded")
            settle(page)
            run.reached = response is None or response.status < 400
        except Exception as e:
            run.error = f"cannot open {start}: {type(e).__name__}"
            return run
        dismiss_cookie_banner(page)
        ev = run.evidence

        for k, step in enumerate(feature.demo_steps, start=1):
            if deadline.expired():
                run.error = "time budget exhausted"
                break
            before = page.evaluate(SIGNATURE_JS)
            before_img = _snap(page, shots / f"step{k}_before.png")
            page.wait_for_timeout(350)
            noise = diff_fraction(before_img, page.screenshot(), before["box"])  # idle animation
            try:
                perform_step(page, step, ctx)
            except Exception as e:
                _fail(run, ctx, page, shots, k, step, e)
                break
            if k > ctx.setup_len:
                run.steps_done += 1
            after = page.evaluate(SIGNATURE_JS)
            after_path = shots / f"step{k}_after.png"
            after_img = _snap(page, after_path)
            run.thumbnail = str(after_path)
            run.final_url = after["url"]
            if k <= ctx.setup_len:
                continue  # setup steps only recreate a state; their effects are not evidence

            if normalize_url(before["url"]) != normalize_url(after["url"]):
                ev.url_changed = True
            if _path(before["url"]) != _path(after["url"]):
                ev.path_changed = True
                continue  # a new page: its pixels/elements say nothing about an in-page change
            if step.do == "dblclick" and after["editing"] and after["editing"] != before["editing"]:
                ev.editing = True
                ev.notes.append("double-click turned the element into an input")
            ev.dom_delta += abs(after["visible"] - before["visible"])
            ev.new_dialog |= after["dialogs"] > before["dialogs"]
            ev.new_list_items += max(0, after["items"] - before["items"])
            if abs(after["scrollY"] - before["scrollY"]) < 50:  # scrolling is not a state change
                changed = diff_fraction(before_img, after_img, before["box"])
                ev.visual_diff = max(ev.visual_diff, round(max(0.0, changed - noise), 4))
        run.final_url = run.final_url or page.url
    finally:
        context.close()
    return run


def find_showcase(
    session: BrowserSession, feature: Feature, lookup: dict[str, PageData], out_dir: Path
) -> tuple[ShowcaseTarget, float, str] | None:
    """Locate the section of the page that states the feature (fuzzy match of the quote)."""
    quotes = [e.quote for e in feature.evidence if e.quote]
    words_src = " ".join(quotes) or f"{feature.name} {feature.description}"
    tokens = list(dict.fromkeys(w for w in re.findall(r"\w{3,}", words_src.lower())))[:12]
    pages = [e.url for e in feature.evidence if e.source != "app_action"] or [
        e.url for e in feature.evidence
    ]
    if not tokens or not pages:
        return None
    context = session.new_context()
    try:
        page = context.new_page()
        for url in dict.fromkeys(pages):
            try:
                page.goto(url, wait_until="domcontentloaded")
                settle(page)
            except Exception:
                continue
            dismiss_cookie_banner(page)
            hit = page.evaluate(SHOWCASE_JS, tokens)
            if hit:
                shot = out_dir / "verify" / re.sub(r"[^\w-]", "_", feature.id) / "showcase.png"
                _snap(page, shot)
                target = ShowcaseTarget(
                    url=page.url, selector=hit["selector"], ref=None, text_quote=hit["snippet"]
                )
                return target, showcase_score(hit["score"]), str(shot)
            # no text match: a same-page anchor whose heading names the feature is still a section
            source = lookup.get(normalize_url(url) or "")
            name_words = set(re.findall(r"\w{3,}", feature.name.lower()))
            for anchor in source.anchors if source else []:
                overlap = name_words & set(re.findall(r"\w{3,}", anchor.text.lower()))
                if name_words and len(overlap) / len(name_words) >= 0.5:
                    target = ShowcaseTarget(
                        url=url, selector=anchor.selector, ref=None, text_quote=anchor.text
                    )
                    return target, 0.5, ""
    finally:
        context.close()
    return None


def _apply_showcase(feature: Feature, found: tuple[ShowcaseTarget, float, str]) -> None:
    target, score, shot = found
    feature.demo_kind, feature.demo_score = "showcase", score
    feature.showcase_target = target
    feature.thumbnail = shot or None
    feature.demo_evidence = DemoEvidence(
        url_changed=False,
        dom_delta=0,
        new_dialog=False,
        new_list_items=0,
        visual_diff=0.0,
        target_page_type=None,
        notes="section found for the claim",
    )


def judge_feature(
    session: BrowserSession,
    feature: Feature,
    ctx: Context,
    out_dir: Path,
    deadline: Deadline,
    insights: dict[str, PageInsight],
) -> None:
    """Fill demo_kind / demo_score / demo_evidence / showcase_target / thumbnail / demo_note."""
    feature.verified = True
    text_only = not any(e.source == "app_action" for e in feature.evidence)
    showcase: tuple[ShowcaseTarget, float, str] | None = None
    if text_only:  # marketing claims: highlight the section instead of faking a demo
        showcase = find_showcase(session, feature, ctx.lookup, out_dir)
        if showcase:
            _apply_showcase(feature, showcase)
            return

    run = FeatureRun()
    if feature.demo_steps:
        run = run_feature(session, feature, ctx, out_dir, deadline)
    final = normalize_url(run.final_url) or ""
    insight = insights.get(final)
    kind, score = classify_demo(
        run.evidence,
        reached=run.reached,
        steps_done=run.steps_done,
        steps_total=run.steps_total,
        target_quality=insight.visual_quality if insight else None,
        target_type=insight.page_type if insight else None,
    )
    notes = list(run.evidence.notes)
    if feature.requires_setup:
        notes.append(f"requires setup: first {ctx.setup_len} steps recreate the state")
    if kind == "navigation" and not insight:
        notes.append(f"target page not analysed: {final}")
    feature.demo_evidence = DemoEvidence(
        url_changed=run.evidence.url_changed,
        dom_delta=run.evidence.dom_delta,
        new_dialog=run.evidence.new_dialog,
        new_list_items=run.evidence.new_list_items,
        visual_diff=round(run.evidence.visual_diff, 4),
        target_page_type=insight.page_type if insight else None,
        notes="; ".join(notes),
    )
    feature.demo_note = run.error or (None if feature.demo_steps else "no demo steps")
    if kind:
        feature.demo_kind, feature.demo_score = kind, score  # type: ignore[assignment]
        feature.thumbnail = run.thumbnail
        return
    showcase = showcase or find_showcase(session, feature, ctx.lookup, out_dir)
    if showcase:
        _apply_showcase(feature, showcase)
        return
    feature.demo_kind, feature.demo_score, feature.thumbnail = "failed", 0.0, None


def verify_features(
    session: BrowserSession,
    profile: ProductProfile,
    pages: list[PageData],
    root_url: str,
    out_dir: Path,
    report: Report,
    deadline: Deadline,
    *,
    insights: list[PageInsight] | None = None,
    limit: int = MAX_FEATURES,
    enter_policy: Policy = "strict",
    scope_prefix: str | None = None,
    setup_counts: dict[str, int] | None = None,
    on_feature: Any = None,
) -> None:
    """Judge the `limit` most important features in place; the rest keep demo_kind = None.

    setup_counts: feature id -> number of leading setup steps (stateful features), whose effects
    are replayed but not counted as evidence.
    """
    lookup = {u: p for p in pages if (u := normalize_url(p.url))}
    by_url = {u: i for i in (insights or []) if (u := normalize_url(i.url))}
    ranked = sorted(profile.features, key=lambda f: -f.importance)[:limit]
    for i, feature in enumerate(ranked, start=1):
        if deadline.expired():
            report.warn("verify stopped: time budget exhausted")
            break
        ctx = Context(
            lookup,
            root_url,
            scope_prefix,
            report,
            feature.id,
            enter_policy,
            guard_on=not session.guard.allow_mutations,
            setup_len=(setup_counts or {}).get(feature.id, 0),
        )
        judge_feature(session, feature, ctx, out_dir, deadline, by_url)
        if on_feature:
            on_feature(i, len(ranked), feature)
