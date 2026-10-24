"""Speech timing without TTS: estimates from word counts, behind an interface a TTS can replace.

`SpeechTiming` is what the rest of the pipeline consumes (scene duration, caption words). Today it
comes from `EstimatedTimer`; a TTS provider returning real word timestamps implements `SpeechTimer`
and nothing else has to change.
"""

import re
from dataclasses import asdict, dataclass, field
from typing import Protocol

WORDS_PER_SECOND = 2.5
MIN_SPEECH_MS = 1500
PAUSE_MS = 250
GROUP_MIN, GROUP_MAX = 3, 5
_BREAK = re.compile(r"[.,;:!?…]+[\"')\]]*$")


@dataclass(frozen=True)
class TimedWord:
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class SpeechTiming:
    duration_ms: int  # speech plus the closing pause
    words: list[TimedWord] = field(default_factory=list)  # relative to the speech start


class SpeechTimer(Protocol):
    def timing(self, text: str) -> SpeechTiming: ...


def split_words(text: str) -> list[str]:
    return text.split()


def estimate_speech_ms(text: str) -> int:
    """Words / 2.5 per second (at least 1500 ms) plus a 250 ms pause."""
    seconds = len(split_words(text)) / WORDS_PER_SECOND
    return max(MIN_SPEECH_MS, round(seconds * 1000)) + PAUSE_MS


def _weights(words: list[str]) -> list[int]:
    return [max(1, len(re.sub(r"\W", "", w))) for w in words]


def _spread(words: list[str], start_ms: int, end_ms: int) -> list[TimedWord]:
    """Time per word proportional to its length; the last word ends exactly at end_ms."""
    weights = _weights(words)
    span = max(0, end_ms - start_ms)
    total = sum(weights)
    out: list[TimedWord] = []
    acc = 0
    cursor = start_ms
    for i, (word, weight) in enumerate(zip(words, weights, strict=True)):
        acc += weight
        end = end_ms if i == len(words) - 1 else start_ms + round(span * acc / total)
        out.append(TimedWord(word, cursor, end))
        cursor = end
    return out


def _group(words: list[str]) -> list[list[str]]:
    """Groups of 3-5 words, closing a group at punctuation once it has at least 3 words."""
    groups: list[list[str]] = []
    current: list[str] = []
    for word in words:
        current.append(word)
        if len(current) >= GROUP_MAX or (len(current) >= GROUP_MIN and _BREAK.search(word)):
            groups.append(current)
            current = []
    if current:
        if groups and len(current) < GROUP_MIN:
            last = groups[-1]
            if len(last) + len(current) <= GROUP_MAX:
                last.extend(current)
            else:  # rebalance: move words from the previous group so that both have >= 3
                need = GROUP_MIN - len(current)
                current = last[-need:] + current
                del last[-need:]
                groups.append(current)
        else:
            groups.append(current)
    return groups


def estimate_captions(text: str, start_ms: int, end_ms: int) -> list[dict]:  # type: ignore[type-arg]
    """Caption groups (3-5 words) with per-word times, in the shape the renderer's karaoke expects.

    Time is spread over [start_ms, end_ms] by character count. Texts with fewer than 3 words give
    one short group.
    """
    words = split_words(text)
    if not words:
        return []
    timed = _spread(words, start_ms, end_ms)
    captions: list[dict] = []  # type: ignore[type-arg]
    index = 0
    for group in _group(words):
        chunk = timed[index : index + len(group)]
        index += len(group)
        captions.append(
            {
                "text": " ".join(group),
                "start_ms": chunk[0].start_ms,
                "end_ms": chunk[-1].end_ms,
                "words": [asdict(w) for w in chunk],
            }
        )
    return captions


class EstimatedTimer:
    """SpeechTimer based on word counts; replace with a TTS-backed timer later."""

    def timing(self, text: str) -> SpeechTiming:
        duration = estimate_speech_ms(text)
        speech_end = max(1, duration - PAUSE_MS)
        return SpeechTiming(duration, _spread(split_words(text), 0, speech_end))
