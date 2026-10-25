# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

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
    methods: list[Literal['browser_window', 'credentials', 'upload_state']]
    can_enter_url: bool = False
    failure: str | None = None
    hint: str | None = None


class Selection(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    min: int
    max: int
    recommended_max: int = 3
    default: list[str]
    new_ids: list[str] = []


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
    selection: Selection | None = None
