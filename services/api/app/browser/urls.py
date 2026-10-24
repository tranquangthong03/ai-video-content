"""URL helpers shared by every module that crawls or drives a site."""

import re
from urllib.parse import parse_qsl, urldefrag, urlencode, urljoin, urlparse, urlunparse

SKIP_EXT = re.compile(
    r"\.(pdf|zip|png|jpe?g|gif|svg|webp|mp4|webm|mp3|css|js|json|xml|ico|woff2?|ttf)$", re.I
)
TRACKING = {"fbclid", "gclid", "ref", "source"}


def normalize_url(url: str, base: str | None = None, *, keep_anchor: bool = False) -> str | None:
    """Absolute URL without tracking params. Fragments are dropped except hash *routes*
    (`#/..`, `#!..`); with keep_anchor=True plain anchors like `#pricing` are kept too."""
    absolute = urljoin(base, url) if base else url
    parsed = urlparse(absolute)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    if SKIP_EXT.search(parsed.path):
        return None
    _, fragment = urldefrag(absolute)
    is_route = fragment.startswith(("/", "!"))
    keep = fragment if (is_route or (keep_anchor and fragment)) else ""
    query = urlencode(
        [
            (k, v)
            for k, v in parse_qsl(parsed.query)
            if not k.startswith("utm_") and k not in TRACKING
        ]
    )
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", query, keep))


def host(url: str) -> str:
    return (urlparse(url).hostname or "").removeprefix("www.")


def same_site(url: str, root: str) -> bool:
    return host(url) == host(root)


def _registrable(hostname: str) -> str:
    """Last two labels (plausible.io, example.com): good enough without a public-suffix list."""
    return ".".join(hostname.split(".")[-2:])


def related_domain(url: str, root: str) -> bool:
    """Same site or a subdomain of the same root domain (demo.plausible.io for plausible.io)."""
    return _registrable(host(url)) == _registrable(host(root))


def anchor_of(url: str) -> str | None:
    """The plain-anchor part of a link (`#pricing` -> `pricing`), None for hash routes."""
    fragment = urlparse(url).fragment
    return fragment if fragment and not fragment.startswith(("/", "!")) else None


def path_prefix(url: str) -> str | None:
    """Scope prefix for a start URL with a real path (`/examples/react/dist`), else None."""
    path = urlparse(url).path.rstrip("/")
    return path or None


def in_scope(url: str, root: str, prefix: str | None) -> bool:
    """Same site and, when the start URL has a path, under that path prefix."""
    if not same_site(url, root):
        return False
    if prefix is None:
        return True
    path = urlparse(url).path.rstrip("/")
    return path == prefix or path.startswith(prefix + "/")
