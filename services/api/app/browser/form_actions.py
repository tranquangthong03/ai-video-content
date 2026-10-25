"""Form actions shared by the Flow Agent and the recorder's replay: choose from a dropdown (native
or drawn by the page), tick a box, enter a date (typed in the field's own format, else picked in
the calendar). They act through `Ops`, so the recorder can swap in a slow, visible mouse and
keyboard while the agent acts at once.

Nothing here decides whether an action is allowed; callers check the blacklist first, and the
option that gets clicked is checked here as well.
"""

import calendar
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from playwright.sync_api import Locator, Page

from app.browser.blacklist import is_blocked, is_blocked_href
from app.browser.locate import ElementInfo, Target, Unsafe, check_clickable
from app.browser.urls import same_site

MAX_MONTH_STEPS = 18
POPUP = (
    "[role=listbox],[role=menu],[class*=dropdown-menu],[class*=select-dropdown],"
    "[class*=autocomplete],[class*=options]"
)
CALENDAR = (
    "[role=dialog],[role=grid],[class*=calendar],[class*=datepicker],[class*=date-picker],"
    "[class*=picker]"
)
DATE_TOKEN = re.compile(r"yyyy|yy|mmmm|mmm|mm|m|dd|d", re.IGNORECASE)
NEXT_BUTTON = re.compile(r"next|tiếp|sau|forward|›|»|>", re.IGNORECASE)
PREV_BUTTON = re.compile(r"prev|trước|back|‹|«|<", re.IGNORECASE)


SUBMIT_NAME = re.compile(
    r"\b(save|submit|apply|create|add|confirm|send request|lưu|gửi|tạo|thêm|xác nhận)\b",
    re.IGNORECASE,
)


def check_submit_click(info: ElementInfo, root_url: str) -> None:
    """The checks for a click the flow is allowed to make (a submit): still no delete / pay /
    invite / send, and nothing that leaves the site."""
    if is_blocked(*info.texts, strict=False, interactive=True):
        raise Unsafe("blacklist", f"matches blacklist: {info.texts[:2]}")
    if is_blocked_href(info.href) or (info.href and not same_site(info.href, root_url)):
        raise Unsafe("blacklist", f"blocked link {info.href}")


class ActionFailed(RuntimeError):
    """The action could not be done (option missing, date refused...); the text is for the agent."""


@dataclass
class Ops:
    """How the mouse and keyboard are used."""

    click: Callable[[Target], None] = lambda t: t.click()
    type_text: Callable[[Target, str], None] = lambda t, text: t.fill(text)


def fold(text: str) -> str:
    """Lower-case without accents or extra spaces, for matching what a user sees."""
    plain = unicodedata.normalize("NFD", text.casefold().replace("đ", "d"))
    return " ".join("".join(c for c in plain if unicodedata.category(c) != "Mn").split())


# --- dropdowns -----------------------------------------------------------------------------------


def _box(loc: Locator) -> dict[str, float] | None:
    try:
        return loc.bounding_box()
    except Exception:
        return None


def _nearest(candidates: list[Locator], anchor: dict[str, float] | None) -> Locator:
    if anchor is None or len(candidates) == 1:
        return candidates[0]

    def distance(loc: Locator) -> float:
        box = _box(loc)
        return abs(box["y"] - anchor["y"]) if box else 1e9

    return min(candidates, key=distance)


def _visible(loc: Locator, limit: int = 20) -> list[Locator]:
    out = []
    for i in range(min(loc.count(), limit)):
        item = loc.nth(i)
        if item.is_visible():
            out.append(item)
    return out


def find_option(page: Page, text: str, anchor: dict[str, float] | None) -> Locator | None:
    """The visible option showing `text` after a dropdown was opened (exact, then accent-blind)."""
    wanted = fold(text)
    searches = [
        page.get_by_role("option", name=text, exact=True),
        page.locator(POPUP).get_by_text(text, exact=True),
        page.get_by_text(text, exact=True),
    ]
    for search in searches:
        found = _visible(search)
        if found:
            return _nearest(found, anchor)
    for search in (page.get_by_role("option"), page.locator(POPUP).locator("li,div,span,a")):
        found = [
            o
            for o in _visible(search, 60)
            if fold(o.inner_text() or "") == wanted
            or (wanted and wanted in fold(o.inner_text() or "") and not o.locator("*").count())
        ]
        if found:
            return _nearest(found, anchor)
    return None


