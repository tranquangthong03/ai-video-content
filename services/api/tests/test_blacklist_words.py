import pytest

from app.browser.blacklist import ACCOUNT_ACTIONS, is_blocked, matched_term
from app.browser.locate import ElementInfo, Unsafe, check_clickable, check_typeable
from app.script.targets import usable

ROOT = "https://app.example.com/"


def info(tag: str = "button", texts: list[str] | None = None, **kw: object) -> ElementInfo:
    base: dict[str, object] = {
        "tag": tag, "texts": texts or [], "href": None, "input_type": None, "button_type": None,
        "in_form": False, "form": None, "is_text_input": False, "text": "",
    }  # fmt: skip
    return ElementInfo(**{**base, **kw})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "text",
    [
        "Invite member", "Invite", "invite teammates", "Mời thành viên", "Mời", "mời thêm đồng nghiệp",
        "Mời người dùng", "Share access", "Generate key", "Generate API key", "Revoke token",
        "Upgrade plan", "Upgrade", "Nâng cấp gói", "Thu hồi quyền", "Tạo khóa API", "Chia sẻ quyền",
    ],
)  # fmt: skip
def test_account_actions_are_blocked_on_controls(text: str) -> None:
    assert is_blocked(text), text


@pytest.mark.parametrize(
    "text",
    [
        "Mời bạn dùng thử", "Mời bạn trải nghiệm miễn phí", "Invite you to try it free",
        "Invite to try", "Upgraded", "upgrades", "Reinvite", "Premier mời", "Create item",
    ],
)  # fmt: skip
def test_calls_to_action_that_only_contain_the_word_are_not_blocked(text: str) -> None:
    if text == "Premier mời":  # ends with the bare word: still "invite", by design
        assert is_blocked(text)
    else:
        assert not is_blocked(text), text


def test_the_term_that_matched_is_reported() -> None:
    assert matched_term(["Please Upgrade now"]) == "upgrade"
    assert matched_term(["Mời thành viên mới"]) == "mời"
    assert set(ACCOUNT_ACTIONS) >= {"invite", "mời", "upgrade", "revoke", "generate key"}


def test_accents_written_in_either_unicode_form_match() -> None:
    import unicodedata

    text = unicodedata.normalize("NFD", "Mời thành viên")
    assert is_blocked(text)


def test_a_heading_or_data_is_not_a_control_but_the_core_terms_still_apply() -> None:
    assert not is_blocked("Upgrade your workflow", interactive=False)
    assert not is_blocked("Mời họp 9h", interactive=False)  # a todo the user typed
    assert is_blocked("Delete everything", interactive=False)
    assert is_blocked("Mua ngay", interactive=False)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"tag": "a"}, True),
        ({"tag": "button"}, True),
        ({"tag": "div", "role": "button"}, True),
        ({"tag": "div", "role": "menuitem"}, True),
        ({"tag": "div", "operable": True}, True),
        ({"tag": "input", "input_type": "submit"}, True),
        ({"tag": "input", "input_type": "text"}, False),
        ({"tag": "li"}, False),
        ({"tag": "h2"}, False),
    ],
)
def test_what_counts_as_an_interactive_element(kwargs: dict[str, object], expected: bool) -> None:
    assert info(**kwargs).interactive is expected  # type: ignore[arg-type]


def test_clicking_is_refused_on_a_control_that_invites_or_upgrades() -> None:
    for tag, role in (("button", None), ("a", None), ("div", "button")):
        with pytest.raises(Unsafe):
            check_clickable(info(tag, ["Invite member"], role=role), ROOT, scope_prefix=None)
    with pytest.raises(Unsafe):
        check_clickable(info("button", ["Upgrade plan"]), ROOT, scope_prefix=None)


def test_a_call_to_action_and_user_data_can_be_clicked() -> None:
    check_clickable(info("button", ["Mời bạn dùng thử"]), ROOT, scope_prefix=None)
    check_clickable(
        info("li", ["Mời họp 9h"]), ROOT, scope_prefix=None
    )  # a todo item (data, double-click)


def test_typing_into_a_field_named_invite_code_is_allowed_but_not_into_a_delete_field() -> None:
    check_typeable(info("input", ["Invite code"], input_type="text", is_text_input=True))
    with pytest.raises(Unsafe):
        check_typeable(info("input", ["Delete reason"], input_type="text", is_text_input=True))


def test_pointing_at_a_heading_with_the_word_is_fine_a_link_with_it_is_not() -> None:
    heading = {"role": "heading", "name": "Upgrade your workflow", "text": "Upgrade your workflow"}
    link = {
        "role": "link",
        "name": "Upgrade",
        "text": "Upgrade",
        "href": "https://app.example.com/u",
    }
    assert usable(heading) and not usable(link)
