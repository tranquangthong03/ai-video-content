"""End-to-end runs with the real LLM (needs DEEPSEEK_API_KEY): `uv run pytest -m e2e`."""

import json
from pathlib import Path

import pytest

from app.llm.client import load_settings
from app.pipeline.explore_cli import main

pytestmark = pytest.mark.e2e

ANSWERS = Path(__file__).parent / "fixtures" / "answers" / "default.json"


@pytest.fixture(autouse=True)
def require_key() -> None:
    try:
        load_settings()
    except RuntimeError:
        pytest.skip("DEEPSEEK_API_KEY is not set")


def run(url: str, job: Path, **flags: str) -> dict:  # type: ignore[type-arg]
    argv = ["--url", url, "--job-dir", str(job), "--auto", "--answers", str(ANSWERS),
            "--timeout", "600", "--max-tokens", "400000", "--stop-after", "outline"]  # fmt: skip
    for k, v in flags.items():
        argv += [f"--{k.replace('_', '-')}", v]
    assert main(argv) == 0
    summary = json.loads((job / "summary.json").read_text(encoding="utf-8"))
    report = json.loads((job / "explore" / "report.json").read_text(encoding="utf-8"))
    names = {c["name"] for c in report["clicks"]}
    assert not any(t in n.lower() for n in names for t in ("delete", "xóa", "buy", "pay", "logout"))
    assert (job / "outline_approved.json").is_file()
    return summary


def test_fixture_site(site: str, tmp_path: Path) -> None:
    summary = run(site + "/", tmp_path / "fixture", max_pages="8")
    assert summary["features"]


def test_todomvc(tmp_path: Path) -> None:
    summary = run("https://todomvc.com/examples/react/dist/", tmp_path / "todomvc", max_pages="8")
    assert summary["features"] and summary["pages_seen"] >= 1
