# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import action as action_1
from . import locator as locator_1


class Chapter(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: str
    title: str
    step_ids: list[int]
    value_line: str | None = None


class Report(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    model: str | None = None
    used_images: bool = False
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0
    write_requests: list[str] = []
    invented_refs: Annotated[
        int, Field(description='Actions that named a ref not in the list')
    ] = 0
    repeat_warnings: int = 0


class Step(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    i: Annotated[int, Field(ge=1)]
    action: action_1.BrowserAction
    locator: Annotated[
        locator_1.LocatorSpec | None,
        Field(
            description='The spec that resolved when the agent acted; replay copies it into action.locator'
        ),
    ] = None
    target_text: str | None = None
    value: str | None = None
    url_before: str | None = None
    url_after: str | None = None
    screenshot: Annotated[
        str | None,
        Field(
            description='Path (relative to the job dir) of the viewport after the step'
        ),
    ] = None
    note: Annotated[
        str, Field(description='One Vietnamese sentence for the viewer')
    ] = ''
    chapter_id: str | None = None
    t_ms_hint: Annotated[int | None, Field(ge=0)] = None


class FlowRun(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    flow_id: str
    status: Literal['reached_goal', 'stopped_before_submit', 'partial', 'failed']
    steps: list[Step]
    chapters: list[Chapter]
    sample_data: dict[str, Any] = {}
    warnings: list[str] = []
    llm_calls: Annotated[int, Field(ge=0)] = 0
    submit_policy: Literal['stop', 'allow'] = 'stop'
    stop_ref: Annotated[
        str | None,
        Field(
            description='stopped_before_submit: the button the agent stopped at (step index of its hover)'
        ),
    ] = None
    report: Annotated[
        Report | None,
        Field(
            description='How the run went: model, images, calls, tokens, seconds, write requests'
        ),
    ] = None
