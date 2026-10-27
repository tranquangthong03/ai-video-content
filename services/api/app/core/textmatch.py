"""Accent-free, fuzzy word matching shared by the explorer and the producer (pure functions)."""

import re
from difflib import SequenceMatcher

from app.core.features import fold

# Words that say nothing about what a text is about (Vietnamese and English)
STOPWORDS = {
    "theo", "cho", "cac", "cua", "voi", "trang", "xem", "them", "tinh", "nang", "the", "and",
    "for", "page", "with", "from", "this", "that",
}  # fmt: skip


def description_words(text: str) -> set[str]:
    """Accent-free lower-case words (3+ letters) of a description, without filler words."""
    return {w for w in re.findall(r"[a-z0-9]{3,}", fold(text)) if w not in STOPWORDS}


def words_match(a: str, b: str) -> bool:
    """Same word, or close enough (learning ~ learn, paths ~ path, typo of one letter)."""
    if a == b:
        return True
    stem = min(len(a), len(b))
    if stem >= 4 and (a.startswith(b) or b.startswith(a)):
        return True
    return stem >= 6 and SequenceMatcher(None, a, b).ratio() >= 0.88


def match_share(text: str, speech: str) -> float:
    """Share (0-1) of the words of `text` that are said in `speech` (fuzzy, accents ignored)."""
    wanted = description_words(text)
    said = description_words(speech)
    if not wanted or not said:
        return 0.0
    return sum(1 for w in wanted if any(words_match(w, h) for h in said)) / len(wanted)


def text_matches(text: str, speech: str, min_share: float = 0.5) -> bool:
    """True when (nearly) the words of `text` are said in `speech`: at least `min_share` of them
    (and one) match, fuzzily, accents ignored. Used to check a speech really mentions an item."""
    wanted = description_words(text)
    said = description_words(speech)
    if not wanted or not said:
        return False
    hits = sum(1 for w in wanted if any(words_match(w, h) for h in said))
    return hits >= 1 and hits / len(wanted) >= min_share
