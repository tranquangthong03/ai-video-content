# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import brief_suggestions, core_flow
from . import flow_quality as flow_quality_1
from . import flow_run, marketing_brief
from . import outline as outline_1
from . import product_profile, video_concept


class Option(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: str
    label: str
    description: str | None = None


class Question(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: str
    text: str
    type: Literal['single', 'multi', 'text']
    options: Annotated[list[Option], Field(validate_default=True)] = []
    allow_custom: bool = False


class SummaryItem(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    scene_id: str
    one_liner: str


class Login(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    login_url: str | None = None
    target_url: str | None = None
    reason: str
    methods: list[Literal['browser_window', 'credentials', 'upload_state', 'public']]
    can_enter_url: bool = False
    failure: str | None = None
    hint: str | None = None


class FlowSelect(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    max: int
    default: list[str]
    submit_blocked_reason: Annotated[
        str | None,
        Field(
            description='Set when the site is a shared demo: allowing submit is refused'
        ),
    ] = None
    infeasible: Annotated[
        dict[str, str],
        Field(
            description="flow id -> the site's own message: this flow cannot be done with this account"
        ),
    ] = {}
    quality: Annotated[
        dict[str, flow_quality_1.FlowQuality],
        Field(
            description='flow id -> how many steps make something visible appear (value_actions) and the label when it is too few',
            validate_default=True,
        ),
    ] = {}
    empty_warning: Annotated[
        str | None,
        Field(
            description='Set when the explored pages show the account has no data (two or more signs)'
        ),
    ] = None
    env_warning: Annotated[
        str | None,
        Field(
            description='Set when a page stayed empty because the request guard refused its requests'
        ),
    ] = None


class Selection(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    min: int
    max: int
    recommended_max: int = 3
    default: list[str]
    new_ids: list[str] = []


class BriefForm(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    suggestions: brief_suggestions.BriefSuggestions
    note: str
    draft: marketing_brief.MarketingBrief | None = None


class InteractionRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    interaction_id: str
    job_id: str
    kind: Literal[
        'clarify',
        'login_required',
        'script_review',
        'video_review',
        'confirm_understanding',
        'select_features',
        'choose_concept',
        'outline_review',
        'select_flow',
        'flow_storyboard_review',
        'marketing_brief',
    ]
    message: str
    questions: Annotated[list[Question], Field(validate_default=True)] = []
    script_version: int | None = None
    summary: list[SummaryItem] | None = None
    changes: list[str] | None = None
    live_login_url: str | None = None
    video_url: str | None = None
    allowed_actions: list[str]
    profile: product_profile.ProductProfile | None = None
    concepts: list[video_concept.VideoConcept] | None = None
    outline: outline_1.Outline | None = None
    login: Login | None = None
    flows: Annotated[
        list[core_flow.CoreFlow] | None,
        Field(
            description='select_flow: the proposed flows; answers.selected_flows is the ordered id list'
        ),
    ] = None
    flow_select: FlowSelect | None = None
    flow_review: Annotated[
        flow_run.FlowRun | None,
        Field(
            description='flow_storyboard_review: the run to look at (steps carry screenshot paths)'
        ),
    ] = None
    flow_quality: Annotated[
        flow_quality_1.FlowQuality | None,
        Field(
            description='flow_storyboard_review: is the run worth filming (value actions, empty pages)'
        ),
    ] = None
    brief_form: BriefForm | None = None
    selection: Selection | None = None
