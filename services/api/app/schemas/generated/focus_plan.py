# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class PlanItem(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    from_ms: Annotated[int, Field(ge=0)]
    to_ms: Annotated[int, Field(ge=0)]
    item_id: str | None = None
    framing: Literal['establish', 'tight', 'medium', 'wide']
    reason: str = ''


class FocusPlan(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    plan: list[PlanItem]
