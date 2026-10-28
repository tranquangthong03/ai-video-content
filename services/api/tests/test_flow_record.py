import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from app.browser.session import BrowserSession
from app.flows.agent import FlowAgent
from app.producer.pipeline import produce
from app.recorder.flow import HERO_MS, FlowRecorder, pick_hero
from app.schemas.generated.flow_run import FlowRun
from app.schemas.generated.scene import Scene
from app.schemas.generated.script import Script
from tests.test_flow_agent import FILL, flow_for, make_caller, step
from tests.test_producer import tiny_mp4

pytestmark = pytest.mark.slow

THEME = {
    "primary": "#4F46E5", "accent": "#F59E0B", "font": "Be Vietnam Pro", "motion_preset": "energetic",
    "caption_style": "minimal", "music_mood": "upbeat", "voice_id": "v", "language": "vi",
}  # fmt: skip


@pytest.fixture(scope="module")
def agent_job(
    browser_session: BrowserSession, site: str, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, FlowRun]:
    """A flow the agent ran on the fixture site (with its storyboard pictures)."""
    base = tmp_path_factory.mktemp("agent")
    caller, _ = make_caller(base, [*FILL, step("stop_before_submit", "Apply", chapter="Gửi")])
    run = FlowAgent(browser_session, caller, flow_for(site), base / "job").run()
    assert run.status == "stopped_before_submit"
    return base / "job", run


@pytest.fixture(scope="module")
def filmed(
    browser_session: BrowserSession, site: str, agent_job: tuple[Path, FlowRun],
    tmp_path_factory: pytest.TempPathFactory,
) -> FlowRecorder:  # fmt: skip
    """The flow replayed once, on one context, through the recorder the producer uses."""
    job, run = agent_job
    out = tmp_path_factory.mktemp("film")
    recorder = FlowRecorder(run, job)
    recorder._record(browser_session, out, {"root_url": site})
    return recorder


def scene(scene_id: str, kind: str, chapter: str | None = None) -> Scene:
    base: dict[str, Any] = {
        "id": scene_id, "type": kind, "voiceover": "một hai ba bốn năm sáu bảy tám chín mười",
        "key_point": f"k{scene_id}", "icon": "check", "visual": {"mode": "recording"},
    }  # fmt: skip
    if kind == "hook":
        base["layout"] = "big_text_over_blur"
    elif kind == "cta":
        base["layout"] = "button_pulse"
    else:
        base.update(layout="full_screen", feature=chapter, chapter_id=chapter)
    return Scene.model_validate(base)


def test_every_step_is_replayed_on_one_context_in_order(filmed: FlowRecorder) -> None:
    rec = filmed.recording
    assert rec is not None and rec.failed_at is None and rec.clip_path and rec.clip_path.is_file()
    steps = [s for s in filmed.run.steps if s.action.do != "goto"]
    assert [m.i for m in rec.marks] == [s.i for s in steps] and all(m.ok for m in rec.marks)
    spans = [(m.start_ms, m.end_ms) for m in rec.marks]
    assert all(a < b for a, b in spans) and all(
        spans[n][1] <= spans[n + 1][0] + 50 for n in range(len(spans) - 1)
    )  # one after the other
    assert rec.start_offset_ms > 0 and rec.content_ms >= spans[-1][1]
    assert len(rec.inventory) >= len(steps) and rec.focus_log and rec.action_log


def test_the_chapters_are_cut_without_gaps_and_every_log_is_retimed(
    filmed: FlowRecorder, tmp_path: Path
) -> None:
    results = []
    for chapter in filmed.run.chapters:
        r = filmed._chapter(filmed.recording, chapter.id, tmp_path, f"s_{chapter.id}")  # type: ignore[arg-type]
        results.append(r)
        assert r.kind == "recording" and r.clip_path and r.clip_path.is_file()
        assert all(0 <= e["t_ms"] <= r.content_ms for e in r.focus_log + r.click_log + r.inventory)
        assert r.inventory and r.focus_log and r.action_log and r.width == 1280
    assert results[0].start_offset_ms > 0 and results[1].start_offset_ms == 0
    total = sum(r.content_ms for r in results)
    assert abs(total - filmed.recording.content_ms) < 400  # type: ignore[union-attr]
    assert {"select", "pick_date"} <= {a["do"] for a in results[0].action_log}  # c1 filled the form
    assert {a["do"] for a in results[1].action_log} == {"type"}  # c2 wrote the comment
    assert {a["do"] for a in results[-1].action_log} == {"hover", "highlight"}  # c3 the button


def test_the_hook_is_about_two_seconds_around_the_highlighted_button(
    filmed: FlowRecorder, tmp_path: Path
) -> None:
    assert pick_hero(filmed.run) == filmed.run.steps[-1].i  # the highlight
    hook = filmed._hook(filmed.recording, tmp_path, "s1")  # type: ignore[arg-type]
    # the hero frame is chosen by code from the frame inventory: 1.5-2.5 s around it
    assert hook is not None and hook.kind == "recording" and hook.start_offset_ms == 0
    assert 1400 <= hook.content_ms <= 2500
    assert filmed.hero is not None and filmed.hero["to_ms"] - filmed.hero["from_ms"] >= 1500


