# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class FlowQuality(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    value_actions: Annotated[int, Field(ge=0)]
    label: Annotated[
        str | None,
        Field(description='Set when value_actions is below 2: the flow only navigates'),
    ] = None
    empty_warning: Annotated[
        str | None,
        Field(description='Set when two or more signs say the pages have no data'),
    ] = None
    empty_signals: list[str] = []
    estimated: Annotated[
        bool,
        Field(
            description='true: counted from the expected steps of a proposal, nothing has run yet'
        ),
    ] = False
