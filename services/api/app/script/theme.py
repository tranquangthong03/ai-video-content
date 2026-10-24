"""Theme of the video, derived from the site itself (no explorer data needed).

Primary color, in order of preference:
  a) <meta name="theme-color"> unless it is white, black or grey;
  b) brand colors from CSS: computed background of buttons / primary / CTA elements plus the
     color of nav links, neutral and page-background colors dropped, the color with the largest
     visible area wins;
  c) the most prominent saturated color in the top of the home page screenshot, ignoring images;
  d) fallback #4F46E5.
`highlight_color` mirrors apps/render/src/color.ts (highlightColor): keep the two in step.
"""

import colorsys
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image
from playwright.sync_api import Page

from app.browser.page_utils import dismiss_cookie_banner, wait_for_settle
from app.browser.session import BrowserSession
from app.schemas.generated.theme import Theme

FALLBACK_PRIMARY = "#4F46E5"
TEMPLATE_BG = "#0B1426"
MIN_CONTRAST = 4.5
PAGE_TIMEOUT_MS = 15_000
MIN_SATURATION = 0.2
SCREENSHOT_MIN_SATURATION = 0.35
MIN_AREA_SHARE = 0.02  # a screenshot color must cover at least 2% of the examined area
LOGO_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg", ".webp"}

# --- color math ----------------------------------------------------------------------------------

Rgb = tuple[int, int, int]


def hex_to_rgb(value: str) -> Rgb:
    h = value.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(v))):02x}" for v in rgb)


def parse_css_color(value: str | None) -> tuple[Rgb, float] | None:
    """(rgb, alpha) of a CSS color as returned by getComputedStyle or a meta tag, else None."""
    if not value:
        return None
    text = value.strip().lower()
    m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", text)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return hex_to_rgb("#" + h), 1.0
    m = re.fullmatch(
        r"rgba?\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)", text
    )
    if not m:
        return None
    alpha = 1.0
    if m.group(4):
        a = m.group(4)
        alpha = float(a[:-1]) / 100 if a.endswith("%") else float(a)
    r, g, b = (round(float(m.group(i))) for i in (1, 2, 3))
    return (r, g, b), alpha


def hls(rgb: Rgb) -> tuple[float, float, float]:
    """(hue 0..1, lightness, saturation) as colorsys defines them."""
    return colorsys.rgb_to_hls(*(v / 255 for v in rgb))


def saturation(rgb: Rgb) -> float:
    _, lightness, sat = hls(rgb)
    return 0.0 if lightness in (0.0, 1.0) else sat


def is_neutral(rgb: Rgb) -> bool:
    """White, black, grey and near-white/near-black tints: not a brand color."""
    _, lightness, sat = hls(rgb)
    return sat < MIN_SATURATION or lightness > 0.94 or lightness < 0.06


def color_distance(a: Rgb, b: Rgb) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5


