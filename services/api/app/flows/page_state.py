"""What the Flow Agent sees each round: the page's url, heading, messages and the elements a user
could act on (in or near the viewport, at most MAX_ELEMENTS), each with a short ref.

Refs are renumbered every round; PageState.by_ref maps one back to the element and its
LocatorSpec, which is what the actions (and the replay) resolve. Elements the agent must never
touch are not listed: blacklisted controls, password fields, links to side or sensitive pages.
"""

from dataclasses import dataclass, field
from typing import Any

from playwright.sync_api import Page

from app.browser.auth_detect import is_logout_url
from app.browser.blacklist import is_blocked, is_blocked_href
from app.core.subpages import is_sensitive_text, is_subpage_text
from app.schemas.generated.locator import Bbox, LocatorSpec

MAX_ELEMENTS = 60
MAX_OPTIONS = 10
MAX_MESSAGES = 5
NEAR_VIEWPORTS = 0.75  # elements up to this many viewport heights above/below are listed too

STATE_JS = r"""
(nearFactor) => {
  const clean = (t) => (t || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
  };
  const regionOf = (el) => {
    if (el.closest('[role=dialog],dialog,[aria-modal=true]')) return 'dialog';
    if (el.closest('nav,[role=navigation]')) return 'nav';
    if (el.closest('aside,[role=complementary]')) return 'aside';
    if (el.closest('header,[role=banner]')) return 'header';
    if (el.closest('footer,[role=contentinfo]')) return 'footer';
    return 'main';
  };
  const roleOf = (el) => {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'button' || tag === 'summary') return 'button';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') {
      const t = (el.type || 'text').toLowerCase();
      if (['button', 'submit', 'reset', 'image'].includes(t)) return 'button';
      if (['checkbox', 'radio'].includes(t)) return t;
      if (t === 'file') return 'file';
      if (t === 'range') return 'slider';
      return 'textbox';
    }
    if (el.isContentEditable) return 'textbox';
    return 'button';
  };
  const labelNear = (el) => {
    // a label that sits next to the control rather than being tied to it (common in custom forms)
    let node = el;
    for (let i = 0; i < 3 && node.parentElement; i++) {
      // a short text block right before the control (or before the box that wraps it)
      const before = node.previousElementSibling;
      if (before && !before.querySelector('input,select,textarea,button,a')) {
        const t = clean(before.innerText);
        const b = before.getBoundingClientRect(), c = node.getBoundingClientRect();
        // it must sit above the control or just to its left, not be another column's label
        const near = (b.bottom <= c.top + 4 && Math.min(b.right, c.right) > Math.max(b.left, c.left)) ||
          (b.right <= c.left + 4 && Math.min(b.bottom, c.bottom) > Math.max(b.top, c.top));
        if (t && t.length <= 50 && near) return t;
      }
      node = node.parentElement;
      const controls = node.querySelectorAll('input:not([type=hidden]),select,textarea,[role=combobox],[role=textbox]');
      if (controls.length > 1) return '';
      const label = node.querySelector('label,legend,[class*=label]');
      if (label && !label.contains(el)) { const t = clean(label.innerText); if (t) return t; }
    }
    return '';
  };
  const labelByPosition = (el) => {
    // the nearest short label above the control, or just to its left, in the same column / row
    const r = el.getBoundingClientRect();
    let best = '', bestScore = 1e9;
    document.querySelectorAll('label,legend,[class*=label]').forEach((l) => {
      if (l.contains(el) || l.querySelector('input,select,textarea,button') || !visible(l)) return;
      const t = clean(l.innerText);
      if (!t || t.length > 40) return;
      const b = l.getBoundingClientRect();
      const overlapX = Math.min(b.right, r.right) - Math.max(b.left, r.left);
      const overlapY = Math.min(b.bottom, r.bottom) - Math.max(b.top, r.top);
      const above = b.bottom <= r.top + 4 && r.top - b.bottom < 60 && overlapX > 0;
      const left = b.right <= r.left + 4 && r.left - b.right < 120 && overlapY > 0;
      const score = above ? r.top - b.bottom : left ? (r.left - b.right) * 0.5 + 30 : 1e9;
      if (score < bestScore) { best = t; bestScore = score; }
    });
    return best;
  };
  const nameOf = (el, tag, type) => {
    const aria = el.getAttribute('aria-label');
    if (aria) return clean(aria);
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const t = clean(lb.split(/\s+/).map((i) => (document.getElementById(i) || {}).innerText || '').join(' '));
      if (t) return t;
    }
    if (tag === 'input' && ['button', 'submit', 'reset'].includes(type)) return clean(el.value);
    if (el.labels && el.labels.length) { const t = clean(el.labels[0].innerText); if (t) return t; }
    const field = tag === 'input' || tag === 'textarea' || tag === 'select' || el.getAttribute('role') === 'combobox';
    if (field) { const t = labelNear(el) || labelByPosition(el); if (t) return t; }
    if (tag === 'input' && ['checkbox', 'radio'].includes(type)) {
      // a tick box of a list item has no label of its own: it is named by its row
      const row = el.closest('li,tr,[role=row],[role=listitem]');
      const t = row ? clean(row.innerText).slice(0, 60) : '';
      if (t) return t;
    }
    const txt = clean(el.innerText || el.textContent);
    if (txt) return txt;
    const img = el.querySelector('img[alt]');
    return clean(el.getAttribute('placeholder') || el.getAttribute('title') || (img && img.getAttribute('alt')));
  };
  const stableId = (id) => /^[A-Za-z][\w-]{1,40}$/.test(id) && !/\d{4,}/.test(id) && !/^:?r\d/.test(id) && !/radix|headlessui/i.test(id);
  const unique = (sel) => { try { return document.querySelectorAll(sel).length === 1; } catch (e) { return false; } };
  const selectorOf = (el) => {
    for (const attr of ['data-testid', 'data-test', 'data-cy']) {
      const v = el.getAttribute(attr);
      if (v) { const s = `[${attr}="${v.replace(/"/g, '\\"')}"]`; if (unique(s)) return s; }
    }
    if (el.id && stableId(el.id)) { const s = '#' + CSS.escape(el.id); if (unique(s)) return s; }
    const aria = el.getAttribute('aria-label');
    if (aria) { const s = `${el.tagName.toLowerCase()}[aria-label="${aria.replace(/"/g, '\\"')}"]`; if (unique(s)) return s; }
    return null;
  };

  const vh = innerHeight, vw = innerWidth;
  const BASE = 'a[href], button, input, select, textarea, summary, [role=button], [role=link], [role=tab], ' +
    '[role=menuitem], [role=checkbox], [role=radio], [role=switch], [role=option], [role=combobox], ' +
    '[role=textbox], [contenteditable=""], [contenteditable=true], [onclick], [aria-haspopup]';
  // options of a custom dropdown have no role: the leaves of a visible popup are listed as options
  const POPUP = '[role=listbox],[role=menu],[class*=dropdown-menu],[class*=select-dropdown],[class*=autocomplete],[class*=options]';
  const popupLeaves = new Set();
  document.querySelectorAll(POPUP).forEach((p) => {
    if (!visible(p)) return;
    [...p.querySelectorAll('li,div,span,a')].filter((x) => !x.children.length && clean(x.innerText)).slice(0, 12)
      .forEach((x) => popupLeaves.add(x));
  });
  const candidates = [...new Set([...document.querySelectorAll(BASE), ...popupLeaves])];

  const seen = new Set();
  const hasMain = !!document.querySelector('main');
  const REGION_ROOT = { nav: 'nav', aside: 'aside', header: 'header', footer: 'footer' };
  const elements = [];
  candidates.forEach((el, index) => {
    if (seen.has(el) || elements.length >= 400) return;
    const tag = el.tagName.toLowerCase();
    const type = tag === 'input' ? (el.type || 'text').toLowerCase() : '';
    if (type === 'hidden' || type === 'password') return;
    const isFile = type === 'file';
    // a styled tick box is often drawn by its label while the input itself is transparent
    const tickBox = tag === 'input' && ['checkbox', 'radio'].includes(type) && el.getBoundingClientRect().width > 1;
    if (!(isFile || tickBox || visible(el))) return;
    const r = el.getBoundingClientRect();
    if (r.bottom < -vh * nearFactor || r.top > vh * (1 + nearFactor)) return;
    seen.add(el);
    const role = popupLeaves.has(el) ? 'option' : roleOf(el);
    const name = nameOf(el, tag, type).slice(0, 80);
    if (!name && !['textbox', 'checkbox', 'radio', 'file', 'combobox'].includes(role)) return;
    let value = '', options = [];
    if (tag === 'select') {
      value = clean(el.selectedOptions[0] ? el.selectedOptions[0].text : '');
      options = [...el.options].map((o) => clean(o.text)).filter(Boolean).slice(0, 10);
    } else if (['checkbox', 'radio'].includes(type) || ['checkbox', 'radio', 'switch'].includes(el.getAttribute('role'))) {
      value = (el.checked || el.getAttribute('aria-checked') === 'true') ? 'checked' : 'unchecked';
    } else if (tag === 'input' || tag === 'textarea') {
      value = clean(el.value).slice(0, 60);
    } else if (['combobox', 'textbox'].includes(role)) {
      value = clean(el.innerText).slice(0, 60);
    }
    if (tag === 'input' && ['button', 'submit', 'reset'].includes(type)) value = '';
    const region = regionOf(el);
    const kind = el.hasAttribute('role') ? `[role="${el.getAttribute('role')}"]` : (isFile ? 'input[type=file]' : tag);
    const scoped = region === 'main' ? (hasMain ? 'main ' : '') : (REGION_ROOT[region] || '') ;
    let query = (scoped && scoped.trim() ? scoped.trim() + ' ' : '') + kind;
    let nth = [...document.querySelectorAll(query)].indexOf(el);
    if (nth < 0) { query = kind; nth = [...document.querySelectorAll(query)].indexOf(el); }
    const stable = selectorOf(el);
    const text = clean(el.innerText).slice(0, 80);
    const cx = r.x + r.width / 2, cy = r.y + scrollY + r.height / 2;
    elements.push({
      index, role, tag, name, text, value, options, region,
      // named by the list item it sits in: that text is the user's data, not a label to judge
      row_named: tag === 'input' && ['checkbox', 'radio'].includes(type) && !el.getAttribute('aria-label') && !(el.labels && el.labels.length),
      placeholder: clean(el.getAttribute('placeholder')).slice(0, 60),
      input_type: type || null,
      disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
      required: !!el.required || el.getAttribute('aria-required') === 'true',
      invalid: el.getAttribute('aria-invalid') === 'true',
      href: tag === 'a' ? el.href : null,
      in_form: !!el.closest('form'),
      button_type: tag === 'button' ? (el.getAttribute('type') || 'submit') : null,
      in_view: r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw,
      selector: stable, query, nth,
      fingerprint: `${tag}|${text.toLowerCase()}|${(cx / vw).toFixed(2)},${(cy / Math.max(1, document.documentElement.scrollHeight)).toFixed(2)}`,
      bbox: [Math.round(r.x), Math.round(r.y + scrollY), Math.round(r.width), Math.round(r.height)],
    });
  });

  // what the page says: alerts, toasts and validation messages that are visible now
  const messages = [];
  const addMessage = (el) => {
    const t = clean(el.innerText).slice(0, 160);
    if (t && visible(el) && !messages.includes(t) && messages.length < 8) messages.push(t);
  };
  document.querySelectorAll('[role=alert],[role=status],[aria-live=assertive],[aria-live=polite],[class*=error],[class*=invalid],[class*=toast],[class*=alert],[class*=notification]')
    .forEach((el) => { if (!el.querySelector('input,button,select,textarea')) addMessage(el); });
  document.querySelectorAll('[aria-invalid=true]').forEach((f) => {
    const id = f.getAttribute('aria-describedby');
    const d = id && document.getElementById(id);
    if (d) addMessage(d);
  });

  if (!elements.some((e) => e.region === 'main' || e.region === 'dialog')) {
    // nothing to operate in the page body: say what it shows (e.g. "No Leave Types with Leave Balance")
    const seenText = new Set();
    document.querySelectorAll('p,span,div,h3,h4,h5,h6').forEach((el) => {
      if (el.children.length || !visible(el)) return;
      if (el.closest('nav,aside,header,footer,[role=navigation],[class*=sidebar],[class*=topbar]')) return;
      const t = clean(el.innerText);
      if (t.length < 8 || t.length > 120 || t.includes('©') || seenText.has(t) || seenText.size >= 4) return;
      seenText.add(t);
      if (messages.length < 8) messages.push('Nội dung trang: ' + t);
    });
  }
  // a big canvas / svg in the page body (a drawing, a chart, an image editor): text will not say it
  let canvasRatio = 0;
  document.querySelectorAll('canvas,svg').forEach((c) => {
    if (!visible(c) || c.closest('nav,aside,header,footer,[role=navigation]')) return;
    const r = c.getBoundingClientRect();
    const w = Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0));
    const h = Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0));
    canvasRatio = Math.max(canvasRatio, (w * h) / (vw * vh));
  });
  const heading = (sel) => [...document.querySelectorAll(sel)].find((x) => visible(x) && clean(x.innerText));
  const h = heading('h1,h2,[role=heading]') || heading('h3,h4,h5,h6');
  return {
    url: location.href, title: document.title, heading: h ? clean(h.innerText).slice(0, 140) : '',
    messages, elements, canvas_ratio: Math.round(canvasRatio * 100) / 100, scroll_y: Math.round(scrollY),
    max_scroll: Math.max(0, document.documentElement.scrollHeight - innerHeight),
  };
}
"""


