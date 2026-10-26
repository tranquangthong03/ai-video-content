# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

from . import action


class Stat(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    value: Annotated[str, Field(max_length=12, min_length=1)]
    label: Annotated[str, Field(max_length=30, min_length=1)]


class Visual(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    mode: Literal['recording', 'screenshot', 'template']
    page: str | None = None
    effect: str | None = None
    actions: Annotated[list[action.BrowserAction], Field(validate_default=True)] = []
    setup: Annotated[
        list[action.BrowserAction],
        Field(
            description='Steps that prepare the state (e.g. add sample data) before actions',
            validate_default=True,
        ),
    ] = []
    show_setup: Annotated[
        bool, Field(description='false: the render trims the setup part off the clip')
    ] = False


class HookScene(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: Annotated[str, Field(min_length=1)]
    type: Literal['hook']
    layout: Literal['big_text_over_blur', 'emoji_pop']
    voiceover: str
    on_screen_text: str | None = None
    stat: Annotated[
        Stat | None,
        Field(
            description='A big number callout shown over the scene (value must be sourced from the proof bank)'
        ),
    ] = None
    key_point: Annotated[str | None, Field(max_length=60)] = None
    icon: (
        Literal[
            'check',
            'globe',
            'bolt',
            'link',
            'star',
            'users',
            'chart',
            'lock',
            'sparkles',
            'code',
            'image',
            'edit',
            'filter',
            'upload',
        ]
        | None
    ) = None
    visual: Visual
    duration_ms: Annotated[int | None, Field(ge=0)] = None
    chapter_id: Annotated[
        str | None,
        Field(
            description='Core-flow mode: the chapter of the flow run this scene shows'
        ),
    ] = None


class FeatureDemoScene(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: Annotated[str, Field(min_length=1)]
    type: Literal['feature_demo']
    layout: Literal['full_screen', 'phone_mockup']
    feature: Annotated[str, Field(min_length=1)]
    voiceover: str
    on_screen_text: str | None = None
    stat: Annotated[
        Stat | None,
        Field(
            description='A big number callout shown over the scene (value must be sourced from the proof bank)'
        ),
    ] = None
    key_point: Annotated[str | None, Field(max_length=60)] = None
    icon: (
        Literal[
            'check',
            'globe',
            'bolt',
            'link',
            'star',
            'users',
            'chart',
            'lock',
            'sparkles',
            'code',
            'image',
            'edit',
            'filter',
            'upload',
        ]
        | None
    ) = None
    visual: Visual
    duration_ms: Annotated[int | None, Field(ge=0)] = None
    chapter_id: Annotated[
        str | None,
        Field(
            description='Core-flow mode: the chapter of the flow run this scene shows'
        ),
    ] = None


class BeforeAfterScene(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: Annotated[str, Field(min_length=1)]
    type: Literal['before_after']
    layout: Literal['split_vertical', 'swipe', 'split_frames']
    before_text: Annotated[str, Field(min_length=1)]
    after_text: Annotated[str, Field(min_length=1)]
    voiceover: str
    on_screen_text: str | None = None
    stat: Annotated[
        Stat | None,
        Field(
            description='A big number callout shown over the scene (value must be sourced from the proof bank)'
        ),
    ] = None
    key_point: Annotated[str | None, Field(max_length=60)] = None
    icon: (
        Literal[
            'check',
            'globe',
            'bolt',
            'link',
            'star',
            'users',
            'chart',
            'lock',
            'sparkles',
            'code',
            'image',
            'edit',
            'filter',
            'upload',
        ]
        | None
    ) = None
    visual: Visual
    duration_ms: Annotated[int | None, Field(ge=0)] = None
    chapter_id: Annotated[
        str | None,
        Field(
            description='Core-flow mode: the chapter of the flow run this scene shows'
        ),
    ] = None


class CtaScene(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: Annotated[str, Field(min_length=1)]
    type: Literal['cta']
    layout: Literal['logo_center', 'button_pulse']
    voiceover: str
    on_screen_text: str | None = None
    stat: Annotated[
        Stat | None,
        Field(
            description='A big number callout shown over the scene (value must be sourced from the proof bank)'
        ),
    ] = None
    key_point: Annotated[str | None, Field(max_length=60)] = None
    icon: (
        Literal[
            'check',
            'globe',
            'bolt',
            'link',
            'star',
            'users',
            'chart',
            'lock',
            'sparkles',
            'code',
            'image',
            'edit',
            'filter',
            'upload',
        ]
        | None
    ) = None
    visual: Visual
    duration_ms: Annotated[int | None, Field(ge=0)] = None
    chapter_id: Annotated[
        str | None,
        Field(
            description='Core-flow mode: the chapter of the flow run this scene shows'
        ),
    ] = None


class Scene(RootModel[HookScene | FeatureDemoScene | BeforeAfterScene | CtaScene]):
    root: Annotated[
        HookScene | FeatureDemoScene | BeforeAfterScene | CtaScene,
        Field(discriminator='type', title='Scene'),
    ]
