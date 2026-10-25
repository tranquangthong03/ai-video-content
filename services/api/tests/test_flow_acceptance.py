import json
import sys
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from rich.console import Console

from app.core.flow_choice import build_request
from app.flows.storyboard import build_request as storyboard_request
from app.schemas.generated.core_flow import CoreFlow
from tests.test_flow_storyboard import make_run
from tests.test_producer import tiny_mp4
from tests.test_select_flow import flow_dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import acceptance_flow as acc  # noqa: E402
import flow_report  # noqa: E402


def flow(fid: str, title: str, **kw: Any) -> CoreFlow:
    return CoreFlow.model_validate(flow_dict(fid, title=title, **kw))


def user(name: str, tmp_path: Path) -> acc.FlowUser:
    return acc.FlowUser(acc.SITES[name], tmp_path, Console(quiet=True))


# --- the scripted user -------------------------------------------------------------------------


def test_orangehrm_describes_its_flow_then_picks_it_and_never_allows_submit(tmp_path: Path) -> None:
    u = user("orangehrm", tmp_path)
    shared = "https://opensource-demo.orangehrmlive.com/"
    first = u.ask(build_request("j", [flow("a", "Xem hồ sơ")], shared))
    assert first.answers and first.answers["flow_description"].startswith("Nhân viên xin nghỉ phép")
    mine = flow("user_x", "Xin nghỉ phép", source="user")
    second = u.ask(build_request("j", [flow("a", "Xem hồ sơ"), mine], shared, default=["user_x"]))
    assert second.answers == {"selected_flows": ["user_x"]}  # no allow_submit on a shared site


def test_todomvc_describes_its_task_list_flow_and_allows_submit(tmp_path: Path) -> None:
    u = user("todomvc", tmp_path)
    url = "https://todomvc.com/examples/react/dist/"
    first = u.ask(build_request("j", [flow("a", "Thêm việc cần làm mới")], url))
    assert first.answers["flow_description"].startswith("Lên danh sách việc")  # type: ignore[index]
    mine = flow("u", "Lên danh sách việc trong ngày", source="user")
    answers = u.ask(build_request("j", [flow("a", "Thêm việc"), mine], url, default=["u"])).answers
    assert answers == {"selected_flows": ["u"], "allow_submit": "true", "submit_confirmed": "true"}


def test_a_site_without_a_matching_proposal_gets_its_flow_described(tmp_path: Path) -> None:
    u = user("squoosh", tmp_path)
    req = build_request("j", [flow("a", "Đăng ký tài khoản")], "https://squoosh.app/")
    assert u.ask(req).answers["flow_description"].startswith("Nén một ảnh")  # type: ignore[index]
    again = build_request(
        "j", [flow("a", "Đăng ký"), flow("u", "Nén ảnh", source="user")], "https://squoosh.app/"
    )
    assert u.ask(again).answers == {"selected_flows": ["u"]}


def test_a_storyboard_that_missed_the_goal_is_rerun_once_then_not_filmed(tmp_path: Path) -> None:
    u = user("squoosh", tmp_path)
    f = flow("leave", "x")
    partial = storyboard_request("j", f, make_run("partial"))
    assert u.ask(partial).action == "regenerate"
    assert (
        u.ask(partial).action == "cancel"
    )  # rerun once; a flow that did not get there is not filmed
    failed = storyboard_request("j", f, make_run("failed", tail=False))
    assert u.ask(failed).action == "cancel"
    assert u.ask(storyboard_request("j", f, make_run())).action == "approve"
    assert [e["event"] for e in u.log].count("regenerate") == 1


def test_orangehrm_saves_the_demo_account_when_asked_to_sign_in(tmp_path: Path) -> None:
    from app.core.credentials import CredentialStore
    from app.core.interaction import make_request

    u = user("orangehrm", tmp_path)
    request = make_request(
        "j", "login_required", "cần đăng nhập",
        login={"reason": "requested", "methods": ["credentials"]},
    )  # fmt: skip
    assert u.ask(request).answers == {"login_method": "credentials"}
    assert CredentialStore(tmp_path).load() == ("Admin", "admin123")


# --- the report --------------------------------------------------------------------------------


