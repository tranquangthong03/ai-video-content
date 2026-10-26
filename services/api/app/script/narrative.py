"""Checks of the marketing narrative that code does, not the prompt (pure functions).

Hook length and kinds, empty phrases, a CTA that reads out a URL, numbers nobody can source.
The writer sends what is wrong back to the model; the formal leftovers are fixed by code."""

import re
from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from app.browser.form_actions import fold
from app.script import catalog as cat

HOOK_MIN_WORDS = 5
URL_RE = re.compile(r"https?://|www\.|\S+\.(?:com|vn|app|io|net|org)/\S+", re.IGNORECASE)


class HookOption(Protocol):
    kind: str
    voiceover: str
    on_screen_text: str | None


def forbidden_in(text: str | None) -> list[str]:
    """Empty marketing phrases found in the text."""
    folded = fold(text or "")
    return [p for p in cat.FORBIDDEN_PHRASES if fold(p) in folded]


def opens_with_name(text: str, product_name: str) -> bool:
    name, folded = fold(product_name), fold(text)
    return bool(name) and (folded == name or folded.startswith(name + " "))


def reads_a_url(text: str | None) -> bool:
    return bool(text and URL_RE.search(text))


def hook_line_issues(
    label: str, voiceover: str, on_screen: str | None, product_name: str
) -> list[str]:
    errors: list[str] = []
    words = cat.word_count(voiceover)
    if not HOOK_MIN_WORDS <= words <= cat.HOOK_MAX_WORDS:
        errors.append(f"{label}: hook có {words} từ, cần {HOOK_MIN_WORDS}–{cat.HOOK_MAX_WORDS}")
    if opens_with_name(voiceover, product_name):
        errors.append(f"{label}: hook không được mở bằng tên sản phẩm «{product_name}»")
    if cat.word_count(on_screen) > cat.ON_SCREEN_MAX_WORDS:
        errors.append(f"{label}: on_screen_text quá {cat.ON_SCREEN_MAX_WORDS} từ")
    return errors


def hook_option_issues(
    options: Sequence[HookOption], product_name: str, *, has_numbers: bool, required: bool
) -> list[str]:
    """Two hooks of different kinds; a shocking-number hook only when the proof has a number."""
    errors: list[str] = []
    if required and len(options) != 2:
        errors.append(f"hook_options cần đúng 2 phương án khác kiểu, hiện có {len(options)}")
    kinds = [o.kind for o in options]
    if len(set(kinds)) != len(kinds):
        errors.append("hook_options: hai phương án phải khác kiểu (kind)")
    for n, option in enumerate(options, start=1):
        label = f"hook_options[{n}]"
        if option.kind not in cat.HOOK_KINDS:
            errors.append(
                f"{label}: kind «{option.kind}» không hợp lệ ({', '.join(cat.HOOK_KINDS)})"
            )
        errors += hook_line_issues(label, option.voiceover, option.on_screen_text, product_name)
        if option.kind == "shocking_number" and not (
            has_numbers and re.search(r"\d", option.voiceover + (option.on_screen_text or ""))
        ):
            errors.append(f"{label}: shocking_number chỉ dùng khi có con số thật trong proof bank")
    return errors


def numbers_in_texts(texts: Iterable[str | None]) -> str:
    return " ".join(t for t in texts if t)


# what a viewer reads or hears as a claim: the only places numbers need a source
CLAIM_FIELDS = ("voiceover", "on_screen_text", "stat")


def scene_texts(scene: Any, only: Sequence[str] | None = None) -> dict[str, str]:
    """Every sentence a scene (draft or built) shows or says, by field."""
    out = {}
    for name in ("voiceover", "on_screen_text", "key_point", "before_text", "after_text"):
        value = getattr(scene, name, None)
        if value:
            out[name] = str(value)
    stat = getattr(scene, "stat", None)
    if stat:
        out["stat"] = f"{stat.value} {stat.label}"
    return {k: v for k, v in out.items() if only is None or k in only}
