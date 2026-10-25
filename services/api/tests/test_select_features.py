import json
from pathlib import Path

from app.pipeline.frontend import ScriptedFrontend
from app.pipeline.proposal_run import Cancelled, ProposalRunner
from app.schemas.generated.product_profile import ProductProfile
from tests.test_explorer import feature, profile


def base() -> ProductProfile:
    feats = [
        {**feature("create_todo", None, []), "name": "Tạo việc", "demo_kind": "interaction"},
        {**feature("filter_todos", None, []), "name": "Lọc việc", "demo_kind": "navigation"},
        {**feature("export", None, []), "name": "Xuất file", "demo_kind": "failed"},
    ]
    return profile(feats)


def runner(tmp_path: Path, answers: dict, explore=None) -> ProposalRunner:  # type: ignore[no-untyped-def,type-arg]
    return ProposalRunner(
        "j",
        tmp_path,
        None,  # type: ignore[arg-type]  # select_features makes no LLM call
        ScriptedFrontend(answers),
        explore_more=explore or (lambda urls, desc: base()),
    )


def test_selection_keeps_the_users_order(tmp_path: Path) -> None:
    answers = {
        "select_features": [
            {"action": "answer", "answers": {"selected_features": ["filter_todos", "create_todo"]}}
        ]
    }
    _, selected = runner(tmp_path, answers).select_features(base())
    assert selected == ["filter_todos", "create_todo"]
    assert (
        json.loads((tmp_path / "selected_features.json").read_text("utf-8"))["selected"] == selected
    )


def test_auto_answer_takes_the_preselected_defaults(tmp_path: Path) -> None:
    _, selected = runner(tmp_path, {}).select_features(base())
    assert selected == ["create_todo", "filter_todos"]  # failed "export" is not preselected


def test_invalid_answers_are_asked_again(tmp_path: Path) -> None:
    answers = {
        "select_features": [
            {"action": "answer", "answers": {"selected_features": ["nope"]}},
            {"action": "answer", "answers": {"selected_features": ["export"]}},
        ]
    }
    _, selected = runner(tmp_path, answers).select_features(base())
    assert selected == ["export"]


def test_explore_more_adds_features_marked_new_and_asks_again(tmp_path: Path) -> None:
    def explore(urls: list[str], desc: str | None) -> ProductProfile:
        assert desc == "Lộ trình học theo vai trò"
        extra = {**feature("role_paths", None, []), "name": "Lộ trình theo vai trò"}
        return profile([f.model_dump() for f in base().features] + [extra])

    answers = {
        "select_features": [
            {"action": "explore_more", "explore": {"description": "Lộ trình học theo vai trò"}},
            {"action": "answer", "answers": {"selected_features": ["role_paths", "create_todo"]}},
        ]
    }
    r = runner(tmp_path, answers, explore)
    asked: list[list[str]] = []
    original = r._ask

    def spy(request):  # type: ignore[no-untyped-def]
        asked.append(request.selection.new_ids)
        return original(request)

    r._ask = spy  # type: ignore[method-assign]
    profile_out, selected = r.select_features(base())
    assert asked == [[], ["role_paths"]]  # the second card flags the new feature
    assert selected == ["role_paths", "create_todo"]
    assert "role_paths" in {f.id for f in profile_out.features}  # and the profile now has it


def test_a_finished_selection_is_reused_on_resume(tmp_path: Path) -> None:
    answers = {
        "select_features": [{"action": "answer", "answers": {"selected_features": ["export"]}}]
    }
    runner(tmp_path, answers).select_features(base())
    again = runner(tmp_path, {"select_features": [{"action": "cancel"}]})
    assert again.select_features(base())[1] == ["export"]  # no question asked


def test_cancel_stops_the_job(tmp_path: Path) -> None:
    try:
        runner(tmp_path, {"select_features": [{"action": "cancel"}]}).select_features(base())
    except Cancelled:
        return
    raise AssertionError("expected Cancelled")


class FakeQuestionary:
    """Stands in for the questionary module: checkbox picks, then select answers in order."""

    class Choice:
        def __init__(self, title: str, value: str, checked: bool = False) -> None:
            self.title, self.value, self.checked = title, value, checked

    def __init__(self, picks: list[str], priorities: list[str]) -> None:
        self.picks, self.priorities = picks, priorities
        self.defaults: list[str] = []

    def checkbox(self, _msg: str, choices: list) -> "FakeQuestionary":  # type: ignore[type-arg]
        self.defaults = [c.value for c in choices if c.checked]
        return _Ask(self.picks)  # type: ignore[return-value]

    def select(self, _msg: str, choices: list) -> "FakeQuestionary":  # type: ignore[type-arg]
        return _Ask(self.priorities.pop(0))  # type: ignore[return-value]


class _Ask:
    def __init__(self, value: object) -> None:
        self.value = value

    def ask(self) -> object:
        return self.value


def test_terminal_menu_asks_the_priority_order_and_preselects_the_defaults() -> None:
    from app.pipeline.frontend import TerminalFrontend
    from app.proposal.selection import build_request

    request = build_request("j", base(), ["create_todo", "filter_todos"], new_ids=["export"])
    fake = FakeQuestionary(["create_todo", "filter_todos", "export"], ["export", "create_todo"])
    response = TerminalFrontend()._ask_selection(request, fake)
    assert fake.defaults == ["create_todo", "filter_todos"]
    assert (response.answers or {})["selected_features"] == [
        "export",
        "create_todo",
        "filter_todos",
    ]