def test_without_a_frame_inventory_the_hook_falls_back_to_the_hero_step(
    filmed: FlowRecorder, tmp_path: Path
) -> None:
    assert filmed.recording is not None
    rec = replace(
        filmed.recording, inventory=[]
    )  # (the film is shared by the tests of this module)
    filmed.hero = None
    hook = filmed._hook(rec, tmp_path, "s1")
    assert hook is not None and hook.kind == "recording" and filmed.hero is None
    assert HERO_MS - 100 <= hook.content_ms <= HERO_MS
    assert any(f["kind"] == "highlight" for f in hook.focus_log)  # the camera has the button


def test_a_step_that_cannot_be_replayed_ends_the_film_and_the_rest_uses_the_storyboard(
    browser_session: BrowserSession, site: str, agent_job: tuple[Path, FlowRun], tmp_path: Path
) -> None:
    job, run = agent_job
    broken = FlowRun.model_validate_json(run.model_dump_json())
    target = [s for s in broken.steps if s.action.do == "pick_date"][-1]  # the last of chapter 1
    spec = target.locator
    assert spec is not None
    spec.css, spec.name, spec.text = "#nope", "Nothing", "Nothing"
    spec.bbox = spec.fingerprint = spec.nth = None  # nothing left to find it by
    target.target_text = "Nothing at all"
    recorder = FlowRecorder(broken, job)
    recorder._record(browser_session, tmp_path, {"root_url": site})
    rec = recorder.recording
    assert rec is not None and rec.failed_at == target.i
    chapter_of_failure = next(c for c in broken.chapters if target.i in c.step_ids)
    part = recorder._chapter(rec, chapter_of_failure.id, tmp_path, "sx")
    assert part.kind == "recording" and any("luồng dừng ở bước" in w for w in part.warnings)
    later = [c for c in broken.chapters if c.step_ids[0] > target.i]
    for c in later:
        r = recorder._chapter(rec, c.id, tmp_path, f"sl_{c.id}")
        assert r.kind == "fallback_screenshot" and r.image_path and r.image_path.is_file()
        assert any("ảnh storyboard" in w for w in r.warnings)
    hook = recorder._hook(rec, tmp_path, "sh")
    assert hook is not None and hook.kind == "recording"  # the best frame that WAS filmed
    hook = recorder._hook(replace(rec, inventory=[]), tmp_path, "sh2")
    assert hook is not None and hook.kind == "screenshot"  # no frames, and the hero step never ran


def test_a_submit_click_is_replayed_only_when_the_policy_is_allow(
    browser_session: BrowserSession, site: str, agent_job: tuple[Path, FlowRun], tmp_path: Path
) -> None:
    job, run = agent_job
    clicked = FlowRun.model_validate_json(run.model_dump_json())
    last = clicked.steps[-2]  # the hover on Apply -> a click on Apply
    last.action.do = "click"
    clicked.steps = clicked.steps[:-1]
    clicked.chapters[-1].step_ids = [s for s in clicked.chapters[-1].step_ids if s <= last.i]
    stop = FlowRecorder(clicked, job)
    stop._record(browser_session, tmp_path / "a", {"root_url": site})
    assert stop.recording is not None and stop.recording.failed_at == last.i  # refused
    clicked.submit_policy = "allow"
    browser_session.guard.write_windows = 0
    allowed = FlowRecorder(clicked, job)
    allowed._record(browser_session, tmp_path / "b", {"root_url": site})
    assert allowed.recording is not None and allowed.recording.failed_at is None
    assert browser_session.guard.write_windows == 1


def test_produce_films_the_flow_once_and_renders_its_chapters_as_scenes(
    browser_session: BrowserSession, site: str, agent_job: tuple[Path, FlowRun], tmp_path: Path
) -> None:
    src_job, run = agent_job
    job = tmp_path / "job"
    shutil.copytree(src_job, job)
    (job / "flow" / "flow_approved.json").write_text(run.model_dump_json(), encoding="utf-8")
    script = Script.model_validate(
        {
            "title": "t", "goal": "tutorial", "aspect_ratio": "9:16", "target_duration_s": 30,
            "headline": "Xin nghỉ trong một phút", "theme": THEME, "flow_id": run.flow_id,
            "scenes": [
                scene("s1", "hook").model_dump(),
                scene("s2", "feature_demo", "c1").model_dump(),
                scene("s3", "feature_demo", "c2").model_dump(),
                scene("s4", "cta").model_dump(),
            ],
        }
    )  # fmt: skip
    for sc in script.scenes:  # the flow route sets these visuals; the CTA is the home page
        sc.root.visual.mode = "recording"
    script.scenes[3].root.visual.page = site + "/flow_home.html"
    seen: list[dict[str, Any]] = []

    def render(props: dict[str, Any], out: Path, work: Path) -> Any:
        seen.append(props)
        tiny_mp4(out)
        return type("R", (), {"render_ms": 1})()

    result = produce(
        script, url=site + "/flow_apply.html", job_dir=job, session=browser_session,
        render=render, progress=None,
    )  # fmt: skip
    assets = seen[0]["assets"]
    assert [o.recording for o in result.scenes[:3]] == ["recording"] * 3
    assert all(assets[i].get("clip_url") for i in ("s1", "s2", "s3"))
    assert assets["s3"]["focus_track"] and result.report["dropped_scenes"] == []
    flow = result.report["flow"]
    assert flow["replay_failed_at"] is None and flow["replayed"] == len(run.steps) - 1
    assert flow["write_requests"] == [] and not any("trùng" in w for w in result.report["warnings"])
    probe = subprocess.run(
        ["ffprobe", "-v", "error", str(assets["s3"]["clip_url"])], capture_output=True
    )
    assert probe.returncode == 0


