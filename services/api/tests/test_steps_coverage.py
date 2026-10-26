import types

from app.producer.steps_coverage import operation_steps, steps_in_clip
from app.schemas.generated.flow_run import FlowRun


def run_with(*dos: str) -> FlowRun:
    steps = [
        {
            "i": i,
            "action": {"do": do},
            "chapter": "c",
            "note": "n",
            "url_before": "u",
            "url_after": "u",
        }
        for i, do in enumerate(dos, 1)
    ]
    return FlowRun.model_construct(
        steps=[
            types.SimpleNamespace(
                **{**s, "i": s["i"], "action": types.SimpleNamespace(do=s["action"]["do"])}
            )
            for s in steps
        ]
    )


def test_the_opening_goto_is_not_an_operation() -> None:
    assert operation_steps(run_with("goto", "click", "type")) == [2, 3]


def test_steps_in_clip_is_the_share_of_operations_whose_mark_survived() -> None:
    r = steps_in_clip(run_with("goto", "click", "type", "hover", "highlight"), [1, 2, 4, 5])
    assert r["steps_in_clip"] == 0.75 and r["missing_steps"] == [3]
    assert (
        steps_in_clip(run_with("goto"), [])["steps_in_clip"] == 1.0
    )  # nothing to film, nothing lost
