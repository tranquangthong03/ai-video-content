"""The tiered regression tools: area selection, path rebasing and the "no LLM, no browser" promise."""

import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import golden, regress


def test_paths_pick_the_areas_to_test() -> None:
    areas, other = regress.areas_of(
        [
            "services/api/app/producer/trim.py",
            "services/api/app/script/critic.py",
            "services/api/tests/test_critic.py",
            "apps/render/src/camera/path.ts",
        ]
    )
    assert areas == ["producer", "script"] and other == {"ts": True, "schema": False}
    areas, other = regress.areas_of(["packages/script-schema/schemas/script.json", "app/llm/x.py"])
    assert areas == ["llm"] and other["schema"] and not other["ts"]


def test_absolute_paths_of_a_snapshot_move_to_the_workspace() -> None:
    props = {
        "assets": {"s1": {"clip_url": "C:\\old\\job\\produce\\s1.mp4", "n": 3}},
        "x": ["C:\\other"],
    }
    moved = regress.rebase(props, "C:\\old\\job", "D:\\ws")
    assert moved["assets"]["s1"]["clip_url"] == "D:\\ws\\produce\\s1.mp4"
    assert moved["x"] == ["C:\\other"] and moved["assets"]["s1"]["n"] == 3


def test_the_llm_guard_refuses_a_call_and_counts_it() -> None:
    from app.llm.json_call import OpenAIChat

    chat = OpenAIChat.__new__(OpenAIChat)  # no client: the guard must stop the call before it
    with regress.llm_meter(False) as meter, pytest.raises(regress.LLMForbidden):
        chat.complete("m", [])
    assert (meter.calls, meter.blocked) == (0, 1)


def test_every_golden_snapshot_has_what_a_replay_reads() -> None:
    for name in golden.NAMES:
        root = golden.GOLDEN / name
        for need in ("confirmed_profile.json", "script_approved.json", "flow/flow_approved.json",
                     "flow/live/logs.json", "produce/render_props.json", "report.json"):  # fmt: skip
            assert (root / need).is_file(), f"{name}/{need}"
        assert list((root / "produce" / "focus").glob("*.json")), name


def test_t1_replays_a_snapshot_with_no_llm_call_and_no_browser(tmp_path: Path) -> None:
    name = "squoosh"
    if not golden.restore_media(name):
        pytest.skip("golden-media/squoosh is missing and out/cam-squoosh is gone: run golden.py")
    rendered: list[Path] = []

    def fake_render(props: dict[str, Any], out: Path, work: Path) -> Any:
        rendered.append(out)
        shutil.copy2(golden.MEDIA / name / "video.mp4", out)  # a real video for ffprobe
        return SimpleNamespace(render_ms=1)

    now, meter, ok = regress.run_t1([name], render=fake_render, qa=False, work=tmp_path)
    assert ok, now
    assert meter.calls == 0  # the promise of T0 / T1
    assert rendered and rendered[0].parent == tmp_path / name
    assert now[name]["video_s"] > 0 and "error" not in now[name]
