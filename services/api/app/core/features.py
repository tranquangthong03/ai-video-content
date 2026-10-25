"""Feature housekeeping shared by the explorer and the proposal steps (pure functions).

merge_duplicates: features that stand for the same user intent become one. default_selection:
the 2-3 features worth demoing, pre-selected for select_features. check_selection: validates the
ordered id list the user answers with.
"""

import re
import unicodedata
from urllib.parse import urlsplit

from app.schemas.generated.product_profile import Feature, ProductProfile

MIN_SELECTED = 1
MAX_SELECTED = 4
RECOMMENDED_MAX = 3
NAME_SIMILARITY = 0.8
ACTING_STEPS = {"click", "dblclick", "right_click", "type", "upload", "hover"}
DEMO_RANK = {"interaction": 3, "navigation": 2, "showcase": 1, "failed": 0}


def fold(text: str) -> str:
    """Lower-case, accent-free (đ included) text for comparing Vietnamese and English names."""
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", fold(text)) if t}


def name_similarity(a: str, b: str) -> float:
    """Token overlap relative to the shorter name (1.0 when one name contains the other)."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def quality(f: Feature) -> tuple[int, float, float]:
    """Sort key, best first when reversed: demo verdict, its confidence, importance."""
    rank = DEMO_RANK.get(f.demo_kind or "", -1)
    return rank, f.demo_score, f.importance


def page_of(f: Feature) -> str:
    url = f.evidence[0].url if f.evidence else ""
    parts = urlsplit(url)
    return f"{parts.netloc}{parts.path.rstrip('/')}"


def main_target(f: Feature) -> str | None:
    """What the last acting demo step works on: role + name of its locator (or its ref)."""
    for step in reversed(f.demo_steps):
        if step.do not in ACTING_STEPS:
            continue
        loc = step.locator
        if loc is not None and (loc.role or loc.name):
            return fold(f"{loc.role or ''}|{loc.name or loc.text or ''}")
        return step.ref
    return None


def weak_demo(f: Feature) -> bool:
    return f.demo_kind in ("failed", None) or not f.demo_steps


def id_stem_contains(a: Feature, b: Feature) -> bool:
    """One id is a token prefix of the other (edit_todo / edit_todo_dblclick), on the same page,
    and at least one of the two has no working demo of its own."""
    ta, tb = re.split(r"[_\-]+", fold(a.id)), re.split(r"[_\-]+", fold(b.id))
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(small) < 2 or big[: len(small)] != small:
        return False
    return page_of(a) == page_of(b) and (weak_demo(a) or weak_demo(b))


def same_intent(a: Feature, b: Feature) -> bool:
    if a.intent_key and a.intent_key == b.intent_key:
        return True
    if name_similarity(a.name, b.name) >= NAME_SIMILARITY:
        return True
    if id_stem_contains(a, b):
        return True
    ta, tb = main_target(a), main_target(b)
    return ta is not None and ta == tb and page_of(a) == page_of(b)


def merge_into(keep: Feature, other: Feature) -> None:
    """Fold other's evidence into keep (the better feature); thumbnail etc. stay keep's own."""
    seen = {(e.source, e.url, e.ref, e.quote) for e in keep.evidence}
    for e in other.evidence:
        if (e.source, e.url, e.ref, e.quote) not in seen:
            keep.evidence.append(e)
            seen.add((e.source, e.url, e.ref, e.quote))
    keep.intent_key = keep.intent_key or other.intent_key
    keep.thumbnail = keep.thumbnail or other.thumbnail


def merge_duplicates(profile: ProductProfile) -> tuple[ProductProfile, list[tuple[str, str]]]:
    """Merge same-intent features; returns (new profile, [(dropped_id, kept_id)]).

    The feature with the best demo verdict survives, the order of the first occurrence is kept.
    User-added features are never dropped in favour of a site feature.
    """
    merged = profile.model_copy(deep=True)
    kept: list[Feature] = []
    dropped: list[tuple[str, str]] = []
    for f in merged.features:
        twin = next((k for k in kept if same_intent(k, f)), None)
        if twin is None:
            kept.append(f)
            continue
        user_first = (f.source == "user") != (twin.source == "user")
        f_wins = (f.source == "user") if user_first else quality(f) > quality(twin)
        winner, loser = (f, twin) if f_wins else (twin, f)
        merge_into(winner, loser)
        kept[kept.index(twin)] = winner
        dropped.append((loser.id, winner.id))
    merged.features = kept
    return merged, dropped


def default_selection(profile: ProductProfile) -> list[str]:
    """2-3 best demonstrable features (verdict, confidence, importance); at least 2 if possible."""
    ranked = sorted(profile.features, key=quality, reverse=True)
    chosen = [f for f in ranked if f.demo_kind in ("interaction", "navigation", "showcase")]
    chosen = chosen[:RECOMMENDED_MAX]
    for f in ranked:
        if len(chosen) >= 2:
            break
        if f not in chosen:
            chosen.append(f)
    return [f.id for f in chosen]


def check_selection(profile: ProductProfile, selected: object) -> list[str]:
    """Errors (English) for an answers['selected_features'] value; empty when it is valid."""
    if not isinstance(selected, list) or not all(isinstance(s, str) for s in selected):
        return ["selected_features must be a list of feature ids"]
    errors: list[str] = []
    if not MIN_SELECTED <= len(selected) <= MAX_SELECTED:
        errors.append(f"select {MIN_SELECTED}-{MAX_SELECTED} features, got {len(selected)}")
    if len(set(selected)) != len(selected):
        errors.append("selected_features has duplicates")
    known = {f.id for f in profile.features}
    errors += [f"unknown feature id: {s}" for s in selected if s not in known]
    return errors
