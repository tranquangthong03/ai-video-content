"""The request guard against the common kinds of API a page talks to (local servers, no real site).

Every kind has a read case (the data shows up) and a write case (the request never reaches the
server). The action that causes a request is announced like the Flow Agent does it.
"""

import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from playwright.sync_api import Page

from app.browser.session import BrowserSession
from app.browser.write_intent import action_trigger

PAGES = {
    # REST with names nobody can guess: POST /api/x on load lists, the same endpoint saves
    "rest": """<h1>Items</h1><p>Everything we sell, with prices, photos and delivery details.</p><ul id=list></ul>
<button id=save>Save</button>
<script>
const call = (b) => fetch('/api/x', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(b)}).then(r => r.json());
call({page: 1}).then(d => { list.innerHTML = d.items.map(i => '<li>' + i + '</li>').join(''); });
save.onclick = () => call({title: 'draft'}).then(() => { document.title = 'saved'; }).catch(() => { document.title = 'failed'; });
</script>""",
    "graphql": """<ul id=list></ul><button id=add>Add task</button>
<script>
const gql = (query) => fetch('/graphql', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({query})}).then(r => r.json());
gql('query Tasks { tasks { title } }').then(d => { list.innerHTML = d.items.map(i => '<li>' + i + '</li>').join(''); });
add.onclick = () => gql('mutation Add { addTask { id } }').catch(() => { document.title = 'failed'; });
</script>""",
    "rpc": """<ul id=list></ul><button id=del>Remove all</button>
<script>
const rpc = (method) => fetch('/rpc', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({jsonrpc:'2.0', method})}).then(r => r.json());
rpc('getItems').then(d => { list.innerHTML = d.items.map(i => '<li>' + i + '</li>').join(''); });
del.onclick = () => rpc('deleteItem').catch(() => { document.title = 'failed'; });
</script>""",
    "search": """<input id=q aria-label="Search products" type=search><ul id=list></ul>
<script>
q.oninput = () => fetch('/indexes/products/queries', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({requests:[{indexName:'p', params:'query=' + q.value}]})}).then(r => r.json()).then(d => { list.innerHTML = d.items.map(i => '<li>' + i + '</li>').join(''); });
</script>""",
    "button": """<h1>Items</h1><ul id=list></ul><nav><button id=show>Show</button></nav>
<script>
show.onclick = () => fetch('/api/x', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({page: 1})}).then(r => r.json()).then(d => { list.innerHTML = d.items.map(i => '<li>' + i + '</li>').join(''); }).catch(() => 0);
</script>""",
    "form": """<form id=f><input name=email value="a@b.io"><button id=go type=button>Join</button></form>
<script>
go.onclick = () => fetch('/api/x', {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body: 'email=a%40b.io'}).catch(() => { document.title = 'failed'; });
</script>""",
}


class Handler(BaseHTTPRequestHandler):
    posts: list[str] = []

    def do_GET(self) -> None:  # noqa: N802
        name = self.path.lstrip("/").split("?")[0]
        body = f"<!doctype html><html><head><title>t</title></head><body>{PAGES.get(name, '')}</body></html>"
        self._send(200, body, "text/html")

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        Handler.posts.append(f"{self.path} {self.rfile.read(length).decode()[:80]}")
        self._send(200, json.dumps({"items": ["alpha", "beta"]}), "application/json")

    def _send(self, status: int, body: str, ctype: str) -> None:
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture(scope="module")
def base() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def session(base: str) -> Iterator[BrowserSession]:
    with BrowserSession(base) as s:
        yield s


def open_page(session: BrowserSession, base: str, name: str) -> Page:
    Handler.posts.clear()
    session.guard.decisions.clear()
    session.guard.intents.clear()
    session.guard.blocked_log.clear()
    session.guard.last_action = None
    page = session.new_context().new_page()
    page.goto(f"{base}/{name}")
    page.wait_for_load_state("networkidle")
    return page


def press(
    session: BrowserSession, page: Page, selector: str, role: str, name: str, do: str = "click"
) -> None:
    session.guard.note_action(action_trigger(do, role, name), name)
    page.click(selector)
    page.wait_for_timeout(400)


