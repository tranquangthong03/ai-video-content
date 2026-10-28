# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class ProofPoint(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    value: Annotated[str, Field(description='the number as written, e.g. 40 or 2.8')]
    unit: str | None = None
    claim: Annotated[str, Field(description='the full sentence the number belongs to')]
    source_note: str | None = None


class MarketingBrief(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    audience: str | None = None
    main_benefit: str | None = None
    secondary_benefits: list[str] = []
    proof_points: Annotated[list[ProofPoint], Field(validate_default=True)] = []
    offer: str | None = None
    cta_text: str | None = None
    cta_url: str | None = None
    tone: str | None = None
    avoid: list[str] = []