def test_a_click_whose_target_is_gone_is_skipped_and_the_film_goes_on(
    browser_session: BrowserSession, site: str, agent_job: tuple[Path, FlowRun], tmp_path: Path
) -> None:
    job, run = agent_job
    broken = FlowRun.model_validate_json(run.model_dump_json())
    pointing = next(s for s in broken.steps if s.action.do == "hover")
    spec = pointing.locator
    assert spec is not None
    spec.css, spec.name, spec.text = "#nope", "Nothing", "Nothing"
    spec.bbox = spec.fingerprint = spec.nth = None
    pointing.target_text = "Nothing at all"
    recorder = FlowRecorder(broken, job)
    recorder._record(browser_session, tmp_path, {"root_url": site})
    rec = recorder.recording
    assert rec is not None and rec.failed_at is None
    assert [m.i for m in rec.marks if m.skipped] == [pointing.i]
    assert rec.marks[-1].i == broken.steps[-1].i and rec.marks[-1].ok  # the highlight still ran
    assert any("bị bỏ qua" in w for w in rec.warnings)


def test_the_sync_pulse_is_measured_and_stays_in_the_part_that_is_cut_off(
    filmed: FlowRecorder, tmp_path: Path
) -> None:
    from app.recorder import sync

    rec = filmed.recording
    assert rec is not None and not any("độ lệch đồng hồ" in w for w in rec.warnings)
    assert abs(rec.sync_offset_ms) < sync.MAX_OFFSET_MS
    first = filmed._chapter(rec, filmed.run.chapters[0].id, tmp_path, "s1")
    assert first.clip_path is not None and first.start_offset_ms > rec.pulse_at_ms + sync.PULSE_MS
    seen = sync.find_pulse(first.clip_path)  # in the cut clip, log time = clip time
    assert seen is not None and abs(seen - rec.pulse_at_ms) <= 150
    assert not sync.video_has_pulse(first.clip_path, first.start_offset_ms, fps=15)
    for chapter in filmed.run.chapters[1:]:
        later = filmed._chapter(rec, chapter.id, tmp_path, f"s_{chapter.id}")
        assert later.clip_path is not None and not sync.video_has_pulse(later.clip_path, 0, fps=15)
    hook = filmed._hook(rec, tmp_path, "sh")
    assert hook is not None and hook.clip_path is not None
    assert not sync.video_has_pulse(hook.clip_path, 0, fps=15)


def test_the_cta_uses_the_hero_frame_as_its_background_with_a_gentle_zoom_target(
    filmed: FlowRecorder, tmp_path: Path
) -> None:
    rec = filmed.recording
    assert rec is not None
    cta = filmed._cta(rec, tmp_path, "s9")
    assert cta is not None and cta.kind == "screenshot"
    assert cta.image_path and cta.image_path.is_file() and cta.image_path.stat().st_size > 1000
    assert cta.focus_log and cta.focus_log[0]["bbox"]["w"] > 0  # something real to zoom toward
    assert filmed._cta(replace(rec, inventory=[]), tmp_path, "s8") is None  # no frames: the old way


def test_a_before_after_needs_two_really_different_frames(
    filmed: FlowRecorder, tmp_path: Path
) -> None:
    rec = filmed.recording
    assert rec is not None
    pair = filmed._pair(rec, tmp_path, "s7")
    if pair is None:  # (the fixture form may not change enough between its first frame and the end)
        assert any("trước/sau" in n for n in filmed.notes)
    else:
        before, after = pair.pair_images or (None, None)
        assert before and after and before.is_file() and after.is_file() and before != after
        assert pair.image_path == after
    assert filmed._pair(replace(rec, inventory=rec.inventory[:1]), tmp_path, "s6") is None


def test_a_chapter_continues_the_previous_one_only_on_the_same_page(
    filmed: FlowRecorder,
) -> None:
    chapters = [c.id for c in filmed.run.chapters]
    assert (
        filmed.continues(chapters[0]) is False
    )  # the first one follows the hook, a cut from elsewhere
    steps = {s.i: s for s in filmed.run.steps}
    left = steps[filmed.run.chapters[0].step_ids[-1]].url_after
    start = steps[filmed.run.chapters[1].step_ids[0]].url_before
    assert filmed.continues(chapters[1]) is (bool(left) and left == start)
