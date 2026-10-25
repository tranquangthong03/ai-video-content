"""Blur personal data on pages seen with a signed-in session (videos and screenshots are public).

An init script, installed in every context of a BrowserSession that holds a session:
  * text that looks like an e-mail address or a phone number is wrapped in a span with
    filter: blur(6px) (Vietnamese and international numbers of 9+ digits)
  * account / avatar / profile / user-menu controls inside a header or nav are blurred as a whole
  * inputs whose value is an e-mail or a phone number are blurred
A MutationObserver applies it again whenever the page changes (after every click, typing,
navigation inside a single-page app). The wrapping never changes the text (innerText stays the same).
"""

import os

# BLUR_PERSONAL_DATA: "auto" (default: only when a session is held), "1" (always), "0" (never)
ENV_VAR = "BLUR_PERSONAL_DATA"

EMAIL_RE = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
PHONE_RE = r"(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{1,4}\)[\s.-]?)?\d{2,4}(?:[\s.-]?\d{2,4}){2,4}"

BLUR_JS = """
(() => {
  const BLUR = 'blur(6px)';
  const EMAIL = new RegExp('%EMAIL%', 'g');
  const PHONE = new RegExp('(?<![\\\\w@])%PHONE%(?![\\\\w@])', 'g');
  const AREA = /avatar|account|profile|user-?menu|user-?dropdown|user-?name|user-?info/i;
  const digits = (s) => (s.match(/\\d/g) || []).length;
  const isPhone = (s) => digits(s) >= 9 && digits(s) <= 15 && /^[+0(]/.test(s.trim());
  const blur = (el) => { el.style.setProperty('filter', BLUR, 'important'); el.dataset.piiBlur = '1'; };

  const wrapText = (node) => {
    const text = node.nodeValue;
    const hits = [];
    for (const re of [EMAIL, PHONE]) {
      re.lastIndex = 0;
      let m;
      while ((m = re.exec(text))) {
        if (re === PHONE && !isPhone(m[0])) continue;
        hits.push([m.index, m.index + m[0].length]);
      }
    }
    if (!hits.length) return;
    hits.sort((a, b) => a[0] - b[0]);
    const frag = document.createDocumentFragment();
    let at = 0;
    for (const [from, to] of hits) {
      if (from < at) continue;
      frag.append(text.slice(at, from));
      const span = document.createElement('span');
      span.textContent = text.slice(from, to);
      blur(span);
      frag.append(span);
      at = to;
    }
    frag.append(text.slice(at));
    node.replaceWith(frag);
  };

  const scan = () => {
    if (!document.body) return;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => {
        const p = n.parentElement;
        if (!p || p.dataset.piiBlur || ['SCRIPT', 'STYLE', 'TEXTAREA', 'NOSCRIPT'].includes(p.tagName)) {
          return NodeFilter.FILTER_REJECT;
        }
        return n.nodeValue.length > 4 ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      },
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(wrapText);
    for (const el of document.querySelectorAll('header *, [role=banner] *, nav *')) {
      const mark = (el.getAttribute('aria-label') || '') + ' ' + (el.className && el.className.toString());
      if (AREA.test(mark) && !el.dataset.piiBlur) blur(el);
    }
    for (const input of document.querySelectorAll('input, textarea')) {
      const v = input.value || '';
      if (v && (new RegExp('^' + '%EMAIL%' + '$').test(v) || isPhone(v))) blur(input);
    }
  };

  let queued = false;
  const later = () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; scan(); });
  };
  window.__pii_scan = scan;
  const start = () => {
    scan();
    new MutationObserver(later).observe(document.documentElement, {
      subtree: true, childList: true, characterData: true,
    });
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
""".replace("%EMAIL%", EMAIL_RE.replace("\\", "\\\\")).replace(
    "%PHONE%", PHONE_RE.replace("\\", "\\\\")
)


def blur_enabled(has_session: bool, env: dict[str, str] | None = None) -> bool:
    """Whether to blur: BLUR_PERSONAL_DATA=1 always, 0 never, otherwise when a session is held."""
    value = (env if env is not None else os.environ).get(ENV_VAR, "auto").strip().lower()
    if value in ("1", "true", "on", "yes"):
        return True
    if value in ("0", "false", "off", "no"):
        return False
    return has_session
