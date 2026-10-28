"""No site-specific code: the product works on any website (demo sites only in the allowed files)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SITES = re.compile(r"demoblaze|orangehrm|squoosh|todomvc|aisoeasy", re.I)
ALLOWED = {"shared_demo.py", "sample-urls.ts"}  # the shared-demo list, the sample URLs of the form
SCAN = [
    (ROOT / "services/api/app", {".py", ".md", ".json"}),
    (ROOT / "apps/render/src", {".ts", ".tsx"}),
    (ROOT / "apps/web/lib", {".ts", ".tsx"}),
    (ROOT / "apps/web/components", {".ts", ".tsx"}),
    (ROOT / "apps/web/app", {".ts", ".tsx"}),
]


def test_no_site_names_in_the_code_or_the_prompts() -> None:
    found = []
    for folder, suffixes in SCAN:
        for path in folder.rglob("*") if folder.is_dir() else []:
            if (
                path.suffix not in suffixes
                or path.name in ALLOWED
                or "generated" in path.parts
                or "__pycache__" in path.parts
                or "node_modules" in path.parts
                or ".test." in path.name
            ):
                continue
            for n, line in enumerate(
                path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
            ):
                if SITES.search(line):
                    found.append(f"{path.relative_to(ROOT)}:{n}")
    assert not found, found
