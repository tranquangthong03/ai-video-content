import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from app.browser.session import BrowserSession
from app.core.usage import UsageTracker
from app.flows.agent import FlowAgent, Limits, cache_key
from app.flows.chapters import group_chapters
from app.llm.json_call import JsonCaller
from app.schemas.generated.core_flow import CoreFlow
from tests.conftest import FakeLLM


def flow_for(site: str, **kw: Any) -> CoreFlow:
    base = {
        "id": "leave", "title": "Xin nghỉ phép", "persona": "Nhân viên", "goal": "Xin nghỉ 2 ngày",
        "start_url": site + "/flow_apply.html", "expected_steps": ["Chọn loại", "Chọn ngày", "Ghi lý do"],
        "success_signal": "Form đã điền", "needs_submit": True, "value": "Nhanh",
    }  # fmt: skip
    return CoreFlow.model_validate({**base, **kw})


def ref_of(prompt: str, name: str) -> str:
    """The ref the prompt lists for an element name (the model reads the same list)."""
    for line in prompt.splitlines():
        cells = [c.strip() for c in line.split(" | ")]
        if len(cells) >= 8 and cells[2] == name and re.fullmatch(r"e\d+", cells[0]):
            return cells[0]
    raise AssertionError(f"{name!r} is not in the prompt")


def step(do: str, name: str | None = None, **kw: Any) -> dict[str, Any]:
    chapter = kw.pop("chapter", "Điền thông tin")
    update = kw.pop("sample", {})
    return {
        "do": do,
        "name": name,
        "chapter": chapter,
        "note": f"{do} {name}",
        "sample": update,
        **kw,
    }


def scripted(plan: list[dict[str, Any]]) -> Callable[[str], dict[str, Any]]:
    queue = list(plan)

    def handler(prompt: str) -> dict[str, Any]:
        item = dict(queue.pop(0) if len(queue) > 1 else queue[0])
        name = item.pop("name", None)
        action: dict[str, Any] = {"do": item.pop("do")}
        if name == "!invented":
            action["ref"] = "e999"
        elif name:
            action["ref"] = ref_of(prompt, name)
        for k in ("value", "direction", "reason", "reason_kind", "quote"):
            if k in item:
                action[k] = item.pop(k)
        return {
            "action": action, "chapter": item.get("chapter", ""), "note": item.get("note", ""),
            "reason": "", "sample_data_update": item.get("sample", {}),
        }  # fmt: skip

    return handler


def make_caller(
    tmp_path: Path, plan: list[dict[str, Any]], vision: str | None = "v", **kw: Any
) -> Any:
    llm = FakeLLM(scripted(plan), vision_model=vision)
    return JsonCaller(llm, tracker=UsageTracker(), cache_dir=tmp_path / "cache", **kw), llm


FILL = [
    step(
        "select", "Leave Type", value="Annual", chapter="Điền thông tin", sample={"loai": "Annual"}
    ),
    step("select", "Reason category", value="Family"),
    step("pick_date", "From Date", value="2027-03-05", sample={"tu": "2027-03-05"}),
    step("pick_date", "To Date", value="2027-03-06"),
    step("type", "Comment", value="Family event", chapter="Ghi lý do"),
]


@pytest.fixture
def session(browser_session: BrowserSession) -> Iterator[BrowserSession]:
    browser_session.guard.write_log.clear()
    browser_session.guard.write_windows = 0
    yield browser_session


def agent(
    session: BrowserSession, site: str, tmp_path: Path, plan: list[dict[str, Any]], **kw: Any
) -> tuple[FlowAgent, FakeLLM]:
    vision = kw.pop("vision", "v")
    caller, llm = make_caller(tmp_path, plan, vision)
    flow = kw.pop("flow", None) or flow_for(site)
    job = kw.pop("job", "job")
    return FlowAgent(session, caller, flow, tmp_path / job, **kw), llm


def test_the_agent_fills_the_form_and_stops_before_the_submit_button(
    session: BrowserSession, site: str, tmp_path: Path
) -> None:
    plan = [*FILL, step("stop_before_submit", "Apply", chapter="Gửi và theo dõi")]
    a, _ = agent(session, site, tmp_path, plan)
    run = a.run()
    assert run.status == "stopped_before_submit" and run.stop_ref == "Apply"
    dos = [s.action.do for s in run.steps]
    assert dos[0] == "goto" and dos[-2:] == ["hover", "highlight"]
    assert dos[1:6] == ["select", "select", "pick_date", "pick_date", "type"]
    assert run.sample_data == {"loai": "Annual", "tu": "2027-03-05"}
    assert run.steps[1].locator and run.steps[1].action.text == "Annual"
    assert run.steps[-1].action.ms == 1800 and run.steps[-1].locator
    assert run.report and run.report.write_requests == [] and not run.warnings
    assert all((tmp_path / "job" / s.screenshot).is_file() for s in run.steps if s.screenshot)
    assert (tmp_path / "job" / "flow" / "flow_run.json").is_file()


