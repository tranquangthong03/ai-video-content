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


class Segment(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    from_ms: Annotated[int, Field(ge=0)]
    to_ms: Annotated[int, Field(ge=0)]
    kind: Literal['llm_wait', 'retry', 'rejected']
    step: int | None = None
    note: str = ''


class Mark(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    i: Annotated[int, Field(ge=1)]
    start_ms: Annotated[int, Field(ge=0)]
    end_ms: Annotated[int, Field(ge=0)]


class Live(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    clip: Annotated[str, Field(description='Path relative to the job dir')]
    logs: Annotated[
        str,
        Field(
            description='JSON file with focus_log, click_log, inventory, action_log, activity_ms'
        ),
    ]
    content_ms: Annotated[int, Field(ge=0)]
    start_offset_ms: Annotated[
        int, Field(description='The loading phase (and the sync pulse) ends here', ge=0)
    ]
    sync_offset_ms: Annotated[
        int, Field(description='video clock = log clock + this')
    ] = 0
    pulse_at_ms: int = 0
    segments: Annotated[list[Segment], Field(validate_default=True)] = []
    marks: Annotated[list[Mark], Field(validate_default=True)] = []


class EnvIssue(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    kind: Literal['guard_broke_page']
    blocked_urls: list[str]
    page_url: str


class GiveUp(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    reason_kind: Literal[
        'no_data',
        'no_permission',
        'feature_missing',
        'blocked_by_site',
        'stuck',
        'env_blocked',
    ]
    reason: str
    quote: Annotated[
        str | None, Field(description="The site's own message, word for word")
    ] = None


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
    guard_intents: Annotated[
        dict[str, int],
        Field(
            description='How the guard judged the non-GET requests: read / write / unknown / telemetry'
        ),
    ] = {}
    text_calls: Annotated[
        int, Field(description='LLM calls made without the screenshot')
    ] = 0
    vision_calls: Annotated[
        int, Field(description='LLM calls made with the screenshot')
    ] = 0
    escalated_because: Annotated[
        str | None,
        Field(description='Why the agent started sending screenshots (vision=auto)'),
    ] = None
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
    blank: Annotated[
        bool,
        Field(
            description='The page was still empty after waiting for its content: not a valid storyboard step'
        ),
    ] = False
    no_effect: Annotated[
        bool,
        Field(
            description='The page did not change after this action: not counted in the flow'
        ),
    ] = False
    flag_reason: Annotated[
        str | None, Field(description='blank_page | guard_broke_page | no_effect')
    ] = None


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
    live: Live | None = None
    goal_status: Annotated[
        Literal['reached', 'stopped_before_submit', 'not_reached'] | None,
        Field(
            description='Computed by code from the actions the user asked for and the real steps; the model never sets it'
        ),
    ] = None
    env_issues: Annotated[
        list[EnvIssue],
        Field(
            description='Pages that stayed empty because the request guard refused the requests they need (environment, not the site)',
            validate_default=True,
        ),
    ] = []
    give_up: GiveUp | None = None
    report: Annotated[
        Report | None,
        Field(
            description='How the run went: model, images, calls, tokens, seconds, write requests'
        ),
    ] = None
