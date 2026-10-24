# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import edit_op


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


class EditPlan(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    status: Literal['ok', 'needs_clarification']
    ops: Annotated[list[edit_op.EditOp], Field(validate_default=True)] = []
    clarification: Clarification | None = None
    rejected: Annotated[list[RejectedItem], Field(validate_default=True)] = []
