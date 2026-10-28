# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import edit_op, marketing_brief


class Explore(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    urls: list[str] = []
    description: str | None = None


class AddedFeature(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    name: str
    description: str


class ProfileEdit(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    exclude_feature_ids: list[str] = []
    one_liner: str | None = None
    target_users: list[str] | None = None
    added_features: Annotated[list[AddedFeature], Field(validate_default=True)] = []


class Target(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    scene_id: str
    field: Literal['voiceover', 'on_screen_text', 'visual', 'layout', 'whole']


class Edit(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    instruction: str | None = None
    targets: Annotated[list[Target], Field(validate_default=True)] = []
    ops: Annotated[list[edit_op.EditOp], Field(validate_default=True)] = []


class UserResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    interaction_id: str
    job_id: str
    base_version: int | None = None
    action: Literal[
        'answer',
        'approve',
        'edit',
        'regenerate',
        'revert',
        'login_done',
        'cancel',
        'explore_more',
        'skip',
    ]
    explore: Annotated[
        Explore | None,
        Field(
            description='Payload of explore_more: pages to look at (urls) and/or a free-text description of them.'
        ),
    ] = None
    profile_edit: Annotated[
        ProfileEdit | None,
        Field(description='Payload of edit on confirm_understanding.'),
    ] = None
    answers: dict[str, Any] | None = None
    edit: Edit | None = None
    brief: Annotated[
        marketing_brief.MarketingBrief | None,
        Field(description='Payload of answer on marketing_brief.'),
    ] = None
    revert_to: int | None = None
