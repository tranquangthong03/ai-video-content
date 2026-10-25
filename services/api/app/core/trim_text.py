"""Deterministic shortening of text that is over a formal limit (pure functions).

A limit on characters, words or lines is a matter of form: it never fails a job. After the model
has had its chances, code cuts the text itself - at a word boundary, never mid-word - and the cut
is reported ("auto_trimmed: field old -> new").
"""

import re

TRAILING = " \t,;:-–—…·/|(["
SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def clean_end(text: str) -> str:
    """Drop punctuation that would dangle after a cut (a trailing comma, dash, open bracket)."""
    return text.rstrip(TRAILING)


def trim_chars(text: str, limit: int) -> str:
    """At most `limit` characters, cut at the last word boundary that fits."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[: limit + 1]
    if not text[limit].isalnum():  # the limit falls right after a word (a space or a mark follows)
        head = text[:limit]
    else:
        head = cut[: cut.rfind(" ")] if " " in cut else ""
    head = clean_end(head)
    return head if head else clean_end(text[:limit])  # one very long word: hard cut


def words_of(text: str) -> int:
    return len(text.split())


def trim_words(text: str, limit: int) -> str:
    """At most `limit` words: whole sentences from the start, else the clauses before the last
    comma that fit, else the first `limit` words. Ends with a full stop when sentences were cut."""
    text = " ".join(text.split())
    if words_of(text) <= limit:
        return text
    sentences = [s for s in SENTENCE_END.split(text) if s]
    kept: list[str] = []
    for sentence in sentences:
        if words_of(" ".join([*kept, sentence])) > limit:
            break
        kept.append(sentence)
    if kept:
        return " ".join(kept)
    first = sentences[0] if sentences else text
    clauses = first.split(",")
    while len(clauses) > 1:  # drop the last clause until it fits
        clauses.pop()
        candidate = clean_end(",".join(clauses))
        if candidate and words_of(candidate) <= limit:
            return candidate + "."
    return clean_end(" ".join(first.split()[:limit])) + "."


def trim_highlight(headline: str, highlight: str | None) -> str | None:
    """The highlight is only valid while it is still a substring of the headline."""
    return highlight if highlight and highlight in headline else None


def trim_lines(text: str, max_lines: int) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[:max_lines])
