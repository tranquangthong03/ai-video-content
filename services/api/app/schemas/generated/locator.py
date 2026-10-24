# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class Bbox(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    x: float
    y: float
    w: float
    h: float


class LocatorSpec(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    role: str | None = None
    name: Annotated[
        str | None, Field(description='Accessible name as computed by the browser')
    ] = None
    text: Annotated[
        str | None, Field(description='innerText, at most 80 characters')
    ] = None
    css: Annotated[
        str | None,
        Field(
            description='A unique stable selector when nth is null, otherwise a query whose nth match is the element'
        ),
    ] = None
    nth: Annotated[int | None, Field(ge=0)] = None
    tag: str | None = None
    fingerprint: Annotated[
        str | None, Field(description='tag|normalized text|relative position')
    ] = None
    bbox: Bbox | None = None
