"""Request guard: stops the explorer from changing data on the target site.

While a sign-in is being performed (allow_login_posts) POSTs to the site's own domain and to a
few well-known authentication providers pass too; nothing else does.

Rules (see decide()): PUT/PATCH/DELETE and document POSTs (form submits) are always blocked.
Other POSTs pass only for GraphQL queries, telemetry/font calls (fake 204),
or read-like paths (search|query|list|filter|graphql without create|update|delete|save|...).

Inside allow_writes() (a core flow whose submit policy is "allow") POST/PUT/PATCH to the site's
own domain pass too, except paths that delete, pay, invite or send. At most MAX_WRITE_WINDOWS
windows per guard, never on a shared demo site; every write request is listed in the report.
"""

import json
import re
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

from app.core.shared_demo import is_shared_demo

Verdict = Literal["continue", "abort", "fake_204"]

ALWAYS_BLOCKED = {"PUT", "PATCH", "DELETE"}
READ_PATH = re.compile(r"search|query|list|filter|graphql", re.I)
WRITE_PATH = re.compile(r"create|update|delete|save|submit|send|pay|checkout", re.I)
# Never let through, even while writes are allowed: destructive, payment, people, outgoing mail
FORBIDDEN_WRITE_PATH = re.compile(
    r"delete|remove|destroy|pay|checkout|billing|subscri|invite|share|send|message|mail|notify|"
    r"upgrade|logout|signout|sign-out|log-out",
    re.I,
)
WRITE_METHODS = {"POST", "PUT", "PATCH"}
MAX_WRITE_WINDOWS = 2


class WritesNotAllowed(RuntimeError):
    """allow_writes() was refused (shared demo site, or the windows are used up)."""


TELEMETRY_HOSTS = (
    "google-analytics.com",
    "googletagmanager.com",
    "doubleclick.net",
    "segment.io",
    "segment.com",
    "mixpanel.com",
    "amplitude.com",
    "hotjar.com",
    "hotjar.io",
    "sentry.io",
    "datadoghq.com",
    "fullstory.com",
    "clarity.ms",
    "cloudflareinsights.com",
    "facebook.com",
    "facebook.net",
    "linkedin.com",
    "intercom.io",
    "hs-analytics.net",
    "hubspot.com",
    "m.stripe.com",
    "posthog.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "use.typekit.net",
    "bat.bing.com",
)


def _is_graphql_query(body: Any) -> bool:
    items = body if isinstance(body, list) else [body]
    if not items:
        return False
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("query"), str):
            return False
        text = item["query"].lstrip()
        if text.startswith(("mutation", "subscription")) or re.search(r"\bmutation\b", text):
            return False  # even with operationName we cannot tell which operation runs
    return True


# Identity providers a site's own sign-in form may post to (host suffix; supabase only under /auth/)
AUTH_PROVIDERS = (
    "auth0.com",
    "clerk.com",
    "clerk.accounts.dev",
    "amazoncognito.com",
    "firebaseapp.com",
    "identitytoolkit.googleapis.com",
    "securetoken.googleapis.com",
    "okta.com",
    "supabase.co",
)
AUTH_SUBDOMAINS = ("auth", "login", "accounts", "sso", "id", "signin")
SECOND_LEVEL = {"com", "co", "org", "net", "gov", "edu", "ac"}


def registrable(host: str) -> str:
    """example.com for app.example.com; example.com.vn for app.example.com.vn."""
    labels = host.split(".")
    if len(labels) >= 3 and labels[-2] in SECOND_LEVEL and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").removeprefix("www.")


