"""Full-screen text cards: scenes with no picture of the product, only words.

A card lasts at most 3 s and all the cards together at most 15 % of the video. Pure numbers for
the report and the scorecard; a flow video is made of footage, so this normally stays at zero.
"""

MAX_CARD_MS = 3000
MAX_CARDS_SHARE = 0.15
TEXT_KIND = "chữ"  # SceneOutcome.kind of a scene without any footage or picture


def text_card_stats(scenes: list[tuple[str, int]]) -> dict[str, float | int | bool]:
    """From (scene kind, duration ms): how many cards, the longest, their share, and whether the
    limits hold."""
    cards = [ms for kind, ms in scenes if kind == TEXT_KIND]
    total = sum(ms for _, ms in scenes)
    longest = max(cards, default=0)
    share = round(sum(cards) / total, 3) if total else 0.0
    return {
        "count": len(cards),
        "longest_ms": longest,
        "ratio": share,
        "ok": longest <= MAX_CARD_MS and share <= MAX_CARDS_SHARE,
    }
