# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class BriefSuggestions(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    audience: list[str]
    main_benefit: list[str]
    offer: list[str]
