# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Beat(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: Annotated[str, Field(pattern='^b[0-9]+$')]
    text: Annotated[str, Field(min_length=1)]
    feature_id: str | None = None


class Outline(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    concept_id: str
    title: Annotated[str, Field(min_length=1)]
    goal: Literal['awareness', 'conversion', 'tutorial', 'recruitment']
    duration_s: Literal[30, 45, 60]
    feature_ids: list[str]
    version: Annotated[int, Field(ge=1)] = 1
    beats: Annotated[list[Beat], Field(min_length=1)]