def test_chapters_cover_every_step_and_there_are_two_to_four(
    session: BrowserSession, site: str, tmp_path: Path
) -> None:
    a, _ = agent(
        session, site, tmp_path, [*FILL, step("stop_before_submit", "Apply", chapter="Gửi")]
    )
    run = a.run()
    assert 2 <= len(run.chapters) <= 4
    assert sorted(i for c in run.chapters for i in c.step_ids) == [s.i for s in run.steps]
    assert all(s.chapter_id for s in run.steps)
    assert (
        run.steps[0].chapter_id == run.steps[1].chapter_id
    )  # the opening goto joins the first chapter


def test_the_report_names_the_model_images_calls_tokens_and_time(
    session: BrowserSession, site: str, tmp_path: Path
) -> None:
    a, llm = agent(session, site, tmp_path, [*FILL, step("stop_before_submit", "Apply")])
    run = a.run()
    r = run.report
    assert r and r.model == "v" and r.used_images
    assert r.llm_calls == run.llm_calls == 6 == len(llm.calls)
    assert r.prompt_tokens == 600 and r.completion_tokens == 300 and r.seconds >= 0
    assert all(c["images"] for c in llm.calls)  # a screenshot rode along every round
    assert "Ảnh chụp màn hình" in llm.calls[0]["prompt"]


def test_without_a_vision_model_the_agent_works_on_text_only(
    session: BrowserSession, site: str, tmp_path: Path
) -> None:
    a, llm = agent(
        session, site, tmp_path, [*FILL, step("stop_before_submit", "Apply")], vision=None
    )
    run = a.run()
    assert run.status == "stopped_before_submit" and not run.report.used_images  # type: ignore[union-attr]
    assert run.report.model == "fake-text" and not any(c["images"] for c in llm.calls)  # type: ignore[union-attr]


def test_an_image_the_provider_refuses_falls_back_to_text_with_a_warning(
    session: BrowserSession, site: str, tmp_path: Path
) -> None:
    class Picky(FakeLLM):
        def complete(self, model: str, messages: list[dict[str, Any]]) -> Any:
            if not isinstance(messages[-1]["content"], str):
                raise RuntimeError("image input is not supported")
            return super().complete(model, messages)

    llm = Picky(scripted([*FILL, step("stop_before_submit", "Apply")]))
    caller = JsonCaller(llm, tracker=UsageTracker(), cache_dir=tmp_path / "cache")
    run = FlowAgent(session, caller, flow_for(site), tmp_path / "job").run()
    assert run.status == "stopped_before_submit" and not run.report.used_images  # type: ignore[union-attr]
    assert any("Không gửi được ảnh" in w for w in run.warnings)
    assert sum(1 for c in llm.calls if c["images"]) == 0  # and it did not try again with images


def test_the_submit_button_is_never_clicked_under_stop_even_if_the_model_tries(
    session: BrowserSession, site: str, tmp_path: Path
) -> None:
    plan = [*FILL, step("click", "Apply"), step("stop_before_submit", "Apply")]
    a, llm = agent(session, site, tmp_path, plan)
    run = a.run()
    assert run.status == "stopped_before_submit"
    assert any("không được phép gửi" in w for w in run.warnings)
    assert not any(s.action.do == "click" for s in run.steps)  # the refused click is no step
    assert "✗ click «Apply»" in llm.calls[-1]["prompt"]  # the model saw why


def test_under_allow_the_agent_clicks_submit_then_finishes(
    session: BrowserSession, site: str, tmp_path: Path
) -> None:
    plan = [*FILL, step("click", "Apply", chapter="Gửi và theo dõi"), step("finish")]
    run = agent(session, site, tmp_path, plan, submit_policy="allow")[0].run()
    assert run.status == "reached_goal" and run.submit_policy == "allow"
    assert run.steps[-1].action.do == "click" and run.steps[-1].target_text == "Apply"


def test_a_ref_the_model_made_up_is_refused_and_counted(
    session: BrowserSession, site: str, tmp_path: Path
) -> None:
    plan = [step("click", "!invented"), *FILL, step("stop_before_submit", "Apply")]
    run = agent(session, site, tmp_path, plan)[0].run()
    assert run.status == "stopped_before_submit"
    assert run.report and run.report.invented_refs == 1
    assert any("không có trong danh sách" in w for w in run.warnings)


def test_a_repeated_action_that_changes_nothing_warns_then_stops(
    session: BrowserSession, site: str, tmp_path: Path
) -> None:
    plan = [step("click", "Leave Type")]  # a native select: clicking it changes nothing, forever
    run_agent, llm = agent(session, site, tmp_path, plan)
    run = run_agent.run()
    assert run.status == "partial" and any("lặp 3 lần" in w for w in run.warnings)
    warned = [c for c in llm.calls if "đã lặp 2 lần mà trang không đổi" in c["prompt"]]
    assert warned, "the second repeat must be reported to the model on the next call"
    assert len(llm.calls) <= 4


def test_give_up_and_finish_end_the_run(session: BrowserSession, site: str, tmp_path: Path) -> None:
    run = agent(session, site, tmp_path, [step("give_up", reason="không thấy form")])[0].run()
    assert run.status == "partial" and any("bỏ cuộc" in w for w in run.warnings)
    run = agent(session, site, tmp_path / "b", [step("finish")])[0].run()
    assert run.status == "reached_goal"


