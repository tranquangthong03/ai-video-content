# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import locator as locator_1


class BrowserAction(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    do: Literal[
        'goto',
        'click',
        'type',
        'scroll',
        'wait',
        'hover',
        'upload',
        'dblclick',
        'right_click',
    ]
    target: Annotated[
        str | None, Field(description='Natural-language description of the element')
    ] = None
    selector: str | None = None
    locator: locator_1.LocatorSpec | None = None
    file: Annotated[str | None, Field(description='Sample file name for do=upload')] = (
        None
    )
    url: str | None = None
    text: str | None = None
    ms: Annotated[int | None, Field(ge=0)] = None
    zoom: bool = False
