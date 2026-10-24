import json
import subprocess
from pathlib import Path
from typing import Any

from app.core.timing import estimate_speech_ms
from app.producer.pipeline import (
    IDLE_LIMIT_MS,
    SCROLL_RATE,
    plan_scene_timing,
    produce,
    scene_idle_gaps,
)
from app.recorder.record import RecordResult
from tests.test_fit_and_scene_writer import make_script
from tests.test_script_writer import make_profile

# --- timing rules ---------------------------------------------------------------------------------


def test_a_clip_shorter_than_the_speech_holds_its_last_frame() -> None:
    assert plan_scene_timing(8000, 5000) == (8000, 1.0, True)


def test_a_clip_as_long_as_the_speech_plays_as_is() -> None:
    assert plan_scene_timing(8000, 8000) == (8000, 1.0, False)


def test_actions_are_never_sped_up_the_scene_just_grows() -> None:
    assert plan_scene_timing(8000, 10000) == (10000, 1.0, False)
    assert plan_scene_timing(8000, 15000) == (15000, 1.0, False)


def test_scrolling_and_pointing_scenes_may_play_up_to_1_15x() -> None:
    final, rate, freeze = plan_scene_timing(8000, 8800, SCROLL_RATE)
    assert (final, rate, freeze) == (8000, 1.1, False)
    final, rate, _ = plan_scene_timing(8000, 15000, SCROLL_RATE)
    assert rate == 1.15 and final == round(15000 / 1.15)  # still longer than the speech


def test_scenes_without_footage_last_exactly_their_speech() -> None:
    assert plan_scene_timing(6000, None) == (6000, 1.0, False)


def test_idle_gaps_follow_the_trim_the_speed_and_the_held_last_frame() -> None:
    # events at 1.0 s and 3.0 s of the clip; the first 500 ms are trimmed: 0.5 s and 2.5 s remain
    assert scene_idle_gaps([1000, 3000], 500, 3500, 1.0, 3000) == [500, 2000, 500]
    # sped up 2x everything happens twice as early
    assert scene_idle_gaps([1000, 3000], 500, 3500, 2.0, 1750) == [1000, 500]
    # the scene is held for 4 s after the last event: that quiet stretch counts
    assert scene_idle_gaps([1000], 0, 1000, 1.0, 5000) == [1000, 4000]
    assert scene_idle_gaps([], 0, 0, 1.0, 3000) == [3000]
    assert scene_idle_gaps([100, 200, 2000], 1000, 3000, 1.0, 3000) == [1000, 2000]


# --- the whole pipeline with a recorder and a renderer that are stand-ins ------------------------------


def tiny_mp4(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=30:duration=1",
         "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path)],
        check=True,
    )  # fmt: skip
    return path


