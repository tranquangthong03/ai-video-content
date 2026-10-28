"""frame_inventory: what is on screen, as a list of items the camera can be pointed at.

A snapshot is taken after every main action and about once a second while scrolling, holding or
filling a quiet stretch. Items are the visible, meaningful elements in the viewport (clip pixels),
at most MAX_ITEMS per snapshot, `main` region first. Every element gets a stable id for the
whole page life (window.__inv_ids), so the same element has the same id in later snapshots and in
the action log. `is_new` marks elements that were not in the page when the last action began.
"""

from typing import Any

from playwright.sync_api import ElementHandle, Page

MAX_ITEMS = 40
TEXT_MAX = 80
KINDS = (
    "input", "button", "list_item", "heading", "paragraph", "card", "image", "media",
    "nav", "sidebar", "footer", "dialog", "other",
)  # fmt: skip
REGIONS = ("main", "nav", "aside", "header", "footer")

# shared helpers, injected in front of both scripts
_COMMON_JS = """
const SEL = 'h1,h2,h3,h4,h5,h6,p,li,button,a[href],input,textarea,select,label,img,svg,video,' +
  'canvas,iframe,article,aside,nav,footer,dialog,[role=button],[role=tab],[role=dialog],' +
  '[role=listitem],[role=row],[role=option],[role=img],[contenteditable=true],' +
  '[class*=card],[class*=Card],td,figcaption,summary,span.count,strong';
const ids = (window.__inv_ids = window.__inv_ids || new WeakMap());
window.__inv_next = window.__inv_next || 1;
// every page load has its own salt: ids restart at 1 on each navigation, so without it an id of
// the list page ("Add") would name another element ("Cancel") on the form page
window.__inv_salt = window.__inv_salt || Math.random().toString(36).slice(2, 5);
const idOf = (el) => {
  if (!ids.has(el)) ids.set(el, 'e' + window.__inv_salt + window.__inv_next++);
  return ids.get(el);
};
const alive = (el) => {
  if (el.id && el.id.startsWith('__hl')) return false;
  const cs = getComputedStyle(el);
  if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return false;
  const r = el.getBoundingClientRect();
  return r.width >= 8 && r.height >= 8;
};
"""

# remember which elements exist right now: anything not in this set later is "new"
MARK_JS = (
    "() => {"
    + _COMMON_JS
    + """
  const base = new Set();
  for (const el of document.querySelectorAll(SEL)) if (alive(el)) base.add(idOf(el));
  window.__inv_base = base;
  return base.size;
}"""
)

ELEMENT_ID_JS = "(el) => {" + _COMMON_JS + " return idOf(el); }"

