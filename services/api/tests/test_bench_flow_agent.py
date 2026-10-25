import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bench_flow_agent as bench  # noqa: E402

from tests.test_flow_storyboard import make_run  # noqa: E402


def test_the_goal_must_really_be_reached_not_only_claimed() -> None:
    stopped = make_run()  # stopped_before_submit; its stop button is not set
    assert not bench.reached("fixture", stopped)
    stopped.stop_ref = "Apply"
    assert bench.reached("fixture", stopped) and bench.reached("orangehrm", stopped)
    stopped.stop_ref = "Cancel"
    assert not bench.reached("fixture", stopped)
    todo = make_run("reached_goal", tail=False)
    assert not bench.reached("todomvc", todo)  # claimed, but one 'type' and no tick


def test_the_configurations_are_text_only_and_with_screenshots() -> None:
    assert bench.CONFIGS["text"] == {
        "LLM_FLOW_AGENT_MODEL": "deepseek-chat", "LLM_FLOW_AGENT_VISION": "false",
    }  # fmt: skip
    assert bench.CONFIGS["vision"]["LLM_FLOW_AGENT_VISION"] == "true"


def rows() -> list[dict[str, Any]]:
    def r(config: str, rep: int, ok: bool, **kw: Any) -> dict[str, Any]:
        base = {"flow": "fixture", "config": config, "rep": rep, "success": ok, "status": "partial",
                "actions": 6, "repeat_warnings": 0, "invented_refs": 0, "llm_calls": 7,
                "seconds": 30.0, "tokens": 9000, "warnings": []}  # fmt: skip
        return {**base, **kw}

    return [
        r(
            "text",
            1,
            False,
            repeat_warnings=2,
            warnings=["pick_date «To Date»: không tìm lại được", "Dừng: «scroll:» lặp 3 lần"],
        ),
        r("text", 2, True, status="stopped_before_submit"),
        r("vision", 1, True, status="stopped_before_submit", tokens=15000, seconds=40.0),
        r("vision", 2, False, warnings=["pick_date «To Date»: không tìm lại được"]),
    ]


def test_summary_and_the_most_common_stuck_steps() -> None:
    s = bench.summary([r for r in rows() if r["config"] == "text"])
    assert (s["runs"], s["success"], s["repeat"], s["tokens"]) == (2, 1, 2, 9000)
    stuck = bench.stuck_steps(rows())
    assert stuck[0][:2] == ("pick_date «To Date»", 2)  # two runs, in both configurations
    assert any("lặp N lần" in k for k, _, _ in stuck)


def test_the_report_has_the_table_the_stuck_list_and_the_outcomes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "bench").mkdir()
    (tmp_path / "bench" / "fixture.json").write_text(json.dumps(rows()), encoding="utf-8")
    monkeypatch.setattr(bench, "OUT", tmp_path / "bench")
    monkeypatch.setattr(bench, "DOCS", tmp_path / "docs")
    bench.report()
    text = (tmp_path / "docs" / "llm-benchmark.md").read_text(encoding="utf-8")
    assert "| fixture | text | 1/2 |" in text and "| tổng | vision | 1/2 |" in text
    assert "pick_date «To Date» — 1 lần chạy" in text and "stopped_before_submit" in text


def test_a_tick_by_click_counts_for_todomvc_but_the_filter_alone_does_not() -> None:
    run = make_run("reached_goal", tail=False)
    steps = [
        ("goto", None),
        ("type", "New"),
        ("type", "New"),
        ("type", "New"),
        ("click", "Mua sữa"),
        ("click", "Active"),
    ]
    run.steps = [
        run.steps[0].model_copy(
            update={
                "i": i,
                "action": run.steps[0].action.model_copy(update={"do": do}),
                "target_text": t,
            }
        )
        for i, (do, t) in enumerate(steps, start=1)
    ]
    assert bench.reached("todomvc", run)
    run.steps[4].target_text = "Active"  # no tick: only the filter was pressed
    assert not bench.reached("todomvc", run)
