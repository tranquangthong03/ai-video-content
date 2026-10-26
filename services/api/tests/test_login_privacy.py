import io
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image, ImageFilter, ImageStat

from app.browser.auth_detect import is_logout_url
from app.browser.blacklist import is_blocked, is_blocked_href
from app.browser.privacy import blur_enabled
from app.browser.session import BrowserSession
from app.core.subpages import is_sensitive, is_sensitive_text
from app.explorer.mapper import crawl
from app.explorer.report import Deadline, Report
from app.explorer.synthesize import _step_problem
from app.schemas.generated.product_profile import DemoStep
from tests.auth_site import EMAIL, AuthSite, running_site
from tests.test_recorder import goto, loc, rec


@pytest.fixture
def site() -> Iterator[AuthSite]:
    with running_site() as s:
        yield s


def state_file(tmp_path: Path, site: AuthSite) -> Path:
    cookie = {"name": "sid", "value": site.new_session(), "domain": "127.0.0.1", "path": "/"}
    path = tmp_path / "storage_state.json"
    path.write_text(json.dumps({"cookies": [{**cookie, "expires": -1}], "origins": []}))
    return path


# --- pages that are never explored once signed in -------------------------------------------------


def test_what_counts_as_a_sensitive_page() -> None:
    for url in ("https://x.com/settings", "https://x.com/app/account/", "https://x.com/billing",
                "https://x.com/admin/users", "https://x.com/team/invite", "https://x.com/api-keys",
                "https://x.com/cài-đặt", "https://x.com/thanh-toán", "https://x.com/user/profile"):  # fmt: skip
        assert is_sensitive(url), url
    for url in ("https://x.com/app", "https://x.com/items", "https://x.com/accounting-tips"):
        assert not is_sensitive(url), url
    assert is_sensitive(None, "Settings - TaskBoard") and is_sensitive(None, "Bảo mật tài khoản")
    assert not is_sensitive(None, "My work - TaskBoard")
    assert (
        is_sensitive_text("Billing")
        and is_sensitive_text("Cài đặt")
        and not is_sensitive_text("Items")
    )


def crawl_app(session: BrowserSession, site: AuthSite, tmp_path: Path, authenticated: bool):  # type: ignore[no-untyped-def]
    ctx = session.new_context()
    report = Report(site.base)
    try:
        pages, _ = crawl(
            ctx.new_page(), ctx, site.base + "/app", tmp_path, report, Deadline(60),
            max_pages=6, authenticated=authenticated,
        )  # fmt: skip
    finally:
        ctx.close()
    return [p.url.removeprefix(site.base) for p in pages], report


def test_signed_in_the_explorer_leaves_settings_and_billing_alone(
    tmp_path: Path, site: AuthSite
) -> None:
    state = state_file(tmp_path, site)
    with BrowserSession(site.base, storage_state=state) as s:
        paths, report = crawl_app(s, site, tmp_path / "a", authenticated=True)
    assert paths == ["/app"]  # (billing is a blocked link anyway; settings is the sensitive one)
    assert any(u.endswith("/app/settings") for u in report.data["sensitive_skipped"])


def test_without_the_flag_the_same_session_does_visit_them(tmp_path: Path, site: AuthSite) -> None:
    state = state_file(tmp_path, site)
    with BrowserSession(site.base, storage_state=state) as s:
        paths, _ = crawl_app(s, site, tmp_path / "b", authenticated=False)
    assert "/app/settings" in paths  # (so the filter above is what keeps them out)


def test_a_demo_step_never_goes_to_a_sensitive_or_sign_out_page() -> None:
    def problem(url: str, authenticated: bool) -> str | None:
        step = DemoStep(do="goto", url=url)
        return _step_problem(step, "https://x.com/app", {}, "https://x.com/", set(), authenticated)

    assert problem("https://x.com/app/settings", True) is not None
    assert problem("https://x.com/app/settings", False) is None  # only while signed in
    assert problem("https://x.com/logout", False) is not None
    assert problem("https://x.com/app/items", True) is None


# --- what is never clicked or visited -----------------------------------------------------------------


def test_the_new_blacklist_terms() -> None:
    for text in ("Invite member", "Mời thành viên", "Share access", "Chia sẻ quyền", "Generate key",
                 "Tạo khóa API", "Revoke token", "Thu hồi", "Upgrade plan", "Nâng cấp"):  # fmt: skip
        assert is_blocked(text), text
    assert not is_blocked("Create item")


