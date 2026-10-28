"""Golden snapshots: what is needed to rerun the script / produce steps with no LLM and no browser.

Usage (from services/api):
  uv run python scripts/golden.py build      # out/cam-* jobs -> tests/golden (+ golden-media)
  uv run python scripts/golden.py restore    # rebuild golden-media/ from out/cam-*

`tests/golden/<name>/` holds the small JSON files (in git); `tests/golden-media/<name>/` holds the
video clips and pictures (NOT in git, see tests/golden/README.md).
"""

import argparse
import shutil
import sys
from pathlib import Path

API = Path(__file__).resolve().parents[1]
GOLDEN = API / "tests" / "golden"
MEDIA = API / "tests" / "golden-media"
NAMES = ("orangehrm", "squoosh", "todomvc")

# files copied as they are (relative to a job dir); a trailing /* means every file of that kind
JSON_FILES = (
    "confirmed_profile.json",
    "outline_approved.json",
    "script_approved.json",
    "script_report.json",
    "selected_flow.json",
    "flow_context.json",
    "theme.json",
    "theme_report.json",
    "report.json",
    "flow/flow_approved.json",
    "flow/flow_run.json",
    "flow/live/logs.json",
    "produce/render_props.json",
)
JSON_GLOBS = ("explore/pages/*.json", "produce/inventory/*.json", "produce/focus/*.json")
MEDIA_FILES = ("flow/live/flow.mp4", "video.mp4")
MEDIA_GLOBS = ("flow/steps/*", "produce/*.mp4", "produce/*.png")


def _files(job: Path, names: tuple[str, ...], globs: tuple[str, ...]) -> list[Path]:
    found = [job / n for n in names if (job / n).is_file()]
    for pattern in globs:
        found += sorted(p for p in job.glob(pattern) if p.is_file())
    return found


def copy_set(job: Path, dest: Path, names: tuple[str, ...], globs: tuple[str, ...]) -> int:
    count = 0
    for src in _files(job, names, globs):
        target = dest / src.relative_to(job)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        count += 1
    return count


def build(name: str, job: Path) -> tuple[int, int]:
    """Snapshot one job dir; returns (json files, media files)."""
    for root in (GOLDEN / name, MEDIA / name):
        shutil.rmtree(root, ignore_errors=True)
    return (
        copy_set(job, GOLDEN / name, JSON_FILES, JSON_GLOBS),
        copy_set(job, MEDIA / name, MEDIA_FILES, MEDIA_GLOBS),
    )


def restore_media(name: str) -> bool:
    """Make golden-media/<name> exist, from the job dir out/cam-<name> when it is missing."""
    if (MEDIA / name / "flow" / "live" / "flow.mp4").is_file():
        return True
    job = API / "out" / f"cam-{name}"
    if not job.is_dir():
        return False
    return copy_set(job, MEDIA / name, MEDIA_FILES, MEDIA_GLOBS) > 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["build", "restore"])
    args = p.parse_args()
    for name in NAMES:
        if args.action == "build":
            job = API / "out" / f"cam-{name}"
            print(name, "json/media files:", *build(name, job))
        else:
            print(name, "media", "ok" if restore_media(name) else "MISSING (no out/ job either)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