def luminance(value: str) -> float:
    def lin(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(v) for v in hex_to_rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def highlight_color(primary: str, bg: str = TEMPLATE_BG, min_ratio: float = MIN_CONTRAST) -> str:
    """The primary lightened (same hue) until it reads on the template background at min_ratio."""
    start = primary.lower()
    if contrast_ratio(start, bg) >= min_ratio:
        return start
    h, lightness, sat = colorsys.rgb_to_hls(*(v / 255 for v in hex_to_rgb(start)))
    for step in range(1, 101):
        candidate = min(1.0, lightness + step * 0.01)
        out = rgb_to_hex(tuple(v * 255 for v in colorsys.hls_to_rgb(h, candidate, sat)))
        if contrast_ratio(out, bg) >= min_ratio:
            return out
        if candidate >= 1.0:
            break
    return "#ffffff"


def opposite_hue(primary: str) -> str:
    """Accent when the site has no second brand color: the opposite hue, bright enough to pop."""
    h, _, s = hls(hex_to_rgb(primary))
    rgb = colorsys.hls_to_rgb((h + 0.5) % 1.0, 0.55, max(s, 0.65))
    return rgb_to_hex(tuple(v * 255 for v in rgb))


def hue_gap(a: Rgb, b: Rgb) -> float:
    d = abs(hls(a)[0] - hls(b)[0]) * 360
    return min(d, 360 - d)


# --- extraction from the live page ----------------------------------------------------------------

BRAND_JS = r"""
() => {
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return null;
    const w = Math.max(0, Math.min(r.right, innerWidth) - Math.max(r.left, 0));
    const h = Math.max(0, Math.min(r.bottom, innerHeight * 2) - Math.max(r.top, 0));
    return w > 6 && h > 6 ? { area: w * h, top: r.top } : null;
  };
  const out = { buttons: [], links: [], page_bg: [], media: [], icons: [], logos: [], meta: null };
  const meta = document.querySelector('meta[name="theme-color"]');
  out.meta = meta ? meta.getAttribute('content') : null;
  for (const el of document.querySelectorAll(
    'button, a[role=button], input[type=submit], [class*=primary], [class*=btn], ' +
    '[class*=cta], a[class*=button]')) {
    const v = vis(el); if (!v) continue;
    out.buttons.push({ color: getComputedStyle(el).backgroundColor, area: v.area });
  }
  for (const el of document.querySelectorAll('nav a, header a')) {
    const v = vis(el); if (!v) continue;
    out.links.push({ color: getComputedStyle(el).color, area: v.area });
  }
  for (const el of [document.documentElement, document.body]) {
    if (el) out.page_bg.push(getComputedStyle(el).backgroundColor);
  }
  for (const el of document.querySelectorAll('img, picture, video, canvas, svg')) {
    const r = el.getBoundingClientRect();
    if (r.width * r.height > 40000) {
      out.media.push({ x: r.left, y: r.top, w: r.width, h: r.height });
    }
  }
  for (const l of document.querySelectorAll('link[rel~=icon], link[rel=apple-touch-icon]')) {
    out.icons.push({ href: l.href, rel: l.getAttribute('rel'), sizes: l.getAttribute('sizes') });
  }
  for (const img of document.querySelectorAll('header img, nav img')) {
    const cls = typeof img.className === 'string' ? img.className : '';
    const hint = [img.alt, cls, img.src].join(' ').toLowerCase();
    if (hint.includes('logo') && img.src) out.logos.push(img.currentSrc || img.src);
  }
  return out;
}
"""


@dataclass
class ThemeResult:
    theme: Theme
    source: str  # meta | css | screenshot | fallback
    accent_source: str  # css | opposite_hue
    logo_path: Path | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def report(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "primary": self.theme.primary,
            "accent": self.theme.accent,
            "accent_source": self.accent_source,
            "highlight": highlight_color(self.theme.primary),
            "logo": str(self.logo_path) if self.logo_path else None,
            "candidates": self.candidates[:5],
            "notes": self.notes,
        }


def _key(rgb: Rgb) -> Rgb:
    """Group near-identical shades: 16 levels per channel."""
    return tuple((v // 16) * 16 + 8 for v in rgb)  # type: ignore[return-value]


def rank_css_colors(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Brand colors from the extracted CSS data, best first: [{color, area}], neutrals and the page
    background removed, shades grouped, area summed (nav link text counts for a third)."""
    page_bg = [c[0] for c in (parse_css_color(v) for v in data.get("page_bg", [])) if c]
    totals: dict[Rgb, float] = {}
    exemplar: dict[Rgb, Rgb] = {}
    for kind, weight in (("buttons", 1.0), ("links", 0.33)):
        for item in data.get(kind, []):
            parsed = parse_css_color(item.get("color"))
            if not parsed or parsed[1] < 0.5:
                continue
            rgb = parsed[0]
            if is_neutral(rgb) or any(color_distance(rgb, bg) < 40 for bg in page_bg):
                continue
            k = _key(rgb)
            totals[k] = totals.get(k, 0.0) + item["area"] * weight
            exemplar.setdefault(k, rgb)
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return [{"color": rgb_to_hex(exemplar[k]), "area": round(area)} for k, area in ranked]


def dominant_from_image(
    image: Image.Image,
    viewport: tuple[int, int],
    exclude: list[dict[str, float]],
    *,
    top_share: float = 0.4,
) -> str | None:
    """Most prominent saturated color in the top part of a page screenshot, ignoring media boxes.

    `exclude` boxes are in viewport pixels and are scaled to the image. Colors are quantized
    (16 levels per channel); neutrals and the background (the most common color) are skipped.
    """
    img = image.convert("RGB")
    width, height = img.size
    sx, sy = width / viewport[0], height / viewport[1]
    limit = int(height * top_share)
    blocked = [
        (
            int(b["x"] * sx),
            int(b["y"] * sy),
            int((b["x"] + b["w"]) * sx),
            int((b["y"] + b["h"]) * sy),
        )
        for b in exclude
    ]
    pixels = img.load()
    step = 3
    # the page background is the most common color of the whole screenshot, not of the header
    page_counts: dict[Rgb, int] = {}
    for y in range(0, height, step * 2):
        for x in range(0, width, step * 2):
            k = _key(pixels[x, y])  # type: ignore[index]
            page_counts[k] = page_counts.get(k, 0) + 1
    background = max(page_counts, key=lambda k: page_counts[k])
    counts: dict[Rgb, int] = {}
    total = 0
    for y in range(0, limit, step):
        for x in range(0, width, step):
            if any(x0 <= x < x1 and y0 <= y < y1 for x0, y0, x1, y1 in blocked):
                continue
            k = _key(pixels[x, y])  # type: ignore[index]
            counts[k] = counts.get(k, 0) + 1
            total += 1
    best: tuple[int, Rgb] | None = None
    for k, n in counts.items():
        if k == background or is_neutral(k) or color_distance(k, background) < 40:
            continue
        if saturation(k) < SCREENSHOT_MIN_SATURATION or n < total * MIN_AREA_SHARE:
            continue  # anti-aliased text edges and thin accents are not a brand color
        if best is None or n > best[0]:
            best = (n, k)
    return rgb_to_hex(best[1]) if best else None


def _meta_color(value: str | None) -> str | None:
    parsed = parse_css_color(value)
    if not parsed or parsed[1] < 0.5 or is_neutral(parsed[0]):
        return None
    return rgb_to_hex(parsed[0])


def pick_accent(primary: str, ranked: list[dict[str, Any]]) -> tuple[str, str]:
    """Second CSS brand color with a clearly different hue, else the opposite hue."""
    p = hex_to_rgb(primary)
    for item in ranked:
        rgb = hex_to_rgb(item["color"])
        if hue_gap(p, rgb) >= 40 and not is_neutral(rgb):
            return item["color"], "css"
    return opposite_hue(primary), "opposite_hue"


def _download_logo(page: Page, data: dict[str, Any], out_dir: Path) -> Path | None:
    """First logo-like header image, else the apple-touch-icon/favicon (png/jpg/svg/webp only)."""
    urls: list[str] = list(data.get("logos", []))
    icons = sorted(data.get("icons", []), key=lambda i: 0 if "apple" in (i.get("rel") or "") else 1)
    urls += [i["href"] for i in icons]
    for url in urls:
        suffix = Path(url.split("?")[0]).suffix.lower()
        if suffix not in LOGO_SUFFIXES:
            continue
        try:
            response = page.context.request.get(url, timeout=5000)
            if not response.ok or len(response.body()) > 2_000_000:
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"logo{suffix}"
            path.write_bytes(response.body())
            return path
        except Exception:
            continue
    return None


def derive_theme(
    session: BrowserSession,
    url: str,
    out_dir: Path,
    *,
    screenshot: Path | None = None,
) -> ThemeResult:
    """Open `url` once (headless, request guard on, 15 s budget) and derive the Theme."""
    notes: list[str] = []
    data: dict[str, Any] = {}
    shot_image: Image.Image | None = None
    context = session.new_context()
    context.set_default_timeout(PAGE_TIMEOUT_MS)
    started = time.time()
    try:
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        dismiss_cookie_banner(page)
        wait_for_settle(
            page, timeout=min(3000, max(500, PAGE_TIMEOUT_MS - (time.time() - started) * 1000))
        )
        data = page.evaluate(BRAND_JS)
        logo = _download_logo(page, data, out_dir / "theme")
        if screenshot is not None and screenshot.is_file():
            shot_image = Image.open(screenshot)
        else:
            tmp = out_dir / "theme" / "home.png"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(tmp))
            shot_image = Image.open(tmp)
    except Exception as e:  # a dead site must not stop the pipeline: fall back to defaults
        notes.append(f"không mở lại được trang để lấy màu: {type(e).__name__}")
        logo = None
    finally:
        context.close()

    ranked = rank_css_colors(data) if data else []
    primary: str | None = None
    source = "fallback"
    meta = _meta_color(data.get("meta")) if data else None
    if meta:
        primary, source = meta, "meta"
    elif ranked:
        primary, source = ranked[0]["color"], "css"
    elif shot_image is not None:
        shot = dominant_from_image(shot_image, (1920, 1080), data.get("media", []) if data else [])
        if shot:
            primary, source = shot, "screenshot"
    if primary is None:
        primary = FALLBACK_PRIMARY
        notes.append("không tìm được màu thương hiệu, dùng màu mặc định")

    accent, accent_source = pick_accent(primary, ranked)
    theme = Theme(
        primary=primary.upper(),
        accent=accent.upper(),
        font="Be Vietnam Pro",
        logo_asset=str(logo) if logo else None,
        motion_preset="energetic",
        caption_style="karaoke",
        music_mood="upbeat",
        voice_id="vi_female_01",
        language="vi",
    )
    return ThemeResult(theme, source, accent_source, logo, ranked, notes)
