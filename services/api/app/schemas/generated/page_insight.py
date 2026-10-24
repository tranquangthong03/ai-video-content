# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Action(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    ref: str
    name: str
    intent: Literal[
        'create',
        'edit',
        'filter',
        'search',
        'export',
        'share',
        'view',
        'navigate_feature',
        'other',
    ]


class ClaimedFeature(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    name: str
    quote: str


class PageInsight(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    url: str = ''
    title: str = ''
    page_type: Literal[
        'landing_hero',
        'landing_features',
        'pricing',
        'app_dashboard',
        'app_list',
        'app_editor',
        'app_detail',
        'app_settings',
        'product_listing',
        'product_detail',
        'docs',
        'other',
    ]
    purpose: str
    actions: Annotated[list[Action], Field(validate_default=True)] = []
    claimed_features: Annotated[list[ClaimedFeature], Field(validate_default=True)] = []
    visual_quality: Annotated[float, Field(ge=0.0, le=1.0)]
