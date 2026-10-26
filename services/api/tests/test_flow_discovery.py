from pathlib import Path
from typing import Any

from app.flows.discovery import (
    PageSummary,
    check_flow,
    normalize_flow,
    page_key,
    pages_text,
    propose_flows,
)
from app.llm.json_call import JsonCaller
from app.schemas.generated.core_flow import CoreFlow
from app.schemas.generated.product_profile import ProductProfile
from tests.conftest import FakeLLM

HOME = "https://hr.example.com/dashboard"
PAGES = [
    PageSummary(url=HOME, title="Dashboard", purpose="Tổng quan", nav=["Leave", "PIM"]),
    PageSummary(url="https://hr.example.com/leave/apply/", title="Apply Leave", purpose="Xin nghỉ"),
    PageSummary(url="https://hr.example.com/login", title="Đăng nhập", purpose="Đăng nhập"),
    PageSummary(url="https://hr.example.com/admin/settings", title="Settings", purpose="Cấu hình"),
]


def profile(site_type: str = "web_app") -> ProductProfile:
    return ProductProfile.model_validate(
        {
            "site_type": site_type, "product_name": "HR", "one_liner": "Quản lý nhân sự",
            "target_users": ["Nhân viên"], "value_props": ["Xin nghỉ nhanh"],
            "features": [
                {"id": "leave", "name": "Leave", "description": "d", "evidence": [], "importance": 0.8}
            ],
        }
    )  # fmt: skip


def flow(**kw: Any) -> dict[str, Any]:
    base = {
        "id": "leave", "title": "Xin nghỉ phép", "persona": "Nhân viên", "goal": "Xin nghỉ 2 ngày",
        "start_url": HOME, "expected_steps": ["Mở Leave", "Chọn loại", "Chọn ngày", "Ghi lý do"],
        "success_signal": "Form đã điền", "needs_submit": True, "value": "Xin nghỉ trong 1 phút",
        "related_feature_ids": ["leave", "ghost"], "confidence": 0.8, "notes": None,
    }  # fmt: skip
    return {**base, **kw}


def caller(tmp_path: Path, *answers: list[dict[str, Any]]) -> tuple[JsonCaller, FakeLLM]:
    queue = list(answers)
    llm = FakeLLM(lambda _p: {"flows": queue.pop(0) if len(queue) > 1 else queue[0]})
    return JsonCaller(llm, cache_dir=tmp_path), llm


def test_page_keys_ignore_scheme_slash_fragment_and_www() -> None:
    assert page_key("http://www.hr.example.com/leave/#top") == page_key(
        "https://hr.example.com/leave"
    )
    assert page_key(HOME) != page_key(HOME + "?tab=2")


def test_a_flow_must_start_on_an_explored_real_page_and_have_3_to_10_steps() -> None:
    ok = CoreFlow.model_validate(flow())
    assert check_flow(ok, PAGES) == []
    for url in ("https://hr.example.com/unknown", PAGES[2].url, PAGES[3].url):
        assert check_flow(CoreFlow.model_validate(flow(start_url=url)), PAGES)
    assert check_flow(CoreFlow.model_validate(flow(expected_steps=["a", "b"])), PAGES)
    assert check_flow(CoreFlow.model_validate(flow(expected_steps=list("abcdefghijk"))), PAGES)


def test_proposed_flows_are_cleaned_ordered_and_capped(tmp_path: Path) -> None:
    flows = [
        flow(id="a"), flow(id="a", title="Xem hồ sơ"), flow(start_url=PAGES[2].url, id="bad"),
        *(flow(id=f"x{i}", title=f"Luồng {i}") for i in range(6)),
    ]  # fmt: skip
    c, _ = caller(tmp_path, flows)
    out = propose_flows(c, profile(), PAGES)
    assert len(out) == 5 and len({f.id for f in out}) == 5
    assert [f.title for f in out][:2] == ["Xin nghỉ phép", "Xem hồ sơ"]  # the model's order
    assert all(f.related_feature_ids == ["leave"] and f.source == "proposed" for f in out)
    assert "bad" not in {f.id for f in out}


