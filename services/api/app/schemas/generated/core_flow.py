# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class CoreFlow(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: Annotated[str, Field(min_length=1)]
    title: Annotated[str, Field(min_length=1)]
    persona: str
    goal: str
    start_url: str
    expected_steps: Annotated[list[str], Field(max_length=12, min_length=1)]
    success_signal: str
    needs_submit: bool
    value: Annotated[str, Field(description='One-sentence benefit for the persona')]
    related_feature_ids: list[str] = []
    source: Literal['proposed', 'user'] = 'proposed'
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.7
    notes: str | None = None
