# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class BrowserAction(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    do: Literal['goto', 'click', 'type', 'scroll', 'wait', 'hover']
    target: Annotated[
        str | None, Field(description='Natural-language description of the element')
    ] = None
    selector: str | None = None
    url: str | None = None
    text: str | None = None
    ms: Annotated[int | None, Field(ge=0)] = None
    zoom: bool = False
