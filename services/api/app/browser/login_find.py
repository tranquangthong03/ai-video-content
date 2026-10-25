"""Where do I sign in? Find the login link of a public landing page.

pick_login_link is pure scoring; find_login_url wraps it with a headless browser.
"""

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from app.browser.blacklist import is_blocked
from app.browser.session import BrowserSession

SIGN_IN_TEXT = re.compile(r"\b(log\s?in|sign\s?in|login|signin)\b|đăng nhập", re.IGNORECASE)
APP_TEXT = re.compile(r"vào ứng dụng|go to app|open app|dashboard|launch app|bảng điều khiển", re.I)
SIGN_IN_HREF = re.compile(r"log-?in|sign-?in|signin|dang-?nhap", re.IGNORECASE)
APP_HREF = re.compile(r"(^|//)app\.|/app(/|$)|dashboard", re.IGNORECASE)
SIGN_UP = re.compile(
    r"sign\s?up|register|create (an )?account|đăng ký|get started|start free", re.I
)

LINKS_JS = """
() => [...document.querySelectorAll('a[href], button')].map((e) => ({
  text: (e.innerText || e.getAttribute('aria-label') || '').trim().slice(0, 60),
  href: e.href || e.getAttribute('data-href') || '',
})).filter((l) => l.text || l.href)
"""


def score(link: dict[str, Any]) -> int:
    text, href = link.get("text", ""), link.get("href", "")
    if SIGN_UP.search(text):
        return 0
    points = 0
    if SIGN_IN_TEXT.search(text):
        points += 3
    elif APP_TEXT.search(text):
        points += 1
    if SIGN_IN_HREF.search(href):
        points += 2
    elif APP_HREF.search(href):
        points += 1
    return points


def pick_login_link(links: list[dict[str, Any]], base_url: str) -> str | None:
    """The best link to the sign-in (or the app), as an absolute URL; None when nothing fits."""
    best: tuple[int, str] | None = None
    for link in links:
        href = link.get("href") or ""
        if not href or href.startswith(("javascript:", "mailto:", "#")):
            continue
        url = urljoin(base_url, href)
        if urlparse(url).scheme not in ("http", "https") or is_blocked(link.get("text", "")):
            continue
        points = score(link)
        if points and (best is None or points > best[0]):
            best = (points, url)
    return best[1] if best else None


def find_login_url(url: str) -> str | None:
    """Open `url` and look for its login link."""
    try:
        with BrowserSession(url) as session:
            context = session.new_context()
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(500)
            links = page.evaluate(LINKS_JS)
            context.close()
    except Exception:
        return None
    return pick_login_link(links, url)
