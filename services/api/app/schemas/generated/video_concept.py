# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class VideoConcept(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: Annotated[str, Field(min_length=1)]
    angle: Literal['overview', 'deep_dive', 'pain_solution']
    title: Annotated[str, Field(min_length=1)]
    goal: Literal['awareness', 'conversion', 'tutorial', 'recruitment']
    hook_example: str
    feature_ids: list[str]
    beats: Annotated[list[str], Field(max_length=6, min_length=4)]
    duration_s: Literal[30, 45, 60]
    why: str
    recommended: bool