def visible_option_texts(page: Page, limit: int = 10) -> list[str]:
    """What the opened list offers: the texts of its visible options."""
    found: list[str] = []
    for search in (page.get_by_role("option"), page.locator(POPUP).locator("li,div,span,a")):
        for item in _visible(search, 40):
            if search is not None and item.locator("*").count():
                continue  # a wrapper, not an option
            text = " ".join((item.inner_text() or "").split())
            if text and text not in found:
                found.append(text)
        if found:
            break
    return found[:limit]


def current_text(target: Target) -> str:
    """What a dropdown shows now: the selected option of a <select>, else the visible text."""
    return target.evaluate(
        "el => el.tagName === 'SELECT' ? (el.selectedOptions[0] ? el.selectedOptions[0].text : '')"
        " : (el.value !== undefined && el.value !== '' ? el.value : el.innerText)"
    ).strip()


def select_option(page: Page, target: Target, text: str, root_url: str, ops: Ops) -> None:
    """Choose `text` in a native <select> or in a dropdown the page draws itself."""
    wanted = text.strip()
    if not wanted:
        raise ActionFailed("select: thiếu giá trị cần chọn")
    if target.info().tag == "select":
        options = target.evaluate("el => [...el.options].map(o => o.text.trim())")
        match = next((o for o in options if o == wanted), None) or next(
            (o for o in options if fold(o) == fold(wanted)), None
        )
        if match is None:
            raise ActionFailed(
                f"select: không có lựa chọn «{wanted}» (có: {', '.join(options[:10])})"
            )
        ops.click(target)
        target.select_label(match)
        return
    before = current_text(target)
    ops.click(target)  # opens the list
    page.wait_for_timeout(250)
    option = find_option(page, wanted, target.box())
    if option is None:
        seen = visible_option_texts(page)
        page.keyboard.press("Escape")
        if visible_option_texts(
            page
        ):  # still open: close it, or the next select would toggle it shut
            ops.click(target)
        have = f" (có: {', '.join(seen)})" if seen else " sau khi mở danh sách"
        raise ActionFailed(f"select: không thấy lựa chọn «{wanted}»{have}")
    choice = Target("css", locator=option)
    check_clickable(choice.info(), root_url, scope_prefix=None)
    ops.click(choice)
    page.wait_for_timeout(250)
    after = current_text(target)
    if fold(wanted) not in fold(after) and after == before:
        raise ActionFailed(f"select: đã bấm «{wanted}» nhưng ô vẫn hiện «{after}»")


# --- check boxes ---------------------------------------------------------------------------------


def is_checked(target: Target) -> bool:
    return bool(
        target.evaluate("el => el.checked === true || el.getAttribute('aria-checked') === 'true'")
    )


def check(target: Target, ops: Ops) -> None:
    """Tick a checkbox or pick a radio; already ticked is left as it is."""
    if is_checked(target):
        return
    ops.click(target)
    if not is_checked(target):
        raise ActionFailed("check: ô chưa được chọn sau khi bấm")


# --- dates ---------------------------------------------------------------------------------------


