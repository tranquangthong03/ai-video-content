# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import scene
from . import theme as theme_1


class Capture(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    viewport: Literal['desktop', 'mobile'] = 'desktop'
    width: Annotated[int, Field(ge=320, le=3840)] = 1440
    height: Annotated[int, Field(ge=320, le=3840)] = 900


class HookOption(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    kind: Literal[
        'pain_question',
        'result_first',
        'shocking_number',
        'counterintuitive',
        'you_are_doing_it_wrong',
    ]
    voiceover: Annotated[str, Field(min_length=1)]
    on_screen_text: str | None = None


class Script(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    title: Annotated[str, Field(min_length=1)]
    goal: Literal['awareness', 'conversion', 'tutorial', 'recruitment']
    aspect_ratio: Literal['9:16']
    target_duration_s: Annotated[int, Field(ge=15, le=90)]
    template: Literal['desktop_focus', 'desktop_showcase', 'phone_showcase'] = (
        'desktop_focus'
    )
    capture: Annotated[Capture, Field(validate_default=True)] = {
        'viewport': 'desktop',
        'width': 1440,
        'height': 900,
    }
    flow_id: str | None = None
    badge: Annotated[str | None, Field(max_length=24)] = None
    headline: Annotated[str, Field(max_length=40, min_length=1)]
    headline_highlight: str | None = None
    framework: Annotated[
        Literal['pain_journey_result', 'before_after_bridge'] | None,
        Field(
            description='The narrative frame the script follows (PAS shortened for a flow video; before/after/bridge for a one-page tool)'
        ),
    ] = None
    hook_options: Annotated[
        list[HookOption],
        Field(
            description='Two hooks of different kinds; the hook scene shows the chosen one',
            max_length=2,
            validate_default=True,
        ),
    ] = []
    theme: theme_1.Theme
    scenes: Annotated[list[scene.Scene], Field(max_length=6, min_length=3)]