def test_produce_fits_every_scene_and_writes_the_report(tmp_path: Path) -> None:
    script, _ = make_script(tmp_path, 45)
    hidden = script.model_dump()
    hidden["scenes"][2]["visual"]["show_setup"] = False  # the setup of s3 is cut off the clip
    script = type(script).model_validate(hidden)
    work = tmp_path / "job"
    seen: dict[str, Any] = {}

    def recorder(
        session: Any, scene: Any, out_dir: Path, speech_ms: int, **kw: Any
    ) -> RecordResult:
        s = scene.root
        seen[s.id] = speech_ms
        if s.visual.mode == "screenshot":
            img = out_dir / f"{s.id}.png"
            img.parent.mkdir(parents=True, exist_ok=True)
            img.write_bytes(b"png")
            return RecordResult(kind="screenshot", image_path=img)
        if s.visual.mode != "recording":
            return RecordResult(kind="template")
        clip = tiny_mp4(out_dir / f"{s.id}.mp4")
        # s2: 4 s of footage after loading (too short); s3: a setup that is not shown, 14 s in all
        content = 5000 if s.id == "s2" else 17000
        return RecordResult(
            kind="recording", clip_path=clip, start_offset_ms=1000,
            setup_end_ms=1000 if s.id == "s2" else 3000, content_ms=content,
            click_log=[{"t_ms": 1500, "x": 10, "y": 10, "type": "click"},
                       {"t_ms": 4000, "x": 20, "y": 20, "type": "click"}],
            activity_ms=[1500.0, 2500.0, 4000.0, 4500.0], steps_ok=2, filled_ms=0,
            warnings=[f"{s.id}: cảnh báo thử"],
        )  # fmt: skip

    renders: list[dict[str, Any]] = []

    def render(props: dict[str, Any], out: Path, work_dir: Path) -> Any:
        renders.append(props)
        tiny_mp4(out)
        return type("R", (), {"render_ms": 1234})()

    messages: list[str] = []
    result = produce(
        script, url="https://todo.example/", job_dir=work, session=None,  # type: ignore[arg-type]
        render=render, profile=make_profile(), recorder=recorder, progress=messages.append,
        token_usage={"total": 1}, extra_report={"url": "https://todo.example/"},
    )  # fmt: skip

    speech = {s.root.id: estimate_speech_ms(s.root.voiceover) for s in script.scenes}
    assert seen == {"s2": speech["s2"], "s3": speech["s3"]} or set(seen) >= {"s2", "s3"}
    by_id = {o.id: o for o in result.scenes}
    s2, s3 = by_id["s2"], by_id["s3"]
    assert (
        s2.usable_ms == 4000
        and s2.freeze is True
        and s2.final_ms == speech["s2"]
        and s2.playback_rate == 1.0
    )
    assert s3.usable_ms == 14000 and s3.freeze is False  # 17 s minus 3 s: setup cut, not shown
    assert s3.playback_rate == 1.0 and s3.final_ms == 14000  # an action scene: never sped up
    assert (
        by_id["s1"].usable_ms is None and by_id["s1"].final_ms == speech["s1"]
    )  # photo: its speech
    assert (
        by_id["s5"].kind == "chữ"
        and by_id["s4"].kind == "cuộn-highlight"
        and by_id["s1"].kind == "ảnh"
        and s2.kind == "thao tác"
    )

    # the script that is rendered carries the final durations
    final = {s["id"]: s["duration_ms"] for s in renders[0]["script"]["scenes"]}
    assert final == {o.id: o.final_ms for o in result.scenes}
    assets = renders[0]["assets"]
    assert assets["s2"]["freeze_last_frame"] is True and assets["s2"]["clip_duration_ms"] == 5000
    assert assets["s2"]["trim_start_ms"] == 0
    assert assets["s3"]["trim_start_ms"] == 2000  # setup_end 3000 - start_offset 1000
    assert [c["t_ms"] for c in assets["s3"]["click_log"]] == [
        4000
    ]  # the click in the hidden setup is dropped
    assert assets["s1"]["screenshot_url"].endswith("s1.png")
    words = assets["s2"]["captions"][0]["words"]
    assert 3 <= len(assets["s2"]["captions"][0]["text"].split()) <= 5 and words[0]["start_ms"] == 0

    report = json.loads((work / "report.json").read_text(encoding="utf-8"))
    assert report["target_ms"] == 45000 and report["estimated_ms"] == sum(speech.values())
    assert report["planned_ms"] == sum(o.final_ms for o in result.scenes)
    assert report["ffprobe"]["pix_fmt"] == "yuv420p" and report["actual_ms"] > 0
    assert report["phases_s"].keys() >= {"timing", "record", "render", "total"}
    assert report["tokens"] == {"total": 1} and report["url"] == "https://todo.example/"
    assert [f["id"] for f in report["features"]] == ["create", "filter", "story"]
    assert len(report["scenes"]) == 5 and report["idle_limit_ms"] == IDLE_LIMIT_MS
    assert {"id", "type", "kind", "speech_ms", "usable_ms", "final_ms", "playback_rate", "freeze",
            "idle_max_ms", "warnings"} <= set(report["scenes"][1])  # fmt: skip
    assert report["warnings"] == ["s2: cảnh báo thử", "s3: cảnh báo thử", "s4: cảnh báo thử"]
    assert any("scene 1/5" in m for m in messages) and result.video == work / "video.mp4"
    assert (
        s2.idle_max_ms is not None and s2.idle_max_ms >= speech["s2"] - 4500
    )  # the held frame is quiet
