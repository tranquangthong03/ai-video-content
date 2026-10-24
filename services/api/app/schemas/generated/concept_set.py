# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from . import video_concept


class ConceptSet(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    concepts: Annotated[
        list[video_concept.VideoConcept], Field(max_length=3, min_length=3)
    ]