def test_the_action_and_call_limits(session: BrowserSession, site: str, tmp_path: Path) -> None:
    scrolls = [step("scroll", direction="down")]
    run = agent(session, site, tmp_path, scrolls, limits=Limits(max_actions=3))[0].run()
    assert len([s for s in run.steps if s.action.do == "scroll"]) == 3
    assert any("đủ 3 hành động" in w for w in run.warnings) and run.status == "partial"
    run = agent(session, site, tmp_path / "b", scrolls, limits=Limits(max_llm_calls=2))[0].run()
    assert any("2 lần gọi LLM" in w for w in run.warnings) and run.llm_calls == 2


def test_the_time_limit(session: BrowserSession, site: str, tmp_path: Path) -> None:
    ticks = iter(range(0, 10_000, 200))  # every look at the clock is 200 s later
    a, _ = agent(
        session, site, tmp_path, [step("scroll", direction="down")], clock=lambda: next(ticks)
    )
    run = a.run()
    assert any("quá 6 phút" in w for w in run.warnings) and run.status in ("partial", "failed")


def test_the_page_that_cannot_be_opened_fails_the_run_cleanly(
    session: BrowserSession, site: str, tmp_path: Path
) -> None:
    flow = flow_for(site, start_url="http://127.0.0.1:9/nothing")
    run = agent(session, site, tmp_path, [step("finish")], flow=flow)[0].run()
    assert run.status == "failed" and any("Không mở được" in w for w in run.warnings)


def test_a_finished_run_is_cached_and_the_second_run_costs_no_llm_call(
    session: BrowserSession, site: str, tmp_path: Path
) -> None:
    plan = [*FILL, step("stop_before_submit", "Apply")]
    first, llm1 = agent(session, site, tmp_path, plan, use_cache=True, job="j1")
    r1 = first.run()
    assert llm1.calls
    second, llm2 = agent(session, site, tmp_path, plan, use_cache=True, job="j2")
    r2 = second.run()
    assert not llm2.calls and r2.status == r1.status and r2.llm_calls == 0
    assert any("cache" in w for w in r2.warnings)
    assert all((tmp_path / "j2" / s.screenshot).is_file() for s in r2.steps if s.screenshot)


def test_failed_runs_are_not_cached_and_the_key_depends_on_policy_and_notes(
    session: BrowserSession, site: str, tmp_path: Path
) -> None:
    run = agent(session, site, tmp_path, [step("give_up", reason="x")], use_cache=True)[0].run()
    assert run.status == "partial"
    assert not list((tmp_path / "cache").glob("flow-cache/*"))
    f = flow_for(site)
    assert cache_key(f, "stop", "") != cache_key(f, "allow", "") != cache_key(f, "stop", "đổi loại")


# --- chapters (pure) --------------------------------------------------------------------------


def names(*items: tuple[str, str]) -> list[tuple[int, str, str]]:
    return [(i, do, name) for i, (do, name) in enumerate(items, start=1)]


def test_chapters_follow_the_agents_names_and_fold_scroll_only_ones() -> None:
    steps = names(
        ("goto", "Mở"), ("click", "Mở"), ("scroll", "Cuộn"), ("select", "Điền"), ("type", "Điền"),
        ("hover", "Gửi"),
    )  # fmt: skip
    chapters = group_chapters(steps)
    assert [c.title for c in chapters] == ["Mở", "Điền", "Gửi"]
    assert chapters[0].step_ids == [1, 2, 3]  # the lone scroll joined the chapter before it


def test_more_than_four_chapters_are_joined_and_one_long_chapter_is_split() -> None:
    many = names(*[("click", f"c{n}") for n in range(7)])
    assert len(group_chapters(many)) == 4
    long = names(*[("type", "Điền")] * 6)
    split = group_chapters(long)
    assert [c.title for c in split] == ["Điền", "Hoàn tất"] and split[0].step_ids == [1, 2, 3]
    assert len(group_chapters(names(("click", "A"), ("click", "A")))) == 1  # too short to split


def test_scrolling_back_up_is_a_valid_step_that_the_recorder_can_repeat(
    session: BrowserSession, site: str, tmp_path: Path
) -> None:
    from tests.test_recorder import goto, rec

    plan = [step("scroll", direction="down"), step("scroll", direction="up"), step("finish")]
    run = agent(session, site, tmp_path, plan, flow=flow_for(site, start_url=site + "/tall.html"))[
        0
    ].run()
    scrolls = [s for s in run.steps if s.action.do == "scroll"]
    assert [(s.action.ms, s.action.text) for s in scrolls] == [(600, None), (600, "up")]
    assert run.status == "reached_goal"
    visual = {
        "mode": "recording",
        "actions": [
            goto(site, "/tall.html"),
            {"do": "scroll", "ms": 600},
            {"do": "scroll", "ms": 600, "text": "up"},
        ],
    }
    r = rec(session, site, tmp_path / "rec", visual, speech_ms=1000)
    assert r.warnings == [] and r.steps_ok == 2