@dataclass
class PageElement:
    ref: str
    role: str
    tag: str
    name: str
    placeholder: str = ""
    value: str = ""
    options: list[str] = field(default_factory=list)
    disabled: bool = False
    required: bool = False
    invalid: bool = False
    region: str = "main"
    in_view: bool = True
    href: str | None = None
    input_type: str | None = None
    button_type: str | None = None
    in_form: bool = False
    locator: LocatorSpec = field(default_factory=LocatorSpec)

    @property
    def is_submit_like(self) -> bool:
        """A form's submit button, judged by the DOM (the agent also checks the name)."""
        return (
            self.tag == "button" and self.in_form and self.button_type == "submit"
        ) or self.input_type in ("submit", "image")


@dataclass
class PageState:
    url: str
    title: str
    heading: str
    messages: list[str]
    elements: list[PageElement]
    scroll_y: int = 0
    max_scroll: int = 0
    canvas_ratio: float = 0.0  # share of the viewport taken by the biggest canvas / svg in the body

    @property
    def by_ref(self) -> dict[str, PageElement]:
        return {e.ref: e for e in self.elements}

    @property
    def can_scroll_down(self) -> bool:
        return self.scroll_y < self.max_scroll - 4


def _listed(raw: dict[str, Any]) -> bool:
    """False for what the agent must never be offered."""
    name, role = raw["name"], raw["role"]
    texts = [] if raw.get("row_named") else [name, raw["text"]]
    if is_blocked(*texts, interactive=role not in ("textbox", "heading")):
        return False
    href = raw["href"]
    if href and (is_blocked_href(href) or is_logout_url(href)):
        return False
    if role == "link" and (is_sensitive_text(name) or is_subpage_text(name)):
        return False
    return True


