# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import scene
from . import theme as theme_1


class Script(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    title: Annotated[str, Field(min_length=1)]
    goal: Literal['awareness', 'conversion', 'tutorial', 'recruitment']
    aspect_ratio: Literal['9:16']
    target_duration_s: Annotated[int, Field(ge=15, le=90)]
    theme: theme_1.Theme
    scenes: Annotated[list[scene.Scene], Field(max_length=6, min_length=3)]
