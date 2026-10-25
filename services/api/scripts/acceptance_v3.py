"""Run one site through run_job with a fixed feature selection (docs/visual-v3 acceptance).

Usage (from services/api):
  uv run python scripts/acceptance_v3.py <aisoeasy|todomvc|squoosh> <job-dir>

The select_features step is answered like a user would: for every wanted feature (matched by
keywords in its name or description, accents ignored) pick it; when the list has none, ask
"explore more" with a description, then pick what turned up. Every other question gets the default
answer of --auto. Prints which features were picked (and which could not be found).
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # services/api, for `app`

from rich.console import Console  # noqa: E402

from app.core.features import fold  # noqa: E402
from app.core.interaction import make_response  # noqa: E402
from app.pipeline.explore_cli import ConsoleReporter  # noqa: E402
from app.pipeline.frontend import ScriptedFrontend  # noqa: E402
from app.pipeline.runner import JobConfig, run_job  # noqa: E402
from app.schemas.generated.interaction import InteractionRequest  # noqa: E402
from app.schemas.generated.user_response import UserResponse  # noqa: E402


def has_all(text: str, keyword: str) -> bool:
    """Every word of `keyword` occurs in `text` (accents and case ignored)."""
    haystack = fold(text)
    return all(w in haystack for w in keyword.split())


@dataclass
class Want:
    label: str
    keywords: list[str]
    explore: str  # what to ask for when the list does not have it
    asked: bool = False
    picked: str | None = None


@dataclass
class Site:
    url: str
    wants: list[Want]
    fill_to: int = 0  # pick this many in all (others come from the preselected defaults)


SITES = {
    "aisoeasy": Site(
        "https://aisoeasy.co/",
        [
            Want(
                "Lộ trình theo vai trò / Learning Paths",
                ["lo trinh", "learning path", "vai tro", "role"],
                "Lộ trình học theo vai trò (Learning Paths)",
            )
        ],
        fill_to=2,
    ),
    "todomvc": Site(
        "https://todomvc.com/examples/react/dist/",
        [
            Want(
                "Thêm việc",
                ["them viec", "tao viec", "them cong viec", "create", "add"],
                "Thêm việc cần làm mới",
            ),
            Want(
                "Sửa việc",
                ["sua viec", "sua noi dung", "chinh sua", "edit"],
                "Sửa một việc đã thêm",
            ),
        ],
    ),
    "squoosh": Site(
        "https://squoosh.app/",
        [
            Want("Nén ảnh", ["nen anh", "compress", "nen "], "Nén ảnh"),
            Want(
                "So sánh trước/sau",
                ["so sanh", "compare", "truoc", "before", "after", "slider"],
                "So sánh ảnh trước và sau khi nén",
            ),
        ],
    ),
}


class PickingFrontend(ScriptedFrontend):
    def __init__(self, site: Site, console: Console) -> None:
        super().__init__({}, console)
        self.site = site
        self.log: list[str] = []

    def ask(self, request: InteractionRequest) -> UserResponse:
        if (
            request.kind != "select_features"
            or request.profile is None
            or request.selection is None
        ):
            return super().ask(request)
        features = request.profile.features
        picked: list[str] = []
        for want in self.site.wants:
            found = next(
                (
                    f
                    for f in features
                    if f.id not in picked
                    and any(has_all(f"{f.id} {f.name} {f.description}", k) for k in want.keywords)
                ),
                None,
            )
            if found is None and not want.asked:
                want.asked = True
                self.log.append(f"explore_more: {want.explore}")
                return make_response(
                    request, "explore_more", explore={"urls": [], "description": want.explore}
                )
            if found is not None:
                want.picked = found.id
                picked.append(found.id)
            else:
                self.log.append(f"NOT FOUND: {want.label}")
        for fid in request.selection.default:  # the "other" features come from the defaults
            if len(picked) >= self.site.fill_to:
                break
            if fid not in picked:
                picked.append(fid)
        self.log.append("selected: " + ", ".join(picked))
        return make_response(request, "answer", answers={"selected_features": picked})


def main() -> int:
    name, job_dir = sys.argv[1], Path(sys.argv[2])
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    site = SITES[name]
    from_script = len(sys.argv) > 3 and sys.argv[3] == "script"  # rerun from the script step
    cfg = JobConfig(
        url=site.url, job_dir=job_dir, max_pages=15, timeout=900,
        from_step="script" if from_script else "explore", resume=from_script,
    )  # fmt: skip
    console = Console()
    frontend = PickingFrontend(site, console)
    result = run_job(cfg, frontend, ConsoleReporter(console))
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "acceptance_selection.json").write_text(
        json.dumps({"site": name, "log": frontend.log}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\n".join(frontend.log))
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
