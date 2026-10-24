"""auto_upload (labels, drop zones, JS-opened file choosers) and wait_for_settle."""

import time
from pathlib import Path

from playwright.sync_api import Page

from app.browser.page_utils import wait_for_settle
from app.browser.session import BrowserSession
from app.explorer.extract import extract_page
from app.explorer.report import Report
from tests.test_explorer import feature, page_of, profile, verify

# --- wait_for_settle ----------------------------------------------------------------------------


def open_page(session: BrowserSession, site: str, path: str):  # type: ignore[no-untyped-def]
    ctx = session.new_context()
    page = ctx.new_page()
    page.goto(f"{site}{path}")
    return ctx, page


def test_a_quiet_page_settles_immediately(browser_session: BrowserSession, site: str) -> None:
    ctx, page = open_page(browser_session, site, "/settle.html")
    started = time.monotonic()
    result = wait_for_settle(page)
    assert result["settled"] is True and result["network_idle"] is True
    assert time.monotonic() - started < 1.5  # network idle + ~400ms of quiet, not the full budget
    ctx.close()


def test_waits_for_a_slow_image_in_the_viewport(browser_session: BrowserSession, site: str) -> None:
    ctx, page = open_page(browser_session, site, "/settle.html")
    page.click("#load-image")
    page.wait_for_timeout(100)
    assert page.evaluate("document.images[0].complete") is False  # still downloading
    result = wait_for_settle(page)
    assert result["images"] is True and result["settled"] is True
    assert page.evaluate("[...document.images].every((i) => i.complete)") is True
    assert (
        result["waited_ms"] >= 300
    )  # a fixed 500ms sleep would have returned with the image missing
    ctx.close()


def test_waits_until_the_dom_stops_changing(browser_session: BrowserSession, site: str) -> None:
    ctx, page = open_page(browser_session, site, "/settle.html")
    page.click("#burst")  # six mutations over ~600ms
    result = wait_for_settle(page)
    assert result["quiet_dom"] is True
    assert page.evaluate("document.getElementById('box').textContent.length") == 6
    ctx.close()


def test_gives_up_at_the_timeout_on_a_page_that_never_settles(
    browser_session: BrowserSession, site: str
) -> None:
    ctx, page = open_page(browser_session, site, "/settle.html")
    page.click("#forever")
    started = time.monotonic()
    result = wait_for_settle(page, timeout=1500)
    elapsed = time.monotonic() - started
    assert result["settled"] is False
    assert 1.0 <= elapsed < 2.5  # one shared budget, not network + dom budgets added up
    ctx.close()


# --- auto_upload --------------------------------------------------------------------------------


def names(report: Report) -> dict[str, dict]:  # type: ignore[type-arg]
    return {a["name"]: a for a in report.data["auto_upload"]}


def click_feature(page, ref: str, fid: str):  # type: ignore[no-untyped-def]
    return feature(fid, None, [{"do": "click", "url": page.url, "ref": ref}], url=page.url)


def test_click_on_a_label_a_drop_zone_and_a_js_button_all_become_uploads(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    data = page_of(browser_session, site, "/pick.html", tmp_path)
    by_text = {e.text: e for e in data.elements}
    label = by_text["Chọn bằng label"]
    zone = by_text["Thả CSV vào đây"]
    pick = by_text["Mở hộp chọn tệp"]
    prof = profile(
        [
            click_feature(data, label.ref, "by-label"),
            click_feature(data, zone.ref, "by-zone"),
            click_feature(data, pick.ref, "by-chooser"),
        ]
    )
    report = verify(browser_session, prof, [data], site, tmp_path)
    uploads = report.data["auto_upload"]
    by_feature = {u["feature"]: u for u in uploads}
    assert set(by_feature) == {"by-label", "by-zone", "by-chooser"}
    assert (
        by_feature["by-label"]["via"] == "direct" and by_feature["by-label"]["file"] == "sample.pdf"
    )
    assert (
        by_feature["by-zone"]["via"] == "direct" and by_feature["by-zone"]["file"] == "sample.csv"
    )
    # the button only opens the chooser from JS: caught through the filechooser event
    assert by_feature["by-chooser"]["via"] == "chooser"
    assert by_feature["by-chooser"]["file"] == "sample.jpg"  # no accept: images by default
    for f in prof.features:
        assert f.demo_kind == "interaction", f.id  # "Đã nhận ..." appeared in the list
        assert f.demo_evidence.new_list_items >= 1  # type: ignore[union-attr]


def test_an_upload_step_on_a_label_works_too(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    data = page_of(browser_session, site, "/pick.html", tmp_path)
    label = next(e for e in data.elements if e.text == "Chọn bằng label")
    step = {"do": "upload", "url": data.url, "ref": label.ref}
    prof = profile([feature("up", None, [step], url=data.url)])
    report = verify(browser_session, prof, [data], site, tmp_path)
    assert prof.features[0].demo_kind == "interaction"
    assert any(c.get("file") == "sample.pdf" for c in report.data["clicks"])


def test_an_ordinary_button_is_never_turned_into_an_upload(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    data = page_of(browser_session, site, "/pick.html", tmp_path)
    plain = next(e for e in data.elements if e.text == "Nút thường")
    prof = profile([click_feature(data, plain.ref, "plain")])
    report = verify(browser_session, prof, [data], site, tmp_path)
    assert report.data["auto_upload"] == []
    assert prof.features[0].demo_kind == "interaction"  # a list item appeared: "plain clicked"


def test_extraction_marks_every_file_input_even_when_hidden(
    browser_session: BrowserSession, site: str, tmp_path: Path
) -> None:
    ctx = browser_session.new_context()
    page: Page = ctx.new_page()
    page.goto(f"{site}/pick.html")
    data = extract_page(page, 1, tmp_path)
    ctx.close()
    uploads = [e for e in data.elements if "upload" in e.caps]
    inputs = [e for e in uploads if e.tag == "input"]
    assert sorted(e.accept or "" for e in inputs) == ["", ".csv", "application/pdf"]
    # the label and the drop zone in front of them are listed too, so the LLM can refer to them
    assert {e.tag for e in uploads if e.tag != "input"} == {"label", "div"}