@pytest.fixture
def job(tmp_path: Path) -> Path:
    directory = tmp_path / "job"
    steps = directory / "flow" / "steps"
    steps.mkdir(parents=True)
    run = make_run()
    for s in run.steps:
        s.screenshot = f"flow/steps/s{s.i}.jpg"
        Image.new("RGB", (160, 90), (s.i * 30, 80, 120)).save(directory / s.screenshot)
    data = json.loads(run.model_dump_json())
    data["report"] = {
        "model": "deepseek-flash", "used_images": True, "llm_calls": 7, "prompt_tokens": 9000,
        "completion_tokens": 700, "seconds": 38.2, "write_requests": [], "invented_refs": 1,
        "repeat_warnings": 0,
    }  # fmt: skip
    data["warnings"] = ["một cảnh báo"]
    (directory / "flow" / "flow_approved.json").write_text(json.dumps(data), encoding="utf-8")
    script = {"scenes": [
        {"id": "s1", "type": "hook", "voiceover": "Hook"},
        {"id": "s2", "type": "feature_demo", "chapter_id": "c1", "voiceover": "Mở form nhanh"},
        {"id": "s3", "type": "feature_demo", "chapter_id": "c2", "voiceover": "Điền xong trong chốc lát"},
        {"id": "s4", "type": "cta", "voiceover": "Thử ngay"},
    ]}  # fmt: skip
    (directory / "script_approved.json").write_text(json.dumps(script), encoding="utf-8")
    report = {
        "actual_ms": 8000, "footage_ratio": 0.75,
        "scenes": [{"id": "s2", "final_ms": 6200, "recording": "recording"},
                   {"id": "s3", "final_ms": 9100, "recording": "recording"}],
        "flow": {"replayed": 6, "replay_failed_at": None, "notes": ["ghi chú quay"], "write_requests": []},
    }  # fmt: skip
    (directory / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (directory / "state.json").write_text(
        json.dumps({"url": "https://opensource-demo.orangehrmlive.com/"}), "utf-8"
    )
    (directory / "script_usage.json").write_text(
        json.dumps({"steps": {"flow_agent": {"input": 9000, "output": 700, "calls": 7}}}), "utf-8"
    )
    tiny_mp4(directory / "video.mp4")
    return directory


def test_the_report_has_the_storyboard_numbers_chapter_table_and_contact_sheet(
    job: Path, tmp_path: Path
) -> None:
    out = tmp_path / "docs"
    numbers = flow_report.build(job, out, "orangehrm")
    assert numbers["status"] == "stopped_before_submit" and numbers["agent_llm_calls"] == 7
    assert numbers["write_requests"] == 0 and numbers["writes_ok"] and numbers["shared_demo_site"]
    assert numbers["replayed"] == 6 and numbers["agent_tokens"] == 9700
    text = (out / "orangehrm.md").read_text(encoding="utf-8")
    assert "Request ghi dữ liệu: 0" in text and "✔" in text
    assert "| Mở form | 1–2 | 6.2 s | recording | Mở form nhanh |" in text
    assert (
        "| flow_agent | 7 | 9000 | 700 |" in text
        and "một cảnh báo" in text
        and "ghi chú quay" in text
    )
    assert (out / "orangehrm-contact-sheet.png").is_file() and "contact-sheet.png" in text
    assert (out / "orangehrm" / "steps" / "s3.jpg").is_file()
    assert json.loads((out / "orangehrm-flow_run.json").read_text("utf-8"))["flow_id"] == "leave"


def test_a_write_on_a_stopped_flow_is_flagged(job: Path, tmp_path: Path) -> None:
    report = json.loads((job / "report.json").read_text("utf-8"))
    report["flow"]["write_requests"] = ["POST https://x.test/api/leave"]
    (job / "report.json").write_text(json.dumps(report), encoding="utf-8")
    numbers = flow_report.build(job, tmp_path / "docs", "x")
    assert numbers["write_requests"] == 1 and not numbers["writes_ok"]
    assert "PHẢI LÀ 0" in (tmp_path / "docs" / "x.md").read_text(encoding="utf-8")


def test_a_job_without_a_flow_run_has_no_report(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        flow_report.build(tmp_path, tmp_path / "docs", "none")
