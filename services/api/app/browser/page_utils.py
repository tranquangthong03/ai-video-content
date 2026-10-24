"""Page-level helpers shared by every browser-driving module."""

import re
import time
from typing import Any

from playwright.sync_api import Page

from app.browser.blacklist import is_blocked

ACCEPT_BUTTON = re.compile(
    r"^\s*(accept( all)?( cookies)?|agree|i agree|allow all|got it|đồng ý|chấp nhận( tất cả)?)\s*$",
    re.I,
)
HIDE_COOKIE_CSS = (
    '[id*="cookie" i], [class*="cookie" i], [class*="consent" i] { display: none !important; }'
)
CAPTCHA_FRAMES = ("recaptcha", "hcaptcha", "challenges.cloudflare.com", "turnstile")
CHALLENGE_TITLES = ("just a moment", "attention required", "verify you are human", "captcha")


# Resolves when the DOM has been quiet for `quiet` ms and every <img> in the viewport is complete,
# or when `maxMs` has passed. Reports what it saw so callers can log it.
SETTLE_JS = """
([quiet, maxMs]) => new Promise((resolve) => {
  const start = performance.now();
  let last = start;
  const observer = new MutationObserver(() => { last = performance.now(); });
  observer.observe(document.documentElement, {
    subtree: true, childList: true, attributes: true, characterData: true,
  });
  const imagesReady = () => [...document.images].every((img) => {
    const r = img.getBoundingClientRect();
    const inView = r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth;
    return !inView || img.complete;
  });
  const tick = () => {
    const now = performance.now();
    const quietDom = now - last >= quiet, imgs = imagesReady();
    if ((quietDom && imgs) || now - start >= maxMs) {
      observer.disconnect();
      resolve({
        settled: quietDom && imgs, quiet_dom: quietDom, images: imgs,
        waited_ms: Math.round(now - start),
      });
    } else {
      setTimeout(tick, 50);
    }
  };
  tick();
})
"""


def wait_for_settle(page: Page, timeout: float = 3000, quiet_ms: int = 400) -> dict[str, Any]:
    """Wait until the page has stopped changing, within one shared time budget (ms).

    Settled means: the network is idle, the DOM saw no mutation for `quiet_ms` in a row, and
    every <img> in the viewport has loaded. Use it after every click/type/upload/Enter instead
    of a fixed sleep. Never raises: a page that never settles just returns after `timeout`.
    """
    started = time.monotonic()
    network_idle = True
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        network_idle = False
    remaining = max(quiet_ms + 100, timeout - (time.monotonic() - started) * 1000)
    try:
        result = page.evaluate(SETTLE_JS, [quiet_ms, remaining])
    except Exception:  # navigation destroyed the context while waiting: the page has changed anyway
        result = {"settled": False, "quiet_dom": False, "images": False, "waited_ms": 0}
    return {**result, "network_idle": network_idle}


def dismiss_cookie_banner(page: Page) -> bool:
    """Click an accept button if there is one; otherwise hide cookie/consent overlays with CSS."""
    try:
        for role in ("button", "link"):
            button = page.get_by_role(role, name=ACCEPT_BUTTON).first  # type: ignore[arg-type]
            if (
                button.count()
                and button.is_visible()
                and not is_blocked(button.inner_text(timeout=500))
            ):
                button.click(timeout=1500)
                page.wait_for_timeout(300)
                return True
    except Exception:  # banner handling must never break the crawl
        pass
    try:
        page.add_style_tag(content=HIDE_COOKIE_CSS)
    except Exception:
        pass
    return False


def detect_blockers(page: Page, status: int | None) -> dict[str, Any]:
    """{needs_login, captcha, http_error}: reasons the current page may not be explorable."""
    try:
        needs_login = page.locator("input[type=password]:visible").count() > 0
    except Exception:
        needs_login = False
    title = ""
    try:
        title = page.title().lower()
    except Exception:
        pass
    frames = any(any(k in (f.url or "") for k in CAPTCHA_FRAMES) for f in page.frames)
    captcha = frames or any(t in title for t in CHALLENGE_TITLES)
    return {
        "needs_login": needs_login,
        "captcha": captcha,
        "http_error": status if status is not None and status >= 400 else None,
    }
