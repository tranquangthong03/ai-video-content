"""Word limits checked by code, not just asked of the LLM: beats <= 15 words, hook <= 12 words.

Lines over the limit go back to the LLM once to be shortened; whatever is still too long is cut
at the limit and a warning is recorded.
"""

import json

from pydantic import BaseModel

from app.llm.json_call import JsonCaller, LLMCallError
from app.llm.prompts import render
from app.schemas.generated.outline import Outline
from app.schemas.generated.video_concept import VideoConcept

BEAT_MAX_WORDS = 15
HOOK_MAX_WORDS = 12


class ShortLine(BaseModel):
    id: str
    text: str


class ShortLines(BaseModel):
    lines: list[ShortLine]


def word_count(text: str) -> int:
    return len(text.split())


def cut_words(text: str, limit: int) -> str:
    """Keep the first `limit` words (last resort when the LLM did not shorten enough)."""
    return " ".join(text.split()[:limit]).rstrip(",;:-— ")


def shorten(
    caller: JsonCaller, lines: dict[str, tuple[str, int]], step: str
) -> tuple[dict[str, str], list[str]]:
    """lines: id -> (text, max_words). Returns (replacement text per too-long id, warnings)."""
    over = {k: (t, m) for k, (t, m) in lines.items() if word_count(t) > m}
    if not over:
        return {}, []
    warnings: list[str] = []
    suggestions: dict[str, str] = {}
    payload = [{"id": k, "text": t, "max_words": m} for k, (t, m) in over.items()]
    try:
        prompt = render("shortener", lines_json=json.dumps(payload, ensure_ascii=False, indent=1))
        suggestions = {s.id: s.text for s in caller.call(step, prompt, ShortLines).lines}
    except LLMCallError as e:
        warnings.append(f"không rút gọn được bằng LLM ({e}); cắt cứng theo giới hạn từ")
    result: dict[str, str] = {}
    for key, (text, limit) in over.items():
        candidate = suggestions.get(key, "").strip()
        if candidate and word_count(candidate) <= limit:
            result[key] = candidate
        else:
            result[key] = cut_words(candidate or text, limit)
            warnings.append(f"{key}: vẫn quá {limit} từ sau khi rút gọn, đã cắt")
    return result, warnings


def enforce_concepts(caller: JsonCaller, concepts: list[VideoConcept]) -> list[str]:
    """Shorten hook_example (<= 12 words) and beats (<= 15) of every concept, in place."""
    lines: dict[str, tuple[str, int]] = {}
    for c in concepts:
        lines[f"{c.id}.hook"] = (c.hook_example, HOOK_MAX_WORDS)
        for i, beat in enumerate(c.beats):
            lines[f"{c.id}.beat{i}"] = (beat, BEAT_MAX_WORDS)
    fixed, warnings = shorten(caller, lines, "concepts")
    for c in concepts:
        c.hook_example = fixed.get(f"{c.id}.hook", c.hook_example)
        c.beats = [fixed.get(f"{c.id}.beat{i}", b) for i, b in enumerate(c.beats)]
    return warnings


def enforce_outline(caller: JsonCaller, outline: Outline) -> tuple[list[str], list[str]]:
    """Shorten beats over 15 words in place. Returns (changes, warnings)."""
    fixed, warnings = shorten(
        caller, {b.id: (b.text, BEAT_MAX_WORDS) for b in outline.beats}, "outline"
    )
    changes = []
    for beat in outline.beats:
        if beat.id in fixed:
            changes.append(f"Rút gọn {beat.id}: «{beat.text}» → «{fixed[beat.id]}»")
            beat.text = fixed[beat.id]
    return changes, warnings
