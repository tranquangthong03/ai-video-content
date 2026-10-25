"""Sites many people share (public demo instances): the system must never write data on them."""

import os
from collections.abc import Mapping
from urllib.parse import urlparse

DEFAULT_SHARED_DEMO_SITES = ("opensource-demo.orangehrmlive.com",)


def shared_demo_sites(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """The built-in list plus SHARED_DEMO_SITES (comma-separated hosts) from the environment."""
    raw = (os.environ if env is None else env).get("SHARED_DEMO_SITES", "")
    extra = tuple(h.strip().lower().removeprefix("www.") for h in raw.split(",") if h.strip())
    return (*DEFAULT_SHARED_DEMO_SITES, *extra)


def is_shared_demo(url: str, env: Mapping[str, str] | None = None) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return any(host == site or host.endswith("." + site) for site in shared_demo_sites(env))


SHARED_DEMO_REASON = (
    "Đây là site demo dùng chung nhiều người; hệ thống không tạo hoặc sửa dữ liệu trên đó."
)
