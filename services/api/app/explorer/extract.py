"""Page extraction: headings, key texts, interactive elements with short stable refs, signals, screenshot."""

import json
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from app.explorer.models import Element, Heading, PageData

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
  const stableId = (id) => /^[A-Za-z][\w-]{1,40}$/.test(id) && !/\d{4,}/.test(id) && !/^(r|:r)/.test(id) && !/radix|headlessui/i.test(id);
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

  const sel = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=link], ' +
    '[role=tab], [role=menuitem], [role=checkbox], [role=switch], [role=option], [contenteditable=""], ' +
    '[contenteditable=true], [onclick]';
  const seen = new Set();
  const elements = [];
  document.querySelectorAll(sel).forEach((el, index) => {
    if (seen.has(el) || elements.length >= 600 || !visible(el)) return;
    seen.add(el);
    const name = nameOf(el);
    const role = roleOf(el);
    if (!name && !['textbox', 'searchbox', 'checkbox', 'file'].includes(role)) return;
    const r = el.getBoundingClientRect();
    elements.push({
      index, role, name, region: regionOf(el), tag: el.tagName.toLowerCase(),
      href: el.tagName === 'A' ? el.href : null,
      selector: selectorOf(el),
      input_type: el.tagName === 'INPUT' ? (el.type || 'text') : null,
      button_type: el.tagName === 'BUTTON' ? (el.getAttribute('type') || 'submit') : null,
      in_form: !!el.closest('form'),
      bbox: [Math.round(r.x), Math.round(r.y + scrollY), Math.round(r.width), Math.round(r.height)],
    });
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
    elements, headings, texts, signals, layout,
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


def build_elements(raw: list[dict[str, Any]]) -> list[Element]:
    elements: list[Element] = []
    for i, e in enumerate(pick_elements(raw), start=1):
        role = e["role"]
        elements.append(
            Element(
                ref=f"e{i}",
                role=role,
                name=e["name"],
                region=e["region"],
                tag=e["tag"],
                href=e["href"],
                selector=e["selector"],
                locator_role=None if role == "file" else role,
                locator_name=e["name"] or None,
                input_type=e["input_type"],
                button_type=e["button_type"],
                in_form=e["in_form"],
                bbox=tuple(e["bbox"]),  # type: ignore[arg-type]
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
        elements=build_elements(raw["elements"]),
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
