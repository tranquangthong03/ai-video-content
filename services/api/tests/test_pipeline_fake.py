"""Whole explore -> understand -> concept -> outline pipeline on the fixture site with a scripted fake LLM."""

import json
from pathlib import Path

from app.pipeline.explore_cli import main
from tests.conftest import FakeLLM, scripted_handler

ANSWERS = {
    "confirm_understanding": [
        {
            "action": "edit",
            "profile_edit": {"exclude_feature_ids": ["f_kanban"], "one_liner": "Quản lý việc gọn"},
        },
        {"action": "answer", "answers": {"oq1": "Nhóm nhỏ"}},
    ],
    "choose_concept": [{"action": "answer", "answers": {"concept_id": "recommended"}}],
    "outline_review": [
        {"action": "edit", "edit": {"instruction": "đổi mở đầu thành câu hỏi"}},
        {"action": "edit", "edit": {"instruction": "việc này mơ hồ"}},
        {"action": "approve"},
    ],
    "clarify": [{"action": "answer", "answers": {"clarify": "b2"}}],
}


def test_auto_run_produces_an_approved_outline_after_edits(
    site: str, tmp_path: Path, hits: list[str], monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    llm = FakeLLM(scripted_handler)
    monkeypatch.setattr("app.pipeline.runner.OpenAIChat", lambda settings: llm)
    monkeypatch.setattr("app.pipeline.runner.load_settings", lambda: _settings(tmp_path))
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps(ANSWERS, ensure_ascii=False), encoding="utf-8")
    job = tmp_path / "job"

    code = main(["--url", site + "/", "--job-dir", str(job), "--auto", "--answers", str(answers),
                 "--max-pages", "6", "--timeout", "180", "--stop-after", "outline"])  # fmt: skip
    assert code == 0

    state = json.loads((job / "state.json").read_text(encoding="utf-8"))  # what the web polls
    assert state["status"] == "done" and state["step"] == "done" and state["progress_pct"] == 100
    assert state["job_id"] == "job" and state["error"] is None
    assert state["latest_screenshot"].startswith("explore/pages/")

    explore = job / "explore"
    report = json.loads((explore / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "done" and report["site_type"] == "web_app"
    assert len(report["pages_seen"]) >= 3 and report["timings_s"]["verify"] >= 0
    assert set(report["tokens"]["steps"]) >= {
        "classify",
        "analyze",
        "synthesize",
        "concepts",
        "outline",
    }
    # nothing dangerous was ever clicked, and what was blocked is on the record
    assert not any(c["name"] in ("Delete", "Delete task") for c in report["clicks"])
    assert "/hit/delete" not in hits and not any("/hit/submit" in h for h in hits)
    assert any("Delete task" in n for n in report["synthesis_dropped"])

    confirmed = json.loads((job / "confirmed_profile.json").read_text(encoding="utf-8"))
    assert "f_kanban" not in {f["id"] for f in confirmed["features"]}
    assert confirmed["one_liner"] == "Quản lý việc gọn"
    by_id = {
        f["id"]: f
        for f in json.loads((explore / "profile_verified.json").read_text(encoding="utf-8"))[
            "features"
        ]
    }
    assert by_id["f_new"]["demo_kind"] == "interaction" and by_id["f_new"]["demo_score"] >= 0.5

    approved = json.loads((job / "outline_approved.json").read_text(encoding="utf-8"))
    assert approved["beats"][0]["text"] == "Bạn có đang ngập việc?"  # first edit
    assert approved["beats"][1]["text"] == "Tạo việc chỉ một cú nhấp"  # edit after a clarification
    assert approved["version"] == 3 and [b["id"] for b in approved["beats"]] == [
        "b1",
        "b2",
        "b3",
        "b4",
    ]
    assert (job / "outline_v1.json").is_file() and (job / "outline_v2.json").is_file()
    summary = json.loads((job / "summary.json").read_text(encoding="utf-8"))
    assert summary["tokens"]["steps"]["verify"]["input"] == 0  # verify makes no LLM calls
    kinds = [
        json.loads(line)["request"]["kind"]
        for line in (job / "interactions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert kinds == ["confirm_understanding", "confirm_understanding", "choose_concept",
                     "outline_review", "outline_review", "clarify", "outline_review"]  # fmt: skip


def test_resume_skips_finished_steps(site: str, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    llm = FakeLLM(scripted_handler)
    monkeypatch.setattr("app.pipeline.runner.OpenAIChat", lambda settings: llm)
    monkeypatch.setattr("app.pipeline.runner.load_settings", lambda: _settings(tmp_path))
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps(ANSWERS, ensure_ascii=False), encoding="utf-8")
    job = tmp_path / "job"
    args = [
        "--url",
        site + "/",
        "--job-dir",
        str(job),
        "--auto",
        "--answers",
        str(answers),
        "--max-pages",
        "4",
        "--stop-after",
        "outline",
    ]
    assert main(args) == 0
    calls_first = len(llm.calls)
    assert main(args) == 5  # existing job dir without --resume is refused
    assert main([*args, "--resume"]) == 0
    assert len(llm.calls) == calls_first  # every step was already on disk: no new LLM call


def test_token_ceiling_pauses_and_resume_continues(site: str, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    llm = FakeLLM(scripted_handler)
    monkeypatch.setattr("app.pipeline.runner.OpenAIChat", lambda settings: llm)
    monkeypatch.setattr("app.pipeline.runner.load_settings", lambda: _settings(tmp_path))
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps(ANSWERS, ensure_ascii=False), encoding="utf-8")
    job = tmp_path / "job"
    args = [
        "--url",
        site + "/",
        "--job-dir",
        str(job),
        "--auto",
        "--answers",
        str(answers),
        "--max-pages",
        "4",
        "--stop-after",
        "outline",
    ]
    assert main([*args, "--max-tokens", "400"]) == 3  # each fake call costs 150 tokens
    report = json.loads((job / "explore" / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "paused_token_ceiling"
    assert main([*args, "--resume", "--max-tokens", "400000"]) == 0


def test_cli_does_not_crash_on_a_non_utf8_redirected_stdout(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Windows redirects stdout with a legacy codepage; Vietnamese text must survive."""
    import io
    import sys

    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252", write_through=True))
    job = tmp_path / "job"
    job.mkdir()
    (job / "leftover.txt").write_text("x", encoding="utf-8")
    # an existing non-empty job dir without --resume prints a Vietnamese message and exits with 5
    assert main(["--url", "http://localhost:1/", "--job-dir", str(job)]) == 5
    assert "đã có dữ liệu" in raw.getvalue().decode("utf-8")


def _settings(tmp_path: Path):  # type: ignore[no-untyped-def]
    from app.llm.client import LLMSettings

    return LLMSettings("http://x", "k", "fake-text", "fake-vision", False, tmp_path / ".cache")
