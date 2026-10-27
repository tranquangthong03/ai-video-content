"""Hero frame: the frame of the filmed flow that best shows the result (pure, from the frame
inventory; no model looks at pixels). The writer reads its texts, the producer cuts around it."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

MIN_CHARS, MAX_CHARS = 80, 900  # a readable amount of text: not empty, not a wall
NOTABLE_KINDS = ("heading", "list_item", "card", "button", "input")
MAX_NOTABLE, MAX_TEXT = 8, 60
DATA_KINDS = ("list_item", "card")
LAST_SNAPSHOT_BONUS = 3.0  # the climax of a flow is near its end


@dataclass(frozen=True)
class Hero:
    t_ms: int
    score: float
    texts: tuple[str, ...]  # the prominent texts shown on that frame


def _items(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [i for i in snapshot.get("items", []) if str(i.get("text", "")).strip()]


def score_snapshot(snapshot: dict[str, Any], position: float) -> float:
    """Higher = a better hero. `position` is 0..1 along the flow (0 first snapshot, 1 last)."""
    items = _items(snapshot)
    chars = sum(
        len(str(i["text"])) for i in items if i.get("kind") in NOTABLE_KINDS + ("paragraph",)
    )
    score = 2.0 * sum(1 for i in items if i.get("is_new"))  # what just appeared
    score += min(
        6, sum(1 for i in items if i.get("kind") in DATA_KINDS)
    )  # a list / table with data
    score += min(3, sum(1 for i in items if i.get("kind") == "input"))  # a form that is there
    score += 3.0 * min(3, sum(1 for i in items if i.get("filled")))  # ... and filled in
    score += 1.0 if any(i.get("kind") == "heading" for i in items) else 0.0
    score += 2.0 if MIN_CHARS <= chars <= MAX_CHARS else -2.0
    return score + LAST_SNAPSHOT_BONUS * position


def notable_texts(snapshot: dict[str, Any]) -> tuple[str, ...]:
    out: list[str] = []
    for kind in NOTABLE_KINDS:
        for i in _items(snapshot):
            text = " ".join(str(i["text"]).split())[:MAX_TEXT]
            if i.get("kind") == kind and text not in out and len(out) < MAX_NOTABLE:
                out.append(text)
    return tuple(out)


HOOK_MIN_MS, HOOK_MAX_MS, HOOK_LEAD_MS = 1500, 2500, 800


def hero_window(t_ms: int, content_ms: int) -> tuple[int, int]:
    """The 1.5-2.5 s of the flow clip around the hero frame: a little before it, mostly after."""
    length = min(HOOK_MAX_MS, max(HOOK_MIN_MS, 2000), content_ms)
    a = max(0, min(t_ms - HOOK_LEAD_MS, content_ms - length))
    return a, a + length


MIN_PAIR_GAP_MS = 2000  # the frames must be this far apart in the flow
MAX_PAIR_SIMILARITY = 0.8  # share of texts the two frames have in common, at most
MIN_NEW_TEXTS = 2  # texts the hero frame shows that the first one did not


def _texts(snapshot: dict[str, Any]) -> set[str]:
    return {" ".join(str(i["text"]).split()).casefold() for i in _items(snapshot)}


def before_after_pair(
    inventory: Sequence[dict[str, Any]], hero_t_ms: int, *, from_ms: int = 0
) -> tuple[int, int] | None:
    """(before t_ms, after t_ms) when the first frame of the flow and the hero frame make a real
    before/after: far enough apart, and the hero shows something the first one does not."""
    usable = [s for s in inventory if int(s.get("t_ms", 0)) >= from_ms and _items(s)]
    hero = next((s for s in usable if int(s["t_ms"]) == hero_t_ms), None)
    if not usable or hero is None:
        return None
    first = usable[0]
    if hero_t_ms - int(first["t_ms"]) < MIN_PAIR_GAP_MS:
        return None
    a, b = _texts(first), _texts(hero)
    if len(b - a) < MIN_NEW_TEXTS or len(a & b) / len(a | b) > MAX_PAIR_SIMILARITY:
        return None
    return int(first["t_ms"]), hero_t_ms


HERO_KINDS = ("heading", "card", "list_item", "button", "input")
EXCLUDED_REGIONS = {"nav", "aside", "footer"}
EXCLUDED_KINDS = {"sidebar", "nav", "footer"}


def hero_item(items: list[dict[str, Any]], clip: tuple[int, int]) -> dict[str, Any] | None:
    """The most telling item of a frame: what just appeared first, then headings and data."""
    view = float(clip[0] * clip[1])
    pool = [
        i
        for i in items
        if i.get("text")
        and i["kind"] in HERO_KINDS
        and i.get("region") not in EXCLUDED_REGIONS
        and i["kind"] not in EXCLUDED_KINDS
        and i["bbox"]["w"] * i["bbox"]["h"] <= 0.5 * view
    ]
    if not pool:
        return None
    return min(pool, key=lambda i: (not i.get("is_new"), HERO_KINDS.index(i["kind"])))


def choose_hero(inventory: Sequence[dict[str, Any]], *, from_ms: int = 0) -> Hero | None:
    """The best snapshot at or after `from_ms`; ties go to the later one."""
    usable = [s for s in inventory if int(s.get("t_ms", 0)) >= from_ms and _items(s)]
    if not usable:
        return None
    last = max(len(inventory) - 1, 1)
    best = max(
        enumerate(usable),
        key=lambda p: (score_snapshot(p[1], inventory.index(p[1]) / last), p[0]),
    )[1]
    return Hero(
        int(best["t_ms"]), score_snapshot(best, inventory.index(best) / last), notable_texts(best)
    )
