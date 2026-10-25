"""Chapters of a flow run: the agent names the stretch each step belongs to; code turns those names
into 2-4 chapters (pure functions). A chapter must contain a step that changes the picture, so a
run of scrolls only is folded into its neighbour."""

from dataclasses import dataclass

MAX_CHAPTERS = 4
MIN_CHAPTERS = 2
MIN_SPLIT_STEPS = 4  # a single chapter of this many visual steps is cut in two
NO_CHANGE = {"scroll", "wait"}  # steps that do not change what is on screen in a way worth filming
FINAL_TITLE = "Hoàn tất"


@dataclass
class Chap:
    title: str
    step_ids: list[int]
    visual: int  # how many of its steps change the picture


def _runs(steps: list[tuple[int, str, str]]) -> list[Chap]:
    """Consecutive steps with the same suggested name form a run. steps: (i, do, name)."""
    runs: list[Chap] = []
    for i, do, name in steps:
        visual = 0 if do in NO_CHANGE else 1
        if runs and runs[-1].title == (name or runs[-1].title):
            runs[-1].step_ids.append(i)
            runs[-1].visual += visual
        else:
            runs.append(Chap(name or "Thao tác", [i], visual))
    return runs


def _merge(a: Chap, b: Chap) -> Chap:
    keep = a if len(a.step_ids) >= len(b.step_ids) else b  # the bigger one names the chapter
    return Chap(keep.title, [*a.step_ids, *b.step_ids], a.visual + b.visual)


def group_chapters(steps: list[tuple[int, str, str]]) -> list[Chap]:
    """steps: (step index, action name, suggested chapter name) in order."""
    runs = _runs(steps)
    # a run without a visual step folds into the previous one (the first one into the next)
    k = 0
    while k < len(runs) and len(runs) > 1:
        if runs[k].visual == 0:
            j = k - 1 if k > 0 else k + 1
            lo, hi = sorted((k, j))
            runs[lo : hi + 1] = [_merge(runs[lo], runs[hi])]
            k = max(0, lo - 1)
        else:
            k += 1
    while len(runs) > MAX_CHAPTERS:  # join the adjacent pair with the fewest steps
        best = min(
            range(len(runs) - 1), key=lambda n: len(runs[n].step_ids) + len(runs[n + 1].step_ids)
        )
        runs[best : best + 2] = [_merge(runs[best], runs[best + 1])]
    if len(runs) == 1 and runs[0].visual >= MIN_SPLIT_STEPS:
        only = runs[0]
        cut = len(only.step_ids) // 2
        runs = [
            Chap(only.title, only.step_ids[:cut], max(1, only.visual // 2)),
            Chap(FINAL_TITLE, only.step_ids[cut:], max(1, only.visual - only.visual // 2)),
        ]
    return runs


def chapter_ids(chapters: list[Chap]) -> dict[int, str]:
    """Step index -> chapter id (c1, c2...)."""
    return {s: f"c{n}" for n, c in enumerate(chapters, start=1) for s in c.step_ids}