def test_when_nothing_is_valid_it_retries_once_with_the_reasons(tmp_path: Path) -> None:
    c, llm = caller(tmp_path, [flow(start_url="https://hr.example.com/nope")], [flow()])
    out = propose_flows(c, profile(), PAGES)
    assert [f.id for f in out] == ["leave"] and len(llm.calls) == 2
    assert "không thuộc các trang đã khám phá" in llm.calls[1]["prompt"]


def test_still_nothing_falls_back_to_a_tour_that_never_submits(tmp_path: Path) -> None:
    c, _ = caller(tmp_path, [flow(start_url="https://hr.example.com/nope")])
    out = propose_flows(c, profile(), PAGES)
    assert [f.id for f in out] == ["tour"]
    tour = out[0]
    assert not tour.needs_submit and tour.start_url == HOME and len(tour.expected_steps) >= 3
    assert all(PAGES[i].title not in " ".join(tour.expected_steps) for i in (2, 3))


def test_a_landing_site_never_needs_submit_and_gets_a_value_tour(tmp_path: Path) -> None:
    c, _ = caller(tmp_path, [flow(id="signup", needs_submit=True)])
    out = propose_flows(c, profile("landing"), PAGES)
    assert not any(f.needs_submit for f in out)
    assert out[-1].id == "tour"


def test_normalize_keeps_the_users_meaning_and_marks_it_as_theirs(tmp_path: Path) -> None:
    c, llm = caller(tmp_path, [flow(id="x", title="Xin nghỉ phép 2 ngày rồi xem đơn")])
    out = normalize_flow(
        c, profile(), PAGES, "Nhân viên xin nghỉ phép 2 ngày rồi xem trạng thái đơn"
    )
    assert out and out.source == "user" and out.id.startswith("user_") and out.confidence == 0.8
    assert "<mode>normalize</mode>" in llm.calls[0]["prompt"]
    assert "xem trạng thái đơn" in llm.calls[0]["prompt"]


def test_normalize_with_an_unexplored_start_lowers_confidence_and_notes_it(tmp_path: Path) -> None:
    c, _ = caller(
        tmp_path, [flow(start_url="https://hr.example.com/not-seen", expected_steps=["Mở"])]
    )
    out = normalize_flow(c, profile(), PAGES, "xin nghỉ")
    assert (
        out and out.start_url.endswith("/leave/apply/") and out.confidence <= 0.3
    )  # nearest to "xin nghỉ"
    assert out.notes and "không thuộc" in out.notes and "bổ sung" in out.notes


def test_normalize_needs_a_description_and_is_capped(tmp_path: Path) -> None:
    c, llm = caller(tmp_path, [flow()])
    assert normalize_flow(c, profile(), PAGES, "   ") is None and not llm.calls
    normalize_flow(c, profile(), PAGES, "x" * 2000)
    assert "x" * 501 not in llm.calls[0]["prompt"]


def test_the_pages_are_listed_with_actions_and_nav() -> None:
    text = pages_text(
        [PageSummary(url=HOME, title="D", purpose="P", actions=["Apply"], nav=["Leave"])]
    )
    assert HOME in text and "actions: Apply" in text and "nav: Leave" in text


def test_normalize_picks_the_explored_page_closest_to_the_description(tmp_path: Path) -> None:
    pages = [
        *PAGES,
        PageSummary(
            url="https://hr.example.com/recruitment/candidates",
            title="Candidates",
            purpose="Ứng viên",
        ),
    ]
    c, _ = caller(tmp_path, [flow(start_url=HOME, title="Thêm candidates mới")])
    out = normalize_flow(c, profile(), pages, "Thêm candidates: vào Recruitment, bấm Add")
    assert out and out.start_url.endswith(
        "/recruitment/candidates"
    )  # the model's HOME had no link to it
    c, _ = caller(tmp_path / "2", [flow(start_url=HOME, title="Mở Dashboard")])
    kept = normalize_flow(c, profile(), pages, "Mở Dashboard xem tổng quan")
    assert kept and kept.start_url == HOME  # a start that matches the description is left alone
