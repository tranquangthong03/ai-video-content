"""A small website with a sign-in, for the login tests (pages in tests/fixtures/site_auth).

/            public landing with a "Log in" link
/login       the form: mode "two_step" (email -> Next -> password), "one_step" or "otp"
             (password, then a one-time code)
/app         needs the cookie `sid`; a list, a "Create item" button, the user's email in the header
/app/settings, /app/billing   more pages behind the sign-in (sensitive); "Invite member" is a button
/api/me      401 without the cookie
/expire      (test helper) forgets every session: the cookies become stale
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

PAGES = Path(__file__).parent / "fixtures" / "site_auth"
EMAIL, PASSWORD, OTP = "demo@example.com", "secret-pass", "123456"


def page(name: str, **values: str) -> bytes:
    text = (PAGES / name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text.encode("utf-8")


class AuthSite(ThreadingHTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.mode = "two_step"
        self.sessions: set[str] = set()
        self.posts: list[str] = []  # "POST /path" of every form post
        self.hits: list[str] = []
        self.counter = 0

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def new_session(self) -> str:
        self.counter += 1
        sid = f"sid{self.counter}"
        self.sessions.add(sid)
        return sid


class Handler(BaseHTTPRequestHandler):
    server: AuthSite

    def log_message(self, *args: Any) -> None:
        pass

    # --- plumbing ------------------------------------------------------------------------
    def cookies(self) -> dict[str, str]:
        jar: SimpleCookie = SimpleCookie(self.headers.get("Cookie", ""))
        return {k: v.value for k, v in jar.items()}

    def signed_in(self) -> bool:
        return self.cookies().get("sid") in self.server.sessions

    def send(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, where: str, headers: dict[str, str] | None = None) -> None:
        self.send(302, b"", {"Location": where, **(headers or {})})

    def form(self) -> dict[str, str]:
        size = int(self.headers.get("Content-Length", 0) or 0)
        data = parse_qs(self.rfile.read(size).decode("utf-8")) if size else {}
        return {k: v[0] for k, v in data.items()}

    # --- routes --------------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        self.server.hits.append(url.path)
        path, query = url.path, parse_qs(url.query)
        if path == "/":
            return self.send(200, page("index.html"))
        if path == "/hidden-form":  # a landing that carries a sign-in form nobody can see
            hidden = b'<form style="display:none"><input type="password"></form>'
            return self.send(200, b"<html><body><h1>Welcome</h1>" + hidden + b"</body></html>")
        if path == "/login":
            if self.signed_in():
                return self.redirect("/app")
            step = (query.get("step") or ["1"])[0]
            error = (query.get("error") or [""])[0]
            err = f'<p class="error" role="alert">{error}</p>' if error else ""
            mode = self.server.mode
            if mode == "social":
                return self.send(200, page("login_social.html"))
            if mode == "captcha":
                return self.send(200, page("login_captcha.html", error=err))
            if mode == "spa":
                return self.send(200, page("login_spa.html"))
            if mode == "one_step":
                return self.send(200, page("login_one.html", error=err))
            if step == "otp":
                return self.send(200, page("login_otp.html", error=err))
            if step == "2":
                return self.send(200, page("login_password.html", error=err))
            return self.send(200, page("login_email.html", error=err))
        if path.startswith("/recaptcha/"):
            return self.send(200, b"<html><body>I am not a robot</body></html>")
        if path == "/expire":
            self.server.sessions.clear()
            return self.send(200, b"expired")
        if path == "/api/me":
            if not self.signed_in():
                return self.send(401, b'{"error":"unauthorized"}')
            return self.send(200, b'{"email":"%s"}' % EMAIL.encode())
        if path == "/logout":
            self.server.sessions.discard(self.cookies().get("sid", ""))
            return self.redirect("/", {"Set-Cookie": "sid=; Max-Age=0; Path=/"})
        if path in ("/app", "/app/", "/app/settings", "/app/billing", "/app/items"):
            if not self.signed_in():
                return self.redirect("/login")
            name = {"/app/settings": "settings.html", "/app/billing": "billing.html"}.get(
                path, "app.html"
            )
            touch = {"Set-Cookie": "seen=1; Path=/"} if name == "app.html" else None
            return self.send(200, page(name, email=EMAIL), touch)
        self.send(404, b"not found")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        self.server.posts.append(f"POST {path}")
        data = self.form()
        mode = self.server.mode
        if path == "/login/identify":
            if data.get("email") == EMAIL:
                return self.redirect("/login?step=2")
            return self.redirect("/login?error=We couldn't find your account")
        if path == "/login/password" or path == "/login/both":
            if mode == "spa":  # fetch from the page: answer with a status, not a redirect
                if data.get("email") != EMAIL or data.get("password") != PASSWORD:
                    return self.send(401, b"no")
                return self.send(
                    200, b"ok", {"Set-Cookie": f"sid={self.server.new_session()}; Path=/"}
                )
            if mode == "captcha" and path == "/login/both":
                return self.redirect("/login?error=Please complete the captcha")
            if mode not in ("one_step", "spa") and path == "/login/both":
                return self.send(400)
            if path == "/login/both" and data.get("email") != EMAIL:
                return self.redirect("/login?error=Incorrect email or password")
            if data.get("password") != PASSWORD:
                return self.redirect("/login?step=2&error=Incorrect password")
            if mode == "otp":
                return self.redirect("/login?step=otp")
            return self.redirect("/app", {"Set-Cookie": f"sid={self.server.new_session()}; Path=/"})
        if path == "/login/otp":
            if data.get("otp") != OTP:
                return self.redirect("/login?step=otp&error=Wrong code")
            return self.redirect("/app", {"Set-Cookie": f"sid={self.server.new_session()}; Path=/"})
        self.send(404)


@contextmanager
def running_site(mode: str = "two_step") -> Iterator[AuthSite]:
    site = AuthSite()
    site.mode = mode
    thread = threading.Thread(target=site.serve_forever, daemon=True)
    thread.start()
    try:
        yield site
    finally:
        site.shutdown()
        site.server_close()
