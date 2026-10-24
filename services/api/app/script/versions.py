"""Script versions on disk: out/<job>/scripts/v{n}.json. Versions are never edited or deleted."""

import json
from pathlib import Path

from app.schemas.generated.script import Script


class ScriptStore:
    def __init__(self, job_dir: Path) -> None:
        self.dir = job_dir / "scripts"

    def _path(self, version: int) -> Path:
        return self.dir / f"v{version}.json"

    def versions(self) -> list[int]:
        if not self.dir.is_dir():
            return []
        found = [int(p.stem[1:]) for p in self.dir.glob("v*.json") if p.stem[1:].isdigit()]
        return sorted(found)

    def latest(self) -> int | None:
        found = self.versions()
        return found[-1] if found else None

    def save(self, script: Script) -> int:
        """Store `script` as the next version and return its number."""
        self.dir.mkdir(parents=True, exist_ok=True)
        version = (self.latest() or 0) + 1
        self._path(version).write_text(
            json.dumps(script.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return version

    def load(self, version: int) -> Script:
        path = self._path(version)
        if not path.is_file():
            raise KeyError(f"không có bản v{version}")
        return Script.model_validate_json(path.read_text(encoding="utf-8"))

    def revert(self, version: int) -> int:
        """Copy an old version as a new one (history stays linear and complete)."""
        return self.save(self.load(version))
