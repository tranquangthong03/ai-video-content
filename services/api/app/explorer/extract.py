"""Page extraction: headings, key texts, interactive elements with short stable refs, signals, screenshot."""

import json
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from app.explorer.models import Anchor, Element, FormData, Heading, PageData
from app.schemas.generated.locator import Bbox, LocatorSpec

MAX_ELEMENTS = 120
REGION_PRIORITY = {"main": 0, "nav": 1, "aside": 1, "header": 2, "footer": 3}

# Runs in the page. Returns raw data; Python picks/limits/orders it deterministically.
EXTRACT_JS = r"""
() => {
  const visible = (el) => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
  };
  const regionOf = (el) => {
    if (el.closest('nav,[role=navigation]')) return 'nav';
    if (el.closest('aside,[role=complementary]')) return 'aside';
    if (el.closest('header,[role=banner]')) return 'header';
    if (el.closest('footer,[role=contentinfo]')) return 'footer';
    return 'main';
  };
  const clean = (t) => (t || '').replace(/\s+/g, ' ').trim();
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
      if (t === 'checkbox') return 'checkbox';
      if (t === 'radio') return 'radio';
      if (t === 'range') return 'slider';
      if (t === 'search') return 'searchbox';
      if (t === 'file') return 'file';
      return 'textbox';
    }
    if (el.isContentEditable) return 'textbox';
    return 'button';
  };
  const nameOf = (el) => {
    const aria = el.getAttribute('aria-label');
    if (aria) return clean(aria);
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const t = clean(lb.split(/\s+/).map((i) => (document.getElementById(i) || {}).innerText || '').join(' '));
      if (t) return t;
    }
    if (el.tagName === 'INPUT' && ['button', 'submit', 'reset'].includes(el.type)) return clean(el.value);
    if (el.labels && el.labels.length) { const t = clean(el.labels[0].innerText); if (t) return t.slice(0, 80); }
    const txt = clean(el.innerText || el.textContent);
    if (txt) return txt.slice(0, 80);
    const img = el.querySelector('img[alt]');
    return clean(el.getAttribute('placeholder') || el.getAttribute('title') || (img && img.getAttribute('alt')) || el.getAttribute('alt')).slice(0, 80);
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

  const sel = 'a[href], button, input, select, textarea, summary, [role=button], [role=link], ' +
    '[role=tab], [role=menuitem], [role=checkbox], [role=switch], [role=option], [contenteditable=""], ' +
    '[contenteditable=true], [onclick]';
  const REGION_ROOT = { nav: 'nav', aside: 'aside', header: 'header', footer: 'footer' };
  const hasMain = !!document.querySelector('main');
  const formOf = (el) => {
    const form = el.closest('form');
    if (!form) return null;
    const inputs = [...form.querySelectorAll('input,textarea')];
    const textType = (e) => e.tagName === 'TEXTAREA' || ['text', 'search', 'url', 'number', ''].includes((e.type || '').toLowerCase());
    return {
      method: (form.getAttribute('method') || 'get').toLowerCase(), action: form.action,
      text_inputs: inputs.filter((e) => textType(e) && visible(e)).length,
      sensitive: inputs.some((e) => ['password', 'email', 'tel', 'file'].includes((e.type || '').toLowerCase())),
    };
  };
  const seen = new Set();
  const elements = [];
  document.querySelectorAll(sel).forEach((el, index) => {
    const isFile = el.tagName === 'INPUT' && (el.type || '').toLowerCase() === 'file';
    if (el.tagName === 'INPUT' && (el.type || '').toLowerCase() === 'hidden') return;
    // hidden file inputs (behind a button or drop zone) are the upload targets, so they are kept
    if (seen.has(el) || elements.length >= 600 || !(isFile || visible(el))) return;
    seen.add(el);
    let name = nameOf(el);
    if (isFile && !name) {
      const zone = el.closest('label,[class*=drop],[class*=upload]');
      name = clean((zone && zone.innerText) || el.getAttribute('title') || el.getAttribute('accept') || 'Tải tệp lên').slice(0, 80);
    }
    const role = roleOf(el);
    if (!name && !['textbox', 'searchbox', 'checkbox', 'file'].includes(role)) return;
    const tag = el.tagName.toLowerCase();
    const region = regionOf(el);
    const r = el.getBoundingClientRect();
    // a css query + position among its matches: the fallback when there is no stable selector
    const kind = el.hasAttribute('role') ? `[role="${el.getAttribute('role')}"]` : (isFile ? 'input[type=file]' : tag);
    const scoped = region === 'main' ? (hasMain ? 'main ' : '') : REGION_ROOT[region] + ' ';
    let query = scoped + kind;
    let nth = [...document.querySelectorAll(query)].indexOf(el);
    if (nth < 0) { query = kind; nth = [...document.querySelectorAll(query)].indexOf(el); }
    const text = clean(el.innerText).slice(0, 80);
    const cx = r.x + r.width / 2, cy = r.y + scrollY + r.height / 2;
    el.setAttribute('data-svai-i', String(index)); // lets Python map the browser's accessible name back
    elements.push({
      index, role, name, text, region, tag, query, nth,
      href: el.tagName === 'A' ? el.href : null,
      selector: selectorOf(el),
      input_type: el.tagName === 'INPUT' ? (el.type || 'text') : null,
      button_type: el.tagName === 'BUTTON' ? (el.getAttribute('type') || 'submit') : null,
      accept: isFile ? el.getAttribute('accept') : null,
      caps: isFile ? ['upload'] : [],
      in_form: !!el.closest('form'), form: formOf(el),
      fingerprint: `${tag}|${text.toLowerCase()}|${(cx / innerWidth).toFixed(2)},${(cy / Math.max(1, document.documentElement.scrollHeight)).toFixed(2)}`,
      bbox: [Math.round(r.x), Math.round(r.y + scrollY), Math.round(r.width), Math.round(r.height)],
    });
  });

  const anchors = [];
  document.querySelectorAll('a[href*="#"]').forEach((a) => {
    try {
      const u = new URL(a.href);
      const samePage = u.pathname.replace(/\/$/, '') === location.pathname.replace(/\/$/, '');
      if (!samePage || u.hash.length < 2 || u.hash.startsWith('#/') || u.hash.startsWith('#!')) return;
      const id = decodeURIComponent(u.hash.slice(1));
      const target = document.getElementById(id);
      if (target && !anchors.some((x) => x.id === id)) {
        anchors.push({ id, selector: '#' + CSS.escape(id), text: clean((target.querySelector('h1,h2,h3') || target).innerText).slice(0, 100) });
      }
    } catch (e) { /* malformed href */ }
  });

  const headings = [];
  document.querySelectorAll('h1,h2,h3').forEach((h) => {
    const text = clean(h.innerText);
    if (text && visible(h) && headings.length < 40) headings.push({ level: +h.tagName[1], text: text.slice(0, 140) });
  });

  const texts = [];
  const push = (t) => { t = clean(t); if (t && t.length >= 3 && !texts.includes(t) && texts.length < 40) texts.push(t); };
  const h1 = document.querySelector('h1');
  if (h1 && visible(h1)) {
    push(h1.innerText);
    const next = h1.parentElement && h1.parentElement.querySelector('p, h2');
    if (next) push(clean(next.innerText).slice(0, 200));
  }
  document.querySelectorAll('h2,h3').forEach((h) => visible(h) && push(h.innerText));
  document.querySelectorAll('p, li, [class*=desc], [class*=subtitle]').forEach((p) => {
    const t = clean(p.innerText);
    if (t.length >= 20 && t.length <= 200 && visible(p)) push(t);
  });
  const emptyRe = /(no \w+ (yet|found)|nothing (here|to show)|empty|get started|không có|chưa có|trống)/i;
  document.querySelectorAll('main *, body > div *').forEach((e) => {
    if (e.children.length === 0 && emptyRe.test(e.innerText || '') && (e.innerText || '').length < 120 && visible(e)) push('[empty state] ' + e.innerText);
  });

  const body = document.body ? document.body.innerText : '';
  const bigInputs = [...document.querySelectorAll('input[type=text],input[type=search],input:not([type]),textarea,[contenteditable=true],input[type=file],[class*=drop]')]
    .filter((e) => { const r = e.getBoundingClientRect(); return visible(e) && r.width >= 400 && r.height >= 40; }).length;
  const cardCounts = {};
  document.querySelectorAll('main > * > *, section > * > *, [class*=grid] > *, [class*=cards] > *').forEach((c) => {
    if (c.className && typeof c.className === 'string') cardCounts[c.className] = (cardCounts[c.className] || 0) + 1;
  });
  const cards = Math.max(0, ...Object.values(cardCounts).filter((n) => n >= 3));
  const hero = !!(h1 && visible(h1) && h1.getBoundingClientRect().top < 900 && parseFloat(getComputedStyle(h1).fontSize) >= 32);
  const signals = {
    forms: document.forms.length,
    has_nav: !!document.querySelector('nav,[role=navigation]'),
    has_sidebar: !!document.querySelector('aside,[role=complementary]'),
    has_price: /(\$|€|£|₫|VND|USD)\s?\d|\d\s?(\$|€|£|₫)|\/\s?(mo|month|year|tháng|năm)\b|per (month|year)/i.test(body),
    has_cart: /(add to cart|add to bag|giỏ hàng|shopping cart|view cart)/i.test(body),
    sections: document.querySelectorAll('section').length,
    big_input: bigInputs,
    interactive: elements.length,
    canvas: document.querySelectorAll('canvas').length,
    text_length: body.length,
  };
  const layout = {
    hero, sidebar: signals.has_sidebar, tables: document.querySelectorAll('table').length,
    forms: signals.forms, cards, images: document.querySelectorAll('img').length,
    video: document.querySelectorAll('video').length, canvas: signals.canvas,
    big_input: bigInputs > 0, sections: signals.sections,
  };
  return {
    title: document.title,
    meta_description: (document.querySelector('meta[name=description]') || {}).content || '',
    og_description: (document.querySelector('meta[property="og:description"]') || {}).content || '',
    elements, headings, texts, signals, layout, anchors,
  };
}
"""