@dataclass
class RequestGuard:
    root_url: str
    allow_mutations: bool = False
    counts: Counter[str] = field(default_factory=Counter)
    blocked_urls: list[str] = field(default_factory=list)
    # first URLs let through / faked per rule, so the report can be audited for wrong passes
    passed_urls: dict[str, list[str]] = field(default_factory=dict)
    login_phase: bool = False
    login_hosts: Counter[str] = field(default_factory=Counter)  # POSTs let through while signing in
    login_blocked_hosts: Counter[str] = field(default_factory=Counter)  # and the ones refused
    write_phase: bool = False
    write_windows: int = 0
    write_log: list[str] = field(default_factory=list)  # every write request let through

    def _is_main_domain(self, url: str) -> bool:
        host, root = _host(url), _host(self.root_url)
        return host == root or host.endswith("." + root)

    @contextmanager
    def allow_login_posts(self) -> Iterator[None]:
        """Within this block the sign-in's own POSTs pass (see login_post_allowed)."""
        self.login_phase = True
        try:
            yield
        finally:
            self.login_phase = False

    @contextmanager
    def allow_writes(self) -> Iterator[None]:
        """Within this block the flow's own writes pass (see decide); refused on shared demos."""
        if is_shared_demo(self.root_url):
            raise WritesNotAllowed("shared demo site")
        if self.write_windows >= MAX_WRITE_WINDOWS:
            raise WritesNotAllowed(f"at most {MAX_WRITE_WINDOWS} submits per flow")
        self.write_windows += 1
        self.write_phase = True
        try:
            yield
        finally:
            self.write_phase = False

    def login_post_allowed(self, url: str) -> bool:
        host, root = _host(url), _host(self.root_url)
        if (
            self._is_main_domain(url)
            or registrable(host) == registrable(root)
            and (host == registrable(root) or host.split(".")[0] in AUTH_SUBDOMAINS)
        ):
            return True
        for provider in AUTH_PROVIDERS:
            if host == provider or host.endswith("." + provider):
                return provider != "supabase.co" or "/auth/" in urlparse(url).path
        return False

    def decide(
        self, method: str, url: str, resource_type: str, post_data: str | None
    ) -> tuple[Verdict, str]:
        """Return (verdict, rule) for one request."""
        method = method.upper()
        if method in {"GET", "HEAD", "OPTIONS"}:
            return "continue", "read"
        if (
            self.write_phase
            and method in WRITE_METHODS
            and self._is_main_domain(url)
            and not FORBIDDEN_WRITE_PATH.search(urlparse(url).path)
        ):
            return "continue", "flow_write"
        if method in ALWAYS_BLOCKED:
            return "abort", f"method_{method.lower()}"
        # POST from here on
        if self.login_phase:
            if self.login_post_allowed(url):
                self.login_hosts[_host(url)] += 1
                return "continue", "login_post"
            self.login_blocked_hosts[_host(url)] += 1
        if resource_type == "document":
            return "abort", "document_post"
        body: Any = None
        if post_data:
            try:
                body = json.loads(post_data)
            except ValueError:
                body = None
        if body is not None and _is_graphql_query(body):
            return "continue", "graphql_query"
        host = _host(url)
        if not self._is_main_domain(url) and any(host.endswith(t) for t in TELEMETRY_HOSTS):
            return "fake_204", "telemetry"
        path = urlparse(url).path
        if READ_PATH.search(path) and not WRITE_PATH.search(path):
            return "continue", "read_path"
        return "abort", "post_default"

    def handle(self, route: Any) -> None:
        """Playwright route handler."""
        request = route.request
        verdict, rule = self.decide(
            request.method, request.url, request.resource_type, request.post_data
        )
        if rule == "read":  # plain GET/HEAD/OPTIONS: not counted
            route.continue_()
        elif self.allow_mutations or verdict == "continue":
            self.counts[f"allowed:{rule}"] += 1
            self._remember(f"allowed:{rule}", request)
            if rule == "flow_write":
                self.write_log.append(f"{request.method} {request.url[:200]}")
            route.continue_()
        elif verdict == "fake_204":
            self.counts[f"faked_204:{rule}"] += 1
            self._remember(f"faked_204:{rule}", request)
            route.fulfill(status=204, body="")
        else:
            self.counts[f"blocked:{rule}"] += 1
            if len(self.blocked_urls) < 10:
                self.blocked_urls.append(f"{request.method} {request.url[:200]}")
            route.abort("blockedbyclient")

    def _remember(self, key: str, request: Any) -> None:
        urls = self.passed_urls.setdefault(key, [])
        if len(urls) < 10:
            urls.append(f"{request.method} {request.url[:200]}")

    def report(self) -> dict[str, Any]:
        grouped: dict[str, dict[str, int]] = {"blocked": {}, "allowed": {}, "faked_204": {}}
        for key, n in self.counts.items():
            kind, _, rule = key.partition(":")
            grouped[kind][rule] = n
        return {
            "allow_mutations": self.allow_mutations,
            **grouped,
            "login_phase": {
                "posts_allowed": dict(self.login_hosts),
                "hosts_refused": dict(self.login_blocked_hosts),
            },
            "writes": {"windows": self.write_windows, "requests": self.write_log[:20]},
            "first_blocked_urls": self.blocked_urls,
            "first_passed_urls": self.passed_urls,
        }
