# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class SetBeatOp(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    op: Literal['set']
    beat_id: str
    text: Annotated[str, Field(min_length=1)]
    feature_id: str | None = None


class DeleteBeatOp(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    op: Literal['delete']
    beat_id: str


class InsertBeatOp(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    op: Literal['insert']
    after_beat_id: str | None
    text: Annotated[str, Field(min_length=1)]
    feature_id: str | None = None


class MoveBeatOp(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    op: Literal['move']
    beat_id: str
    after_beat_id: str | None


class SetMetaOp(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    op: Literal['set_meta']
    field: Literal['title', 'goal', 'duration_s']
    value: str | float


class BeatOp(
    RootModel[SetBeatOp | DeleteBeatOp | InsertBeatOp | MoveBeatOp | SetMetaOp]
):
    root: Annotated[
        SetBeatOp | DeleteBeatOp | InsertBeatOp | MoveBeatOp | SetMetaOp,
        Field(discriminator='op', title='BeatOp'),
    ]
