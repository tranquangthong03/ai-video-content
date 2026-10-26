# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class SetOp(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    op: Literal['set']
    scene_id: str
    field: Literal['voiceover', 'on_screen_text', 'layout', 'feature', 'hook_option']
    value: str


class RewriteOp(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    op: Literal['rewrite']
    scene_id: str
    fields: Annotated[
        list[Literal['voiceover', 'on_screen_text', 'visual']], Field(min_length=1)
    ]
    instruction: str


class DeleteOp(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    op: Literal['delete']
    scene_id: str


class InsertOp(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    op: Literal['insert']
    after_scene_id: str | None
    scene_type: Literal['hook', 'feature_demo', 'before_after', 'cta']
    instruction: str


class MoveOp(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    op: Literal['move']
    scene_id: str
    after_scene_id: str | None


class SetThemeOp(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    op: Literal['set_theme']
    field: Literal[
        'motion_preset', 'caption_style', 'music_mood', 'voice_id', 'primary'
    ]
    value: str


class SetGlobalOp(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    op: Literal['set_global']
    field: Literal['goal', 'tone', 'duration', 'audience', 'cta', 'features']
    value: str | list[str]


class EditOp(
    RootModel[
        SetOp | RewriteOp | DeleteOp | InsertOp | MoveOp | SetThemeOp | SetGlobalOp
    ]
):
    root: Annotated[
        SetOp | RewriteOp | DeleteOp | InsertOp | MoveOp | SetThemeOp | SetGlobalOp,
        Field(discriminator='op', title='EditOp'),
    ]