def _rank(raw: dict[str, Any]) -> tuple[int, int, int]:
    """Lower is kept first when there are more than MAX_ELEMENTS: dialogs, then what is on screen,
    then the main content, in document order."""
    region = {"dialog": 0, "main": 1, "nav": 2, "aside": 2, "header": 3, "footer": 4}
    return (
        0 if raw["region"] == "dialog" else 1,
        0 if raw["in_view"] else 1,
        region.get(raw["region"], 4),
    )


def build_state(raw: dict[str, Any]) -> PageState:
    kept = [e for e in raw["elements"] if _listed(e)]
    kept = sorted(sorted(kept, key=_rank)[:MAX_ELEMENTS], key=lambda e: e["index"])
    elements: list[PageElement] = []
    for i, e in enumerate(kept, start=1):
        x, y, w, h = e["bbox"]
        stable = e["selector"]
        spec = LocatorSpec(
            role=None if e["role"] == "file" else e["role"],
            name=e["name"] or None,
            text=e["text"] or None,
            css=stable or e["query"],
            nth=None if stable else e["nth"],
            tag=e["tag"],
            fingerprint=e["fingerprint"],
            bbox=Bbox(x=x, y=y, w=w, h=h),
        )
        elements.append(
            PageElement(
                ref=f"e{i}", role=e["role"], tag=e["tag"], name=e["name"],
                placeholder=e["placeholder"], value=e["value"], options=e["options"][:MAX_OPTIONS],
                disabled=e["disabled"], required=e["required"], invalid=e["invalid"],
                region=e["region"], in_view=e["in_view"], href=e["href"],
                input_type=e["input_type"], button_type=e["button_type"], in_form=e["in_form"],
                locator=spec,
            )
        )  # fmt: skip
    return PageState(
        url=raw["url"],
        title=raw["title"],
        heading=raw["heading"],
        messages=[m for m in raw["messages"] if m][:MAX_MESSAGES],
        elements=elements,
        scroll_y=raw["scroll_y"],
        max_scroll=raw["max_scroll"],
        canvas_ratio=raw.get("canvas_ratio", 0.0),
    )


def capture_state(page: Page) -> PageState:
    """The state of the page as it is now (read-only: nothing is clicked or typed)."""
    return build_state(page.evaluate(STATE_JS, NEAR_VIEWPORTS))


def format_elements(elements: list[PageElement]) -> str:
    """One line per element: ref | role | name | placeholder | value | options | flags | region."""
    lines = []
    for e in elements:
        flags = []
        if e.disabled:
            flags.append("disabled")
        if e.required:
            flags.append("required")
        if e.invalid:
            flags.append("invalid")
        if not e.in_view:
            flags.append("offscreen")
        lines.append(
            " | ".join(
                [
                    e.ref,
                    e.role,
                    e.name or "-",
                    e.placeholder or "-",
                    e.value or "-",
                    "/".join(e.options) if e.options else "-",
                    ",".join(flags) or "-",
                    e.region,
                ]
            )
        )
    return "\n".join(lines)


def format_messages(messages: list[str]) -> str:
    return "; ".join(messages) if messages else "không có"
