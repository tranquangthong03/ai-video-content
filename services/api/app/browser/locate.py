"""Find an element again from a LocatorSpec, and decide whether it is safe to act on.

resolve() tries, in order: stable css -> role + exact name -> role + partial name -> text ->
css + nth -> bbox (only when the element at that point has a matching fingerprint). The strategy
that worked (or every strategy that failed) is returned so reports can show how a step was done.
The blacklist is checked on the element that was actually resolved, not on stored data.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from playwright.sync_api import ElementHandle, Locator, Page

from app.browser.blacklist import is_blocked, is_blocked_href
from app.browser.urls import in_scope, same_site
from app.schemas.generated.locator import LocatorSpec

STRATEGIES = ("css", "role_exact", "role_partial", "text", "css_nth", "bbox")
NEAR_PX = 200  # a bbox match farther than this from the stored position is considered ambiguous

# Runs on an element; the same text normalisation as the extractor uses for fingerprints.
INFO_JS = r"""
(el) => {
  const clean = (t) => (t || '').replace(/\s+/g, ' ').trim();
  const tag = el.tagName.toLowerCase();
  const labelled = (el.getAttribute('aria-labelledby') || '').split(/\s+/)
    .map((i) => (document.getElementById(i) || {}).innerText || '').join(' ');
  const labels = el.labels ? [...el.labels].map((l) => l.innerText).join(' ') : '';
  const texts = [el.getAttribute('aria-label'), el.getAttribute('title'), el.getAttribute('alt'),
    el.getAttribute('placeholder'),
    // a button's value is its label; a text field's value is what the user typed (never checked)
    tag === 'input' && ['button', 'submit', 'reset'].includes((el.type || '').toLowerCase()) ? el.value : '',
    labelled, labels,
    clean(el.innerText).slice(0, 200), el.id, el.getAttribute('name'), el.getAttribute('data-testid')]
    .map(clean).filter(Boolean);
  const form = el.closest('form');
  let formInfo = null;
  if (form) {
    const inputs = [...form.querySelectorAll('input,textarea')];
    const visible = (e) => { const r = e.getBoundingClientRect(); return r.width > 1 && r.height > 1; };
    const textType = (e) => e.tagName === 'TEXTAREA' || ['text', 'search', 'url', 'number', ''].includes((e.type || '').toLowerCase());
    formInfo = {
      method: (form.getAttribute('method') || 'get').toLowerCase(),
      action: form.action,
      text_inputs: inputs.filter((e) => textType(e) && visible(e)).length,
      sensitive: inputs.some((e) => ['password', 'email', 'tel', 'file'].includes((e.type || '').toLowerCase())),
    };
  }
  const type = tag === 'input' ? (el.type || 'text').toLowerCase() : null;
  // the file input this element is, labels, contains, or belongs to a <label> of
  const lab = el.closest ? el.closest('label') : null;
  const fileInput = (tag === 'input' && type === 'file') ? el
    : (el.control && el.control.type === 'file') ? el.control
    : (el.querySelector && el.querySelector('input[type=file]'))
    || (lab && lab.control && lab.control.type === 'file' ? lab.control : null);
  return {
    file_input: !!fileInput, file_accept: fileInput ? fileInput.getAttribute('accept') : null,
    tag, texts, href: tag === 'a' ? el.href : null, input_type: type,
    button_type: tag === 'button' ? (el.getAttribute('type') || 'submit') : null,
    in_form: !!form, form: formInfo,
    is_text_input: tag === 'textarea' || (tag === 'input' && ['text', 'search', 'url', 'number'].includes(type)),
    text: clean(el.innerText).slice(0, 80),
    role: el.getAttribute('role'),
    operable: el.hasAttribute('onclick') || (el.tabIndex >= 0 && !['input', 'textarea', 'select'].includes(tag)),
  };
}
"""

FILE_INPUT_JS = """
(el) => {
  const type = (el.type || '').toLowerCase();
  if (el.tagName === 'INPUT' && type === 'file') return el;
  if (el.control && el.control.type === 'file') return el.control;
  const inner = el.querySelector ? el.querySelector('input[type=file]') : null;
  if (inner) return inner;
  const lab = el.closest ? el.closest('label') : null;
  return lab && lab.control && lab.control.type === 'file' ? lab.control : null;
}
"""

# Element at a page-coordinate point, with its fingerprint head ("tag|text").
POINT_JS = r"""
([x, y]) => {
  window.scrollTo(0, Math.max(0, y - window.innerHeight / 2));
  const el = document.elementFromPoint(x - window.scrollX, y - window.scrollY);
  if (!el) return null;
  const clean = (t) => (t || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const target = el.closest('a,button,input,select,textarea,summary,[role]') || el;
  return { head: target.tagName.toLowerCase() + '|' + clean(target.innerText).slice(0, 80) };
}
"""


@dataclass
class FormInfo:
    method: str
    action: str
    text_inputs: int
    sensitive: bool


INTERACTIVE_ROLES = ("button", "link", "menuitem", "tab", "menuitemcheckbox", "option")


@dataclass
class ElementInfo:
    tag: str
    texts: list[str]
    href: str | None
    input_type: str | None
    button_type: str | None
    in_form: bool
    form: FormInfo | None
    is_text_input: bool
    text: str
    file_input: bool = False  # is, labels, or contains an <input type=file>
    file_accept: str | None = None
    role: str | None = None
    operable: bool = False  # onclick / tabindex: a div that acts as a button

    @property
    def interactive(self) -> bool:
        """A control the visitor operates (button, link, menu item...), not data or a text field."""
        if self.tag in ("a", "button", "summary") or self.role in INTERACTIVE_ROLES:
            return True
        if self.tag == "input":
            return self.input_type in ("button", "submit", "reset", "image")
        return self.operable

    @property
    def submits_form(self) -> bool:
        if self.input_type in ("submit", "image"):
            return True
        return self.tag == "button" and self.in_form and self.button_type == "submit"


class Unsafe(RuntimeError):
    """Acting on this element is forbidden. reason: blacklist | leaves_site | out_of_scope | other."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


ITEM_CONTAINER_JS = (
    "el => el.closest('li,tr,[role=listitem],[role=row],td,[role=cell]') || el.parentElement"
)


class Target:
    """A resolved element: either a Locator or an ElementHandle (bbox strategy), same actions."""

    def __init__(
        self, strategy: str, locator: Locator | None = None, handle: ElementHandle | None = None
    ):
        self.strategy = strategy
        self._obj: Any = locator if locator is not None else handle

    def click(self, timeout: float = 4000) -> None:
        self._obj.click(timeout=timeout)

    def fill(self, text: str, timeout: float = 4000) -> None:
        self._obj.fill(text, timeout=timeout)

    def hover(self, timeout: float = 4000) -> None:
        self._obj.hover(timeout=timeout)

    def dblclick(self, timeout: float = 4000) -> None:
        self._obj.dblclick(timeout=timeout)

    def right_click(self, timeout: float = 4000) -> None:
        self._obj.click(button="right", timeout=timeout)

    def box(self) -> dict[str, float] | None:
        """Bounding box in viewport pixels (None when not rendered)."""
        return self._obj.bounding_box()

    def scroll_into_view_if_needed(self, timeout: float = 4000) -> None:
        self._obj.scroll_into_view_if_needed(timeout=timeout)

    def handle(self) -> Any:
        return self._obj.evaluate_handle("el => el")

    def item_container(self) -> Any:
        """Handle of the list item / row / cell around this element (else its parent)."""
        return self._obj.evaluate_handle(ITEM_CONTAINER_JS)

    def file_input(self) -> ElementHandle | None:
        """The <input type=file> behind this element (itself, its label's control, or a descendant)."""
        return self._obj.evaluate_handle(FILE_INPUT_JS).as_element()

    def click_catching_file_chooser(self, page: Page, timeout: float = 4000) -> Any:
        """Click; return the FileChooser if the click opened one (it is intercepted, never shown)."""
        caught: list[Any] = []

        def handler(
            chooser: Any,
        ) -> None:  # a plain function: Playwright tags handlers with attributes
            caught.append(chooser)

        page.once("filechooser", handler)
        try:
            self._obj.click(timeout=timeout)
            page.wait_for_timeout(300)  # the chooser event arrives shortly after the click
        finally:
            if not caught:
                page.remove_listener("filechooser", handler)
        return caught[0] if caught else None

    def scroll_into_view(self, timeout: float = 4000) -> None:
        self._obj.scroll_into_view_if_needed(timeout=timeout)

    def set_input_files(self, path: str, timeout: float = 4000) -> None:
        self._obj.set_input_files(path, timeout=timeout)

    def press(self, key: str, timeout: float = 4000) -> None:
        self._obj.press(key, timeout=timeout)

    def info(self) -> ElementInfo:
        raw = self._obj.evaluate(INFO_JS)
        form = FormInfo(**raw["form"]) if raw["form"] else None
        return ElementInfo(**{**raw, "form": form})


@dataclass
class Resolution:
    target: Target | None
    tried: list[str] = field(default_factory=list)  # "<strategy>: <why it did not work>"

    @property
    def strategy(self) -> str | None:
        return self.target.strategy if self.target else None


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _pick(
    page: Page, locator: Locator, spec: LocatorSpec, *, visible: bool = True
) -> tuple[Locator | None, str]:
    """Reduce a locator to exactly one element (nearest to the stored bbox when several match)."""
    if visible:
        locator = locator.filter(visible=True)
    n = locator.count()
    if n == 0:
        return None, "no match"
    if n == 1:
        return locator.first, "ok"
    if spec.bbox is None:
        return None, f"ambiguous ({n} matches, no bbox to choose)"
    scroll_y = page.evaluate("window.scrollY")
    scroll_x = page.evaluate("window.scrollX")
    best: tuple[float, int] | None = None
    for i in range(min(n, 30)):
        box = locator.nth(i).bounding_box()
        if not box:
            continue
        dx = (box["x"] + scroll_x) - spec.bbox.x
        dy = (box["y"] + scroll_y) - spec.bbox.y
        dist = (dx * dx + dy * dy) ** 0.5
        if best is None or dist < best[0]:
            best = (dist, i)
    if best is None or best[0] > NEAR_PX:
        return None, f"ambiguous ({n} matches, none near the stored position)"
    return locator.nth(best[1]), f"ok (nearest of {n})"


def _fingerprint_head(spec: LocatorSpec) -> str | None:
    if not spec.fingerprint:
        return None
    parts = spec.fingerprint.split("|")
    return "|".join(parts[:2]) if len(parts) >= 2 else None


def _attempt(page: Page, spec: LocatorSpec) -> Resolution:
    tried: list[str] = []

    def found(strategy: str, loc: Locator) -> Resolution:
        return Resolution(Target(strategy, locator=loc), tried)

    # 1. stable selector
    if spec.css and spec.nth is None:
        try:
            loc = page.locator(spec.css)
            if loc.count() == 1:
                return found("css", loc.first)
            tried.append(f"css: {loc.count()} matches for {spec.css!r}")
        except Exception as e:
            tried.append(f"css: {type(e).__name__}")
    # 2-3. role + name
    role_ok = bool(spec.role) and spec.role not in ("file", "generic")
    if role_ok and spec.name:
        for strategy, exact in (("role_exact", True), ("role_partial", False)):
            try:
                loc, why = _pick(
                    page, page.get_by_role(spec.role, name=spec.name, exact=exact), spec
                )  # type: ignore[arg-type]
            except Exception as e:
                loc, why = None, type(e).__name__
            if loc is not None:
                return found(strategy, loc)
            tried.append(f"{strategy}: {why}")
    # 4. visible text
    if spec.text:
        try:
            loc, why = _pick(page, page.get_by_text(spec.text, exact=False), spec)
        except Exception as e:
            loc, why = None, type(e).__name__
        if loc is not None:
            return found("text", loc)
        tried.append(f"text: {why}")
    # 5. css query + nth, accepted only when the element still looks like the stored one
    if spec.css and spec.nth is not None:
        try:
            query = page.locator(spec.css)
            if query.count() > spec.nth:
                candidate = query.nth(spec.nth)
                info = Target("css_nth", locator=candidate).info()
                head = _fingerprint_head(spec)
                same = head is None or head == f"{info.tag}|{_norm(info.text)}"
                if same:
                    return found("css_nth", candidate)
                tried.append("css_nth: element at that index changed")
            else:
                tried.append(f"css_nth: only {query.count()} matches")
        except Exception as e:
            tried.append(f"css_nth: {type(e).__name__}")
    # 6. coordinates, only when what sits there still matches the fingerprint
    head = _fingerprint_head(spec)
    if spec.bbox and head:
        try:
            cx, cy = spec.bbox.x + spec.bbox.w / 2, spec.bbox.y + spec.bbox.h / 2
            at_point = page.evaluate(POINT_JS, [cx, cy])
            if at_point and at_point["head"] == head:
                handle = page.evaluate_handle(
                    "([x, y]) => { const e = document.elementFromPoint(x - scrollX, y - scrollY);"
                    " return e.closest('a,button,input,select,textarea,summary,[role]') || e; }",
                    [cx, cy],
                ).as_element()
                if handle:
                    return Resolution(Target("bbox", handle=handle), tried)
            tried.append("bbox: fingerprint at that point does not match")
        except Exception as e:
            tried.append(f"bbox: {type(e).__name__}")
    return Resolution(None, tried)


def resolve(page: Page, spec: LocatorSpec, *, retry: bool = True) -> Resolution:
    """Resolve spec on the current page; one short retry covers late rendering."""
    result = _attempt(page, spec)
    if result.target is None and retry:
        page.wait_for_timeout(600)
        again = _attempt(page, spec)
        again.tried = result.tried + ["(retried)"] + again.tried
        return again
    return result


# --- safety on the element that was really resolved -------------------------------------------


def check_clickable(
    info: ElementInfo,
    root_url: str,
    *,
    scope_prefix: str | None = None,
    strict: bool = True,
    ignore_texts: Iterable[str] = (),
) -> None:
    """Raise Unsafe when clicking/hovering this element is forbidden.

    ignore_texts: sample data the explorer typed earlier; an element showing exactly that text
    (a todo item) is data, not a control.
    """
    if is_blocked(*info.texts, strict=strict, ignore=ignore_texts, interactive=info.interactive):
        raise Unsafe("blacklist", f"matches blacklist: {info.texts[:2]}")
    if is_blocked_href(info.href):
        raise Unsafe("blacklist", f"blocked link {info.href}")
    if info.submits_form:
        raise Unsafe("blacklist", "would submit a form")
    if info.href and info.href.startswith("http"):
        if not same_site(info.href, root_url):
            raise Unsafe("leaves_site", info.href)
        if not in_scope(info.href, root_url, scope_prefix):
            raise Unsafe("out_of_scope", info.href)


def check_typeable(info: ElementInfo) -> None:
    """Typing is allowed anywhere except password fields and fields whose own name is blacklisted.
    The typed text itself is never checked."""
    if is_blocked(*info.texts, strict=True, interactive=False):  # a field is not a control
        raise Unsafe("blacklist", f"field matches blacklist: {info.texts[:2]}")
    if info.input_type == "password":
        raise Unsafe("other", "never type into password fields")
