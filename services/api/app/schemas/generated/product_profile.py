# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Evidence(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    source: Literal[
        'landing_hero',
        'landing_features',
        'pricing',
        'nav',
        'app_action',
        'docs',
        'landing_claim',
    ]
    url: str
    ref: str | None = None
    quote: str | None = None


class DemoStep(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    do: Literal['goto', 'click', 'type', 'scroll', 'hover', 'wait']
    url: str | None = None
    ref: str | None = None
    text: str | None = None


class Feature(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: Annotated[str, Field(min_length=1)]
    name: Annotated[str, Field(min_length=1)]
    description: str
    evidence: list[Evidence]
    importance: Annotated[float, Field(ge=0.0, le=1.0)]
    demo_steps: Annotated[list[DemoStep], Field(validate_default=True)] = []
    demo_score: Annotated[float, Field(ge=0.0, le=1.0)] = 0
    verified: bool = False
    demo_note: str | None = None
    thumbnail: str | None = None
    source: Literal['site', 'user'] = 'site'


class ProductProfile(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    site_type: Literal['landing', 'web_app', 'ecommerce', 'tool', 'content']
    product_name: Annotated[str, Field(min_length=1)]
    one_liner: str
    target_users: list[str]
    value_props: list[str] = []
    features: Annotated[list[Feature], Field(max_length=12)]
    open_questions: list[str] = []