def test_sign_out_paths_are_blocked_in_every_spelling() -> None:
    for url in ("https://x.com/logout", "https://x.com/sign-out", "https://x.com/sign_out",
                "https://x.com/đăng-xuất", "https://x.com/dang-xuat"):  # fmt: skip
        assert is_logout_url(url) and is_blocked_href(url), url


def test_the_recorder_refuses_invite_and_sign_out(tmp_path: Path, site: AuthSite) -> None:
    visual = {
        "mode": "recording",
        "actions": [
            goto(site.base, "/app"),
            {"do": "click", "locator": loc("#invite")},
            {"do": "goto", "url": site.base + "/logout"},
            {"do": "hover", "locator": loc("#create")},
        ],
    }
    with BrowserSession(site.base, storage_state=state_file(tmp_path, site)) as s:
        r = rec(s, site.base, tmp_path / "out", visual)
    assert r.steps_failed == 2 and r.steps_ok == 1
    assert all("bị chặn vì an toàn" in w for w in r.warnings)
    assert "/logout" not in " ".join(site.hits)  # never requested


# --- blurring personal data ----------------------------------------------------------------------------


def open_app(session: BrowserSession, site: AuthSite):  # type: ignore[no-untyped-def]
    ctx = session.new_context()
    page = ctx.new_page()
    page.goto(site.base + "/app")
    page.wait_for_timeout(300)
    return ctx, page


def test_email_phone_and_the_account_menu_are_blurred_and_the_text_is_unchanged(
    tmp_path: Path, site: AuthSite
) -> None:
    with BrowserSession(site.base, storage_state=state_file(tmp_path, site)) as s:
        ctx, page = open_app(s, site)
        blurred = page.evaluate(
            """() => [...document.querySelectorAll('[data-pii-blur]')].map(
                 (e) => [e.textContent, getComputedStyle(e).filter])"""
        )
        text_before = page.inner_text("body")
        page.evaluate(
            "document.querySelector('main').append(' write to late@example.com or +84 912 345 678')"
        )
        # the observer catches what appears later (it scans on requestAnimationFrame, which a busy
        # machine can delay well past a fixed 300ms: wait for the condition, not for the clock)
        page.wait_for_function(
            "[...document.querySelectorAll('[data-pii-blur]')].some((e) => e.textContent.includes('late@example.com'))",
            timeout=10_000,
        )
        late = page.evaluate(
            "[...document.querySelectorAll('[data-pii-blur]')].map((e) => e.textContent)"
        )
        text_after = page.inner_text("body")
        ctx.close()
    texts = [b[0] for b in blurred]
    assert EMAIL in texts and "0901 234 567" in texts and "D" in texts  # e-mail, phone, avatar
    assert "Bilol Abdurasul" in texts  # the name in the user dropdown of the header
    assert all("blur(6px)" in b[1] for b in blurred)
    assert "late@example.com" in late and "+84 912 345 678" in late
    assert text_before.replace(" ", "") in text_after.replace(" ", "")  # nothing was removed
    assert "Create item" not in texts and "Items" not in texts


def edge_energy(png: bytes) -> float:
    image = Image.open(io.BytesIO(png)).convert("L").filter(ImageFilter.FIND_EDGES)
    return float(ImageStat.Stat(image).mean[0])


def test_the_header_in_a_screenshot_is_visibly_blurred(tmp_path: Path, site: AuthSite) -> None:
    state = state_file(tmp_path, site)
    shots = {}
    for blur in (False, True):
        with BrowserSession(site.base, storage_state=state, blur_personal=blur) as s:
            ctx, page = open_app(s, site)
            box = page.locator("#user-email").bounding_box()
            assert box is not None
            shots[blur] = page.screenshot(
                clip={
                    "x": box["x"] - 4,
                    "y": box["y"] - 4,
                    "width": box["width"] + 8,
                    "height": box["height"] + 8,
                }
            )
            ctx.close()
    assert edge_energy(shots[True]) < 0.5 * edge_energy(shots[False])


def test_blur_follows_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    assert blur_enabled(True, {}) is True and blur_enabled(False, {}) is False  # auto
    assert blur_enabled(False, {"BLUR_PERSONAL_DATA": "1"}) is True
    assert blur_enabled(True, {"BLUR_PERSONAL_DATA": "0"}) is False


def test_a_public_visit_without_a_session_is_not_blurred(site: AuthSite) -> None:
    with BrowserSession(site.base) as s:
        ctx = s.new_context()
        page = ctx.new_page()
        page.goto(site.base + "/")
        page.evaluate("document.body.append(' mail me: someone@example.com')")
        page.wait_for_timeout(500)  # negative check: nothing to wait on, only time
        count = page.locator("[data-pii-blur]").count()
        ctx.close()
    assert count == 0
