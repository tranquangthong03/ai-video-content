# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import locator as locator_1


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
    do: Literal[
        'goto',
        'click',
        'type',
        'scroll',
        'hover',
        'wait',
        'upload',
        'dblclick',
        'right_click',
    ]
    url: str | None = None
    ref: str | None = None
    text: str | None = None
    file: Annotated[str | None, Field(description='Sample file name for do=upload')] = (
        None
    )
    locator: Annotated[
        locator_1.LocatorSpec | None,
        Field(description='Filled by code from the element behind ref'),
    ] = None


class DemoEvidence(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    url_changed: bool
    dom_delta: int
    new_dialog: bool
    new_list_items: int
    visual_diff: float
    target_page_type: str | None = None
    notes: str = ''


class ShowcaseTarget(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    url: str
    selector: str | None = None
    ref: str | None = None
    text_quote: str


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
    demo_kind: Annotated[
        Literal['interaction', 'navigation', 'showcase', 'failed'] | None,
        Field(description='null = not verified'),
    ] = None
    demo_score: Annotated[
        float, Field(description='Confidence of the demo_kind verdict', ge=0.0, le=1.0)
    ] = 0
    demo_evidence: DemoEvidence | None = None
    showcase_target: ShowcaseTarget | None = None
    requires_setup: Annotated[
        bool,
        Field(
            description='Only visible after earlier steps created some data; demo_steps then start with those setup steps'
        ),
    ] = False
    verified: bool = False
    demo_note: str | None = None
    thumbnail: str | None = None
    source: Literal['site', 'user'] = 'site'
    intent_key: Annotated[
        str | None,
        Field(
            description='Short snake_case English key of what the user does (create_item, edit_item). Features sharing a key are the same intent and get merged.'
        ),
    ] = None


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
