"""When may the explorer press Enter after typing into a field?

strict (default): only while the request guard is on AND
  a) the field is a text input/textarea outside any <form>, or
  b) it sits in a <form> with exactly one visible text input, no password/email/tel/file input,
     a same-site action, and (method GET or the action is the current page's own path).
relaxed: whenever the guard is on, except password fields and blacklisted field names.
Everything else is "enter_blocked" with the reason, which goes into the report.
"""

from typing import Literal
from urllib.parse import urlparse

from app.browser.blacklist import is_blocked
from app.browser.locate import ElementInfo
from app.browser.urls import same_site

Policy = Literal["strict", "relaxed"]


def enter_decision(
    info: ElementInfo, page_url: str, *, guard_on: bool, policy: Policy = "strict"
) -> tuple[bool, str]:
    """(allowed, reason). `reason` explains a refusal and is "ok" when allowed."""
    if not guard_on:
        return False, "guard_off"
    if not info.is_text_input:
        return False, "not_a_text_input"
    if info.input_type == "password":
        return False, "password_field"
    if is_blocked(*info.texts, strict=True):
        return False, "blacklisted_field"
    if policy == "relaxed":
        return True, "ok"
    if not info.in_form:
        return True, "ok"
    form = info.form
    assert form is not None
    if form.text_inputs != 1:
        return False, f"form_has_{form.text_inputs}_text_inputs"
    if form.sensitive:
        return False, "form_has_sensitive_input"
    if not same_site(form.action, page_url):
        return False, "form_action_other_site"
    here, there = urlparse(page_url).path.rstrip("/"), urlparse(form.action).path.rstrip("/")
    if form.method != "get" and here != there:
        return False, "form_posts_to_other_path"
    return True, "ok"