SNAPSHOT_JS = (
    "([extra, maxItems, textMax]) => {"
    + _COMMON_JS
    + """
  const vw = innerWidth, vh = innerHeight;
  const base = window.__inv_base || null;
  const clean = (t) => (t || '').replace(/\\s+/g, ' ').trim().slice(0, textMax);
  const regionOf = (el) => {
    if (el.closest('footer,[role=contentinfo]')) return 'footer';
    if (el.closest('nav,[role=navigation]')) return 'nav';
    if (el.closest('aside,[role=complementary]')) return 'aside';
    if (el.closest('header,[role=banner]')) return 'header';
    return 'main';
  };
  const kindOf = (el, tag, role) => {
    if (tag === 'nav' || role === 'navigation') return 'nav';
    if (tag === 'aside' || role === 'complementary') return 'sidebar';
    if (tag === 'footer' || role === 'contentinfo') return 'footer';
    if (tag === 'dialog' || role === 'dialog') return 'dialog';
    if (tag === 'input' || tag === 'textarea' || tag === 'select' ||
        el.isContentEditable) return 'input';
    if (tag === 'button' || role === 'button' || role === 'tab' || tag === 'summary') return 'button';
    if (tag === 'a') return 'button';
    if (/^h[1-6]$/.test(tag)) return 'heading';
    if (tag === 'li' || role === 'listitem' || role === 'row' || role === 'option' ||
        tag === 'td') return 'list_item';
    if (tag === 'img' || tag === 'svg' || role === 'img') return 'image';
    if (tag === 'video' || tag === 'canvas' || tag === 'iframe') return 'media';
    if (tag === 'article' || /card/i.test(el.className && el.className.toString())) return 'card';
    if (tag === 'p' || tag === 'label' || tag === 'figcaption' || tag === 'span' ||
        tag === 'strong') return 'paragraph';
    return 'other';
  };
  // only a field one types words into counts (not a select, a checkbox, a slider or a file picker)
  const typedInto = (el, tag) => {
    if (tag === 'select') return false;
    if (tag === 'input' && ['checkbox', 'radio', 'range', 'button', 'file', 'submit', 'color', 'hidden'].includes((el.type || '').toLowerCase())) return false;
    return !!(el.value && String(el.value).trim());
  };
  const textOf = (el, tag) => {
    if (tag === 'input' || tag === 'textarea') {
      return clean(el.value || el.placeholder || el.getAttribute('aria-label'));
    }
    if (tag === 'img') return clean(el.alt || el.getAttribute('aria-label'));
    return clean(el.innerText || el.getAttribute('aria-label') || el.title);
  };
  // has a picture / canvas / video got its content: true / false, or undefined when it cannot be told
  const loadedOf = (el, tag) => {
    try {
      if (tag === 'img') return !!(el.complete && el.naturalWidth > 0);
      if (tag === 'video') return el.readyState >= 2;
      if (tag === 'canvas') {
        const ctx = el.getContext && el.getContext('2d');
        if (!ctx || !el.width || !el.height) return undefined; // (a WebGL canvas gives no 2d context)
        for (let i = 0; i < 24; i++) {
          for (let j = 0; j < 24; j++) {
            const px = ctx.getImageData(Math.floor((el.width - 1) * i / 23), Math.floor((el.height - 1) * j / 23), 1, 1).data;
            if (px[3] > 0) return true;
          }
        }
        return false;
      }
    } catch (e) { /* a tainted canvas: unknown */ }
    return undefined;
  };
  const out = [];
  const seen = new Set();
  const add = (el, forced) => {
    if (!el || !el.isConnected || !alive(el)) return;
    const r = el.getBoundingClientRect();
    if (r.bottom <= 0 || r.right <= 0 || r.top >= vh || r.left >= vw) return;
    const id = idOf(el);
    if (seen.has(id)) return;
    seen.add(id);
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role');
    const x = Math.max(0, r.left), y = Math.max(0, r.top);
    const w = Math.min(vw, r.right) - x, h = Math.min(vh, r.bottom) - y;
    const text = textOf(el, tag);
    const kind = kindOf(el, tag, role);
    if (!forced && !text && !['input', 'image', 'media', 'card', 'nav', 'sidebar', 'footer',
        'dialog'].includes(kind)) return;
    out.push({
      id, role: role || (tag === 'a' ? 'link' : tag), tag, text, kind,
      region: regionOf(el), is_new: base ? !base.has(id) : false, forced: !!forced,
      bbox: { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) },
      // a field somebody typed into (the text of an empty one is only its placeholder)
      ...(kind === 'input' ? { filled: typedInto(el, tag) } : {}),
      ...(['img', 'video', 'canvas'].includes(tag) && loadedOf(el, tag) !== undefined
        ? { loaded: loadedOf(el, tag) } : {}),
    });
  };
  if (extra) add(extra, true);
  for (const el of document.querySelectorAll(SEL)) add(el, false);
  const rank = (i) => (i.forced ? 0 : i.is_new ? 1 : i.region === 'main' ? 2 : 3);
  out.sort((a, b) => rank(a) - rank(b) || a.bbox.y - b.bbox.y || a.bbox.x - b.bbox.x);
  const kept = out.slice(0, maxItems);
  kept.sort((a, b) => a.bbox.y - b.bbox.y || a.bbox.x - b.bbox.x);
  return kept.map(({ forced, ...rest }) => rest);
}"""
)


def mark_baseline(page: Page) -> None:
    """Remember the elements on the page now (call before an action; later ones are `is_new`)."""
    try:
        page.evaluate(MARK_JS)
    except Exception:
        pass


def element_id(page: Page, handle: ElementHandle) -> str | None:
    try:
        return str(page.evaluate(ELEMENT_ID_JS, handle))
    except Exception:
        return None


def snapshot(page: Page, extra: ElementHandle | None = None) -> list[dict[str, Any]]:
    """Visible items in the viewport; `extra` (the element just worked on) is always included."""
    try:
        items: list[dict[str, Any]] = page.evaluate(SNAPSHOT_JS, [extra, MAX_ITEMS, TEXT_MAX])
    except Exception:
        return []
    return items