def parse_iso(value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError as e:
        raise ActionFailed(f"pick_date: «{value}» không phải YYYY-MM-DD") from e


def format_date(day: date, hint: str) -> str | None:
    """The date written like the hint ("dd/mm/yyyy", "d MMM yyyy"...), or None without a hint."""
    leftover = DATE_TOKEN.sub("", hint)
    if "y" not in hint.casefold() or re.search(r"[^\W\d_]", leftover):
        return None  # not a format: a placeholder such as "Select date" has other letters

    def token(m: re.Match[str]) -> str:
        t = m.group(0).lower()
        return {
            "yyyy": f"{day.year:04d}", "yy": f"{day.year % 100:02d}",
            "mmmm": calendar.month_name[day.month], "mmm": calendar.month_abbr[day.month],
            "mm": f"{day.month:02d}", "m": str(day.month),
            "dd": f"{day.day:02d}", "d": str(day.day),
        }[t]  # fmt: skip

    return DATE_TOKEN.sub(token, hint.strip())


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _month_in(text: str) -> tuple[int, int] | None:
    """(year, month) shown by a calendar header, if the text names one."""
    low = text.casefold()
    year = re.search(r"\b(19|20)\d{2}\b", low)
    if not year:
        return None
    for number in range(1, 13):
        names = {calendar.month_name[number].casefold(), calendar.month_abbr[number].casefold()}
        if any(re.search(rf"\b{re.escape(n)}\b", low) for n in names):
            return int(year.group(0)), number
    return None


def _calendar_popup(page: Page) -> Locator | None:
    for loc in _visible(page.locator(CALENDAR), 10):
        if loc.get_by_role("button").count() or loc.get_by_role("gridcell").count():
            return loc
    return None


def pick_in_calendar(page: Page, day: date, ops: Ops) -> None:
    popup = _calendar_popup(page)
    if popup is None:
        raise ActionFailed("pick_date: không thấy lịch để chọn ngày")
    for _ in range(MAX_MONTH_STEPS):
        shown = _month_in((popup.inner_text() or "")[:120])
        if shown is None:
            raise ActionFailed("pick_date: không đọc được tháng đang hiện trên lịch")
        if shown == (day.year, day.month):
            break
        name = NEXT_BUTTON if shown < (day.year, day.month) else PREV_BUTTON
        button = next(
            (
                b
                for b in _visible(popup.get_by_role("button"), 12)
                if name.search((b.get_attribute("aria-label") or "") + " " + (b.inner_text() or ""))
            ),
            None,
        )
        if button is None:
            raise ActionFailed("pick_date: không có nút chuyển tháng trên lịch")
        ops.click(Target("css", locator=button))
        page.wait_for_timeout(150)
    else:
        raise ActionFailed("pick_date: lịch không tới được tháng cần chọn")
    cells = _visible(popup.get_by_role("gridcell", name=str(day.day), exact=True), 40) or _visible(
        popup.get_by_text(str(day.day), exact=True), 40
    )
    cells = [
        c
        for c in cells
        if not re.search(r"outside|other|disabled|muted", c.get_attribute("class") or "", re.I)
    ]
    if not cells:
        raise ActionFailed(f"pick_date: không thấy ngày {day.day} trên lịch")
    ops.click(Target("css", locator=cells[0]))


def pick_date(page: Page, target: Target, iso: str, ops: Ops) -> None:
    """Enter a date: a date input takes ISO; a text field gets the date in its placeholder's
    format; when the field refuses it (read-only, or the page rejects it) the calendar is used."""
    day = parse_iso(iso)
    info = target.info()
    if info.input_type == "date":
        ops.type_text(target, day.isoformat())
        return
    hint = target.evaluate(
        "el => (el.getAttribute('placeholder') || el.getAttribute('data-format') || '')"
    )
    text = format_date(day, hint) or day.isoformat()
    readonly = bool(target.evaluate("el => el.readOnly === true"))
    if not readonly:
        ops.type_text(target, text)
        page.keyboard.press("Tab")
        page.wait_for_timeout(250)
        shown = str(target.evaluate("el => el.value || el.innerText || ''"))
        invalid = bool(target.evaluate("el => el.getAttribute('aria-invalid') === 'true'"))
        if _digits(shown) == _digits(text) and not invalid:
            return
    ops.click(target)  # the calendar opens
    page.wait_for_timeout(250)
    pick_in_calendar(page, day, ops)
    page.wait_for_timeout(250)
    shown = str(target.evaluate("el => el.value || el.innerText || ''"))
    if str(day.day) not in shown and not _digits(shown):
        raise ActionFailed(f"pick_date: ô ngày vẫn trống sau khi chọn {iso}")
