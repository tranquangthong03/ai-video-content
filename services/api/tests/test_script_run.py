import json
from pathlib import Path
from typing import Any

import pytest

from app.llm.json_call import JsonCaller
from app.pipeline.explore_cli import main
from app.pipeline.frontend import ScriptedFrontend
from app.pipeline.proposal_run import Cancelled
from app.pipeline.script_run import ScriptRunner
from app.schemas.generated.script import Script
from app.script.theme import ThemeResult
from app.script.versions import ScriptStore
from tests.conftest import FakeLLM
from tests.test_script_writer import (
    THEME,
    good_output,
    good_scene,
    make_outline,
    make_profile,
    words,
)


def fixed_output(voice_words: int = 22) -> dict[str, Any]:
    out = good_output()
    for scene in out["script"]["scenes"]:
        scene["voiceover"] = words(voice_words, "w")
    return out


class Handler:
    """Stand-in for every LLM role the script step uses."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.writer_calls = 0
        self.plan: dict[str, Any] = {"status": "ok", "ops": []}
        self.plans: list[dict[str, Any]] = []  # answers in order, before falling back to `plan`
        self.scene: dict[str, Any] | None = None

    def __call__(self, prompt: str) -> dict[str, Any]:
        self.prompts.append(prompt)
        if prompt.startswith("Bạn là biên kịch short video marketing (TikTok"):
            self.writer_calls += 1
            out = fixed_output()
            if self.writer_calls > 1:  # a regeneration reads differently
                out["script"]["scenes"][0]["voiceover"] = words(22, f"regen{self.writer_calls}")
            return out
        if prompt.startswith('Bạn là "Edit Planner"'):
            return self.plans.pop(0) if self.plans else self.plan
        if prompt.startswith("Bạn là biên kịch short video marketing. Nhiệm vụ"):
            return {"scene": self.scene}
        if prompt.startswith("Bạn là trợ lý biên tập video"):
            return {
                "mapping": [
                    {"beat_id": "b2", "feature_id": "create", "confidence": 0.9, "reason": "r"},
                    {"beat_id": "b3", "feature_id": "filter", "confidence": 0.9, "reason": "r"},
                ]
            }
        raise AssertionError(f"unexpected prompt: {prompt[:70]!r}")


def build(
    tmp_path: Path,
    answers: dict[str, list[dict[str, Any]]],
    handler: Handler | None = None,
    outline=None,
):  # type: ignore[no-untyped-def]
    handler = handler or Handler()
    llm = FakeLLM(handler)
    caller = JsonCaller(llm, cache_dir=tmp_path / "cache")
    frontend = ScriptedFrontend(answers)
    theme_calls: list[int] = []

    def theme_fn() -> ThemeResult:
        theme_calls.append(1)
        return ThemeResult(THEME, "css", "css", None, [{"color": "#4f46e5", "area": 1}], [])

    job = tmp_path / "job"
    job.mkdir(exist_ok=True)
    runner = ScriptRunner(
        "job1", job, caller, frontend, make_profile(), outline or make_outline(), "https://todo.example/",
        theme_fn=theme_fn,
    )  # fmt: skip
    return runner, handler, frontend, job, theme_calls


def requests(job: Path) -> list[dict[str, Any]]:
    lines = (job / "interactions.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(x) for x in lines]


def test_approve_right_away_writes_version_report_and_approved_script(tmp_path: Path) -> None:
    runner, handler, _, job, theme_calls = build(
        tmp_path, {"script_review": [{"action": "approve"}]}
    )
    script = runner.run()
    assert isinstance(script, Script) and script.template == "desktop_focus"
    assert (job / "scripts" / "v1.json").is_file() and (job / "script_approved.json").is_file()
    assert (job / "theme.json").is_file() and theme_calls == [1]
    report = json.loads((job / "script_report.json").read_text(encoding="utf-8"))
    assert report["approved"] is True and report["theme"]["source"] == "css"
    assert report["fit"]["target_ms"] == 45000 and report["fit"]["within_tolerance"] is True
    assert report["generation"]["attempts"] == 1 and report["versions"] == [1]
    first = requests(job)[0]["request"]
    assert first["kind"] == "script_review" and first["script_version"] == 1
    assert first["allowed_actions"] == ["approve", "edit", "regenerate", "revert", "cancel"]
    assert [s["scene_id"] for s in first["summary"]] == ["s1", "s2", "s3", "s4", "s5"]
    assert (
        "[quay thao tác]" in first["summary"][1]["one_liner"]
        and "[ảnh]" in first["summary"][0]["one_liner"]
    )
    assert handler.writer_calls == 1


def test_a_free_text_edit_makes_version_2_touching_only_the_target_scene(tmp_path: Path) -> None:
    handler = Handler()
    handler.plan = {
        "status": "ok",
        "ops": [
            {
                "op": "rewrite",
                "scene_id": "s3",
                "fields": ["voiceover"],
                "instruction": "ngắn gọn hơn",
            }
        ],
    }
    handler.scene = good_scene(3, "feature_demo", feature="filter", voiceover=words(22, "mới"))
    answers = {
        "script_review": [
            {"action": "edit", "edit": {"instruction": "scene 3: ngắn gọn hơn"}},
            {"action": "approve"},
        ]
    }
    runner, _, _, job, _ = build(tmp_path, answers, handler)
    script = runner.run()
    store = ScriptStore(job)
    assert store.versions() == [1, 2]
    v1, v2 = store.load(1), store.load(2)
    assert [s.root.voiceover for i, s in enumerate(v2.scenes) if i != 2] == [
        s.root.voiceover for i, s in enumerate(v1.scenes) if i != 2
    ]
    assert v2.scenes[2].root.voiceover.startswith("mới0") and script == v2
    second = requests(job)[1]["request"]  # the review after the edit
    assert second["script_version"] == 2
    assert any("Scene s3: đổi lời đọc" in c for c in second["changes"])


def test_quick_set_ops_and_a_new_primary_color(tmp_path: Path) -> None:
    ops = [
        {
            "op": "set",
            "scene_id": "s1",
            "field": "voiceover",
            "value": "Câu mở đầu do tôi tự viết ra",
        },
        {"op": "set_theme", "field": "primary", "value": "#0f766e"},
    ]
    answers = {"script_review": [{"action": "edit", "edit": {"ops": ops}}, {"action": "approve"}]}
    runner, handler, _, job, _ = build(tmp_path, answers)
    script = runner.run()
    assert script.scenes[0].root.voiceover == "Câu mở đầu do tôi tự viết ra"
    assert script.theme.primary == "#0F766E"
    assert not any(
        p.startswith('Bạn là "Edit Planner"') for p in handler.prompts
    )  # no planner call
    changes = requests(job)[1]["request"]["changes"]
    assert any("Đổi màu chủ đạo: #4F46E5 → #0F766E" in c for c in changes)


def test_a_clarification_is_asked_and_the_answer_is_used(tmp_path: Path) -> None:
    handler = Handler()
    plans = [
        {
            "status": "needs_clarification",
            "clarification": {
                "question": "Sửa scene nào?",
                "options": [{"id": "s2", "label": "Scene 2"}, {"id": "s3", "label": "Scene 3"}],
            },
        },
        {
            "status": "ok",
            "ops": [
                {"op": "set", "scene_id": "s3", "field": "on_screen_text", "value": "Lọc nhanh"}
            ],
        },
    ]
    handler.plans = plans
    answers = {
        "script_review": [
            {"action": "edit", "edit": {"instruction": "sửa đoạn demo"}},
            {"action": "approve"},
        ],
        "clarify": [{"action": "answer", "answers": {"clarify": "s3"}}],
    }
    runner, _, _, job, _ = build(tmp_path, answers, handler)
    script = runner.run()
    assert script.scenes[2].root.on_screen_text == "Lọc nhanh"
    kinds = [r["request"]["kind"] for r in requests(job)]
    assert kinds == ["script_review", "clarify", "script_review"]


def test_revert_copies_an_old_version_forward(tmp_path: Path) -> None:
    ops = [
        {
            "op": "set",
            "scene_id": "s1",
            "field": "voiceover",
            "value": "Một câu mở đầu hoàn toàn khác",
        }
    ]
    answers = {"script_review": [
        {"action": "edit", "edit": {"ops": ops}},
        {"action": "revert", "revert_to": 1},
        {"action": "approve"},
    ]}  # fmt: skip
    runner, _, _, job, _ = build(tmp_path, answers)
    script = runner.run()
    store = ScriptStore(job)
    assert store.versions() == [1, 2, 3]
    assert store.load(3).model_dump() == store.load(1).model_dump() and script == store.load(1)
    third = requests(job)[2]["request"]
    assert third["script_version"] == 3 and any(
        "Scene s1: đổi lời đọc" in c for c in third["changes"]
    )


def test_regenerate_writes_a_new_script_as_the_next_version(tmp_path: Path) -> None:
    answers = {"script_review": [{"action": "regenerate"}, {"action": "approve"}]}
    runner, handler, _, job, _ = build(tmp_path, answers)
    script = runner.run()
    assert handler.writer_calls == 2 and ScriptStore(job).versions() == [1, 2]
    assert script.scenes[0].root.voiceover.startswith("regen2")


def test_an_edit_that_changes_nothing_says_so(tmp_path: Path) -> None:
    answers = {
        "script_review": [
            {"action": "edit", "edit": {"instruction": "không làm gì"}},
            {"action": "approve"},
        ]
    }
    runner, _, _, job, _ = build(tmp_path, answers)
    runner.run()
    assert ScriptStore(job).versions() == [1]
    assert "Chưa có thay đổi nào" in requests(job)[1]["request"]["message"]


def test_a_stale_base_version_is_refused(tmp_path: Path) -> None:
    answers = {"script_review": [{"action": "approve", "base_version": 7}, {"action": "approve"}]}
    runner, _, _, job, _ = build(tmp_path, answers)
    runner.run()
    assert "Bản bạn xem là v7" in requests(job)[1]["request"]["message"]


def test_cancel_raises(tmp_path: Path) -> None:
    runner, *_ = build(tmp_path, {"script_review": [{"action": "cancel"}]})
    with pytest.raises(Cancelled):
        runner.run()


def test_set_global_rewrites_the_whole_script_with_the_new_brief(tmp_path: Path) -> None:
    handler = Handler()
    handler.plan = {
        "status": "ok",
        "ops": [{"op": "set_global", "field": "tone", "value": "hài hước"}],
    }
    answers = {
        "script_review": [
            {"action": "edit", "edit": {"instruction": "giọng hài hước hơn"}},
            {"action": "approve"},
        ]
    }
    runner, _, _, job, _ = build(tmp_path, answers, handler)
    runner.run()
    writer_prompts = [
        p for p in handler.prompts if p.startswith("Bạn là biên kịch short video marketing (TikTok")
    ]
    assert (
        len(writer_prompts) == 2
        and "tone: hài hước" in writer_prompts[1]
        and "<user_notes>" not in writer_prompts[0]
    )
    assert ScriptStore(job).versions() == [1, 2]


def test_an_old_outline_gets_its_demo_beats_linked_before_the_writer_runs(tmp_path: Path) -> None:
    outline = make_outline(feature_ids={})  # every middle beat unlinked, as in the todomvc outline
    runner, handler, _, job, _ = build(
        tmp_path, {"script_review": [{"action": "approve"}]}, outline=outline
    )
    runner.run()
    mapper_calls = [p for p in handler.prompts if p.startswith("Bạn là trợ lý biên tập video")]
    assert len(mapper_calls) == 1
    writer_prompt = next(
        p for p in handler.prompts if p.startswith("Bạn là biên kịch short video marketing (TikTok")
    )
    assert '"feature_id": "create"' in writer_prompt and '"feature_id": "filter"' in writer_prompt
    report = json.loads((job / "script_report.json").read_text(encoding="utf-8"))
    assert [c for c in report["beat_mapping"]["changes"]] == [
        "Gắn b2 với «Tính năng create»",
        "Gắn b3 với «Tính năng filter»",
    ]
    assert (job / "beat_mapping_script.json").is_file()


def test_an_outline_that_is_already_linked_is_not_sent_to_the_mapper(tmp_path: Path) -> None:
    linked = make_outline(feature_ids={1: "create", 2: "filter", 3: "story"})  # every middle beat
    runner, handler, *_ = build(
        tmp_path, {"script_review": [{"action": "approve"}]}, outline=linked
    )
    runner.run()
    assert not any(p.startswith("Bạn là trợ lý biên tập video") for p in handler.prompts)


def test_a_finished_job_is_returned_without_any_llm_call(tmp_path: Path) -> None:
    runner, _, _, job, _ = build(tmp_path, {"script_review": [{"action": "approve"}]})
    first = runner.run()
    again, handler2, _, _, theme_calls = build(tmp_path, {})
    assert again.run() == first and handler2.prompts == [] and theme_calls == []


def test_resuming_continues_from_the_newest_version_and_keeps_the_theme(tmp_path: Path) -> None:
    ops = [{"op": "set_theme", "field": "primary", "value": "#B91C1C"}]
    runner, _, _, job, _ = build(
        tmp_path,
        {"script_review": [{"action": "edit", "edit": {"ops": ops}}, {"action": "cancel"}]},
    )
    with pytest.raises(Cancelled):
        runner.run()
    assert ScriptStore(job).versions() == [1, 2] and not (job / "script_approved.json").exists()
    runner2, handler2, _, _, theme_calls = build(
        tmp_path, {"script_review": [{"action": "approve"}]}
    )
    script = runner2.run()
    assert (
        handler2.writer_calls == 0 and theme_calls == []
    )  # nothing regenerated, theme read from disk
    assert (
        script.theme.primary == "#B91C1C"
        and runner2.ctx is not None
        and runner2.ctx.theme.primary == "#B91C1C"
    )


# --- the CLI ----------------------------------------------------------------------------------


def test_cli_from_step_script_runs_to_an_approved_script_with_one_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.llm.client import LLMSettings

    handler = Handler()
    handler.plan = {
        "status": "ok",
        "ops": [{"op": "set", "scene_id": "s2", "field": "on_screen_text", "value": "Gõ là có"}],
    }
    llm = FakeLLM(handler)
    monkeypatch.setattr("app.pipeline.runner.OpenAIChat", lambda settings: llm)
    settings = LLMSettings(
        api_key="k", base_url="http://x", model="m", vision_model=None,
        cache_enabled=False, cache_dir=tmp_path / "cache",
    )  # fmt: skip
    monkeypatch.setattr("app.pipeline.runner.load_settings", lambda: settings)
    monkeypatch.setattr(
        "app.pipeline.runner.derive_theme",
        lambda *a, **k: ThemeResult(THEME, "css", "css", None, [], []),
    )

    class FakeSession:
        def __init__(self, *a: Any, **k: Any) -> None: ...
        def __enter__(self) -> "FakeSession":
            return self

        def __exit__(self, *a: Any) -> None: ...

    monkeypatch.setattr("app.pipeline.runner.BrowserSession", FakeSession)
    job = tmp_path / "job"
    job.mkdir()
    (job / "confirmed_profile.json").write_text(make_profile().model_dump_json(), encoding="utf-8")
    (job / "outline_approved.json").write_text(make_outline().model_dump_json(), encoding="utf-8")
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({"script_review": [
        {"action": "edit", "edit": {"instruction": "scene 2: chữ ngắn hơn"}}, {"action": "approve"},
    ]}), encoding="utf-8")  # fmt: skip
    code = main(
        [
            "--url",
            "https://todo.example/",
            "--job-dir",
            str(job),
            "--auto",
            "--answers",
            str(answers),
            "--from-step",
            "script",
            "--stop-after",
            "script",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    approved = Script.model_validate_json(
        (job / "script_approved.json").read_text(encoding="utf-8")
    )
    assert approved.scenes[1].root.on_screen_text == "Gõ là có"
    assert "Kịch bản v1" in out and "Kịch bản v2" in out and "Ước tính" in out and "#4F46E5" in out
    assert (job / "script_usage.json").is_file()


def test_cli_refuses_from_step_script_without_the_saved_outline(tmp_path: Path) -> None:
    job = tmp_path / "empty"
    job.mkdir()
    assert (
        main(["--url", "https://x.example/", "--job-dir", str(job), "--from-step", "script"]) == 5
    )


def test_cli_produce_step_is_not_available_yet(tmp_path: Path) -> None:
    assert (
        main(["--url", "https://x.example/", "--job-dir", str(tmp_path), "--from-step", "produce"])
        == 5
    )