def settle(page: Page) -> None:
    """Wait until the page is reasonably stable (SPAs keep requests open, so networkidle is best-effort)."""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10_000)
        page.wait_for_load_state("networkidle", timeout=3_000)
    except Exception:
        pass
    page.wait_for_timeout(400)


def pick_elements(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep at most MAX_ELEMENTS, preferring main content, then restore document order."""
    ranked = sorted(raw, key=lambda e: (REGION_PRIORITY.get(e["region"], 4), e["index"]))
    kept = sorted(ranked[:MAX_ELEMENTS], key=lambda e: e["index"])
    return kept


def accessible_names(page: Page) -> dict[int, str]:
    """Accessible name per tagged element (data-svai-i), as computed by the browser itself.

    One DOM call + one accessibility-tree call over CDP. Unlike innerText this includes
    aria-label, labels and generated (::before/::after) content.
    """
    cdp = page.context.new_cdp_session(page)
    try:
        cdp.send("DOM.enable")
        cdp.send("Accessibility.enable")
        doc = cdp.send("DOM.getFlattenedDocument", {"depth": -1})
        by_backend: dict[int, int] = {}
        for node in doc["nodes"]:
            attrs = node.get("attributes") or []
            tagged = dict(zip(attrs[0::2], attrs[1::2], strict=False)).get("data-svai-i")
            if tagged is not None:
                by_backend[node["backendNodeId"]] = int(tagged)
        names: dict[int, str] = {}
        for node in cdp.send("Accessibility.getFullAXTree")["nodes"]:
            index = by_backend.get(node.get("backendDOMNodeId", -1))
            name = (node.get("name") or {}).get("value") or ""
            if index is not None and name and not node.get("ignored"):
                names[index] = " ".join(name.split())[:120]
        return names
    except Exception:
        return {}  # fall back to the DOM-derived names
    finally:
        try:
            cdp.detach()
        except Exception:
            pass


def build_elements(
    raw: list[dict[str, Any]], ax_names: dict[int, str] | None = None
) -> list[Element]:
    ax_names = ax_names or {}
    elements: list[Element] = []
    for i, e in enumerate(pick_elements(raw), start=1):
        role = e["role"]
        name = ax_names.get(e["index"]) or e["name"]
        stable = e["selector"]
        x, y, w, h = e["bbox"]
        spec = LocatorSpec(
            role=None if role == "file" else role,
            name=name or None,
            text=e["text"] or None,
            css=stable or e["query"],
            nth=None if stable else e["nth"],
            tag=e["tag"],
            fingerprint=e["fingerprint"],
            bbox=Bbox(x=x, y=y, w=w, h=h),
        )
        elements.append(
            Element(
                ref=f"e{i}",
                role=role,
                name=name,
                region=e["region"],
                tag=e["tag"],
                text=e["text"],
                href=e["href"],
                selector=stable,
                locator=spec,
                input_type=e["input_type"],
                button_type=e["button_type"],
                accept=e["accept"],
                in_form=e["in_form"],
                form=FormData(**e["form"]) if e["form"] else None,
                caps=e["caps"],
            )
        )
    return elements


def describe_layout(layout: dict[str, Any]) -> str:
    """Vietnamese one-line layout description derived from the DOM (stand-in for a screenshot)."""
    parts = []
    if layout.get("hero"):
        parts.append("có khối hero lớn (H1 nổi bật ở đầu trang)")
    if layout.get("sidebar"):
        parts.append("có sidebar/menu bên")
    for key, label in (
        ("tables", "bảng"),
        ("forms", "form"),
        ("cards", "card lặp lại"),
        ("images", "ảnh"),
    ):
        if layout.get(key):
            parts.append(f"{layout[key]} {label}")
    if layout.get("video"):
        parts.append("có video")
    if layout.get("canvas"):
        parts.append("có vùng canvas (trình soạn thảo/đồ họa)")
    if layout.get("big_input"):
        parts.append("có ô nhập/thả file lớn ở khu vực chính")
    if layout.get("sections"):
        parts.append(f"{layout['sections']} section")
    return "; ".join(parts) or "trang đơn giản"


def extract_page(
    page: Page, n: int, out_dir: Path, *, depth: int = 0, score: float = 0.0
) -> PageData:
    """Extract one loaded page; writes pages/<n>.json and pages/<n>.png under out_dir."""
    settle(page)
    raw = page.evaluate(EXTRACT_JS)
    ax_names = accessible_names(page)
    page.evaluate(
        "document.querySelectorAll('[data-svai-i]').forEach((e) => e.removeAttribute('data-svai-i'))"
    )
    pages_dir = out_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    screenshot = pages_dir / f"{n}.png"
    try:
        page.screenshot(path=str(screenshot))
    except Exception:
        screenshot = None  # type: ignore[assignment]
    data = PageData(
        n=n,
        url=page.url,
        title=raw["title"],
        meta_description=raw["meta_description"],
        og_description=raw["og_description"],
        headings=[Heading(**h) for h in raw["headings"]],
        key_texts=raw["texts"],
        elements=build_elements(raw["elements"], ax_names),
        anchors=[Anchor(**a) for a in raw["anchors"]],
        signals=raw["signals"],
        layout=raw["layout"],
        screenshot=str(screenshot) if screenshot else None,
        depth=depth,
        score=score,
    )
    (pages_dir / f"{n}.json").write_text(
        json.dumps(data.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return data
