"""Request guard: stops the explorer from changing data on the target site.

Rules (see decide()): PUT/PATCH/DELETE and document POSTs (form submits) are always blocked.
Other POSTs pass only for GraphQL queries, telemetry/font calls (fake 204),
or read-like paths (search|query|list|filter|graphql without create|update|delete|save|...).
"""

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

Verdict = Literal["continue", "abort", "fake_204"]

ALWAYS_BLOCKED = {"PUT", "PATCH", "DELETE"}
READ_PATH = re.compile(r"search|query|list|filter|graphql", re.I)
WRITE_PATH = re.compile(r"create|update|delete|save|submit|send|pay|checkout", re.I)
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

    def _is_main_domain(self, url: str) -> bool:
        host, root = _host(url), _host(self.root_url)
        return host == root or host.endswith("." + root)

    def decide(
        self, method: str, url: str, resource_type: str, post_data: str | None
    ) -> tuple[Verdict, str]:
        """Return (verdict, rule) for one request."""
        method = method.upper()
        if method in {"GET", "HEAD", "OPTIONS"}:
            return "continue", "read"
        if method in ALWAYS_BLOCKED:
            return "abort", f"method_{method.lower()}"
        # POST from here on
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
            "first_blocked_urls": self.blocked_urls,
            "first_passed_urls": self.passed_urls,
        }