def test_rest_with_a_hidden_name_reads_on_load_and_is_blocked_on_save(
    session: BrowserSession, base: str
) -> None:
    page = open_page(session, base, "rest")
    assert page.locator("#list li").count() == 2  # the list came through the guard
    assert session.guard.intents["read"] >= 1
    before = len(Handler.posts)
    press(session, page, "#save", "button", "Save")
    page.wait_for_timeout(300)
    assert len(Handler.posts) == before  # the save never reached the server
    assert page.title() == "failed"
    assert session.guard.intents["write"] == 1
    assert session.guard.recent_blocked(5)  # the blank-page check will see it


def test_the_same_endpoint_without_the_page_load_context_is_unknown_and_blocked(
    session: BrowserSession, base: str
) -> None:
    page = open_page(session, base, "rest")
    session.guard.last_action = None
    session.guard.clock = lambda: time.monotonic() + 100  # long after the page load: no known cause
    try:
        page.evaluate(
            "fetch('/api/x', {method:'POST', body: JSON.stringify({a: 1})}).catch(() => 0)"
        )
        page.wait_for_timeout(300)
    finally:
        session.guard.clock = time.monotonic
    assert session.guard.intents["unknown"] == 1


def test_graphql_query_reads_and_mutation_is_blocked(session: BrowserSession, base: str) -> None:
    page = open_page(session, base, "graphql")
    assert page.locator("#list li").count() == 2
    before = len(Handler.posts)
    press(session, page, "#add", "button", "Add task")
    assert len(Handler.posts) == before
    assert session.guard.intents["write"] == 1


def test_json_rpc_get_reads_and_delete_is_blocked(session: BrowserSession, base: str) -> None:
    page = open_page(session, base, "rpc")
    assert page.locator("#list li").count() == 2
    before = len(Handler.posts)
    press(session, page, "#del", "button", "Remove all")
    assert len(Handler.posts) == before
    assert session.guard.intents["write"] == 1


def test_search_service_post_passes_while_typing_in_the_search_box(
    session: BrowserSession, base: str
) -> None:
    page = open_page(session, base, "search")
    session.guard.note_action(action_trigger("type", "searchbox", "Search products"), "q")
    page.fill("#q", "lamp")
    page.wait_for_timeout(500)
    assert page.locator("#list li").count() == 2
    assert any(p.startswith("/indexes/products/queries") for p in Handler.posts)


def test_a_form_with_an_email_is_blocked(session: BrowserSession, base: str) -> None:
    page = open_page(session, base, "form")
    before = len(Handler.posts)
    press(session, page, "#go", "button", "Join")
    assert len(Handler.posts) == before
    assert session.guard.intents["write"] == 1
    decision = session.guard.decisions[-1]
    assert decision["verdict"] == "write" and decision["outcome"] == "blocked"


def test_a_blank_page_after_a_blocked_request_is_an_env_issue(
    session: BrowserSession, base: str
) -> None:
    """The endpoint has a name nobody can read and a plain button asked for it: blocked, so the
    list stays empty and the system says why."""
    from app.browser.env_issue import check_env_issue

    page = open_page(session, base, "button")
    events: list[dict[str, Any]] = []
    session.guard.sink = events.append
    since = session.guard.clock()
    try:
        press(session, page, "#show", "button", "Show")
        assert page.locator("#list li").count() == 0
        issue = check_env_issue(page, session.guard, since)
    finally:
        session.guard.sink = None
    assert issue is not None and issue["kind"] == "guard_broke_page"
    assert issue["blocked_urls"][0].endswith("/api/x") and issue["page_url"].endswith("/button")
    assert any(e.get("event") == "env_issue" for e in events)
    assert any(e.get("event") == "guard_decision" and e["verdict"] == "unknown" for e in events)


def test_a_page_with_content_is_not_an_env_issue_even_with_a_blocked_request(
    session: BrowserSession, base: str
) -> None:
    from app.browser.env_issue import check_env_issue

    page = open_page(session, base, "rest")  # the list loaded by itself
    since = session.guard.clock()
    press(session, page, "#save", "button", "Save")  # blocked, but the page still shows its list
    assert check_env_issue(page, session.guard, since) is None
