"""Fix the formal limits of a draft by code once the model has had its chances.

Characters, words, lines, an icon name: matters of form. They never fail a job: the text is cut at
a word boundary (core/trim_text.py) and a line "auto_trimmed: <field> <old> -> <new>" goes to the
script report (and the script review). Structure (scene type, layout, feature, missing fields) is
not touched here: that is for the writer to get right or the user to regenerate.
"""

from app.core import trim_text as tt
from app.script import catalog as cat


def note(field: str, old: str, new: str) -> str:
    return f"auto_trimmed: {field} «{old}» → «{new}»"


def trim_scene(s, label: str, max_words: int):  # type: ignore[no-untyped-def]
    """(scene with its formal limits met, the notes of what was cut)."""
    notes: list[str] = []
    changes: dict[str, object] = {}

    def cut_words(field: str, limit: int) -> None:
        old = getattr(s, field)
        if old and tt.words_of(old) > limit:
            new = tt.trim_words(old, limit) if field == "voiceover" else _first_words(old, limit)
            changes[field] = new
            notes.append(note(f"{label} {field}", old, new))

    cut_words("voiceover", min(max_words, cat.HOOK_MAX_WORDS) if s.type == "hook" else max_words)
    cut_words("on_screen_text", cat.ON_SCREEN_MAX_WORDS)
    if s.type == "before_after":
        cut_words("before_text", cat.BEFORE_AFTER_MAX_WORDS)
        cut_words("after_text", cat.BEFORE_AFTER_MAX_WORDS)
    key = s.key_point
    if key and len(key) > cat.KEY_POINT_MAX:
        changes["key_point"] = tt.trim_chars(key, cat.KEY_POINT_MAX)
        notes.append(note(f"{label} key_point", key, str(changes["key_point"])))
    elif not (key and key.strip()):  # a missing key point is made from what the scene says
        source = changes.get("voiceover", s.voiceover) or ""
        filled = tt.trim_chars(
            str(s.on_screen_text or _first_clause(str(source))), cat.KEY_POINT_MAX
        )
        if filled:
            changes["key_point"] = filled
            notes.append(f"auto_filled: {label} key_point → «{filled}»")
    if s.icon not in cat.ICONS and cat.ICONS:
        changes["icon"] = "check" if "check" in cat.ICONS else cat.ICONS[0]
        notes.append(f"auto_trimmed: {label} icon «{s.icon}» → «{changes['icon']}»")
    return (s.model_copy(update=changes) if changes else s), notes


def _first_words(text: str, limit: int) -> str:
    return tt.clean_end(" ".join(text.split()[:limit]))


def _first_clause(text: str) -> str:
    return tt.clean_end(text.replace(".", ",").split(",")[0].strip())


def trim_draft(draft, ctx):  # type: ignore[no-untyped-def]
    """The whole draft (badge, headline, highlight, every scene) within its limits."""
    notes: list[str] = []
    changes: dict[str, object] = {}
    if draft.badge is not None and len(draft.badge) > cat.BADGE_MAX:
        changes["badge"] = tt.trim_chars(draft.badge, cat.BADGE_MAX) or None
        notes.append(note("badge", draft.badge, str(changes["badge"])))
    headline = draft.headline
    if not headline.strip():
        headline = draft.title.strip() or ctx.outline.title
        changes["headline"] = tt.trim_chars(headline, cat.HEADLINE_MAX)
        notes.append(f"auto_filled: headline → «{changes['headline']}»")
    elif len(headline) > cat.HEADLINE_MAX:
        changes["headline"] = tt.trim_chars(headline, cat.HEADLINE_MAX)
        notes.append(note("headline", headline, str(changes["headline"])))
    final = str(changes.get("headline", headline))
    if tt.trim_highlight(final, draft.headline_highlight) != (draft.headline_highlight or None):
        old = draft.headline_highlight
        changes["headline_highlight"] = None  # cut away with the headline's tail
        notes.append(f"auto_trimmed: headline_highlight «{old}» → null")
    scenes = []
    for i, scene in enumerate(draft.scenes, start=1):
        limit = ctx.demo_max_words if scene.type == "feature_demo" else cat.VOICEOVER_MAX_WORDS
        fixed, scene_notes = trim_scene(scene, f"scene {i}", limit)
        scenes.append(fixed)
        notes += scene_notes
    changes["scenes"] = scenes
    return draft.model_copy(update=changes), notes
