# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import beat_op


class Option(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: str
    label: str


class Clarification(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    question: str
    options: Annotated[list[Option], Field(validate_default=True)] = []


class RejectedItem(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    request: str
    reason: str
    suggestion: str | None = None


class OutlineEditPlan(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    status: Literal['ok', 'needs_clarification']
    ops: Annotated[list[beat_op.BeatOp], Field(validate_default=True)] = []
    clarification: Clarification | None = None
    rejected: Annotated[list[RejectedItem], Field(validate_default=True)] = []
    warnings: list[str] = []
