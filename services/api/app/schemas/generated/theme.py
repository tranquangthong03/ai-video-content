# AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Theme(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    primary: Annotated[str, Field(pattern='^#[0-9a-fA-F]{6}$')]
    accent: Annotated[str, Field(pattern='^#[0-9a-fA-F]{6}$')]
    font: Annotated[str, Field(min_length=1)]
    logo_asset: str | None = None
    motion_preset: Literal['energetic', 'calm']
    caption_style: Literal['tiktok_bounce', 'minimal', 'karaoke']
    music_mood: Literal['energetic', 'upbeat', 'calm', 'corporate']
    voice_id: Annotated[str, Field(min_length=1)]
    language: Literal['vi', 'en']
