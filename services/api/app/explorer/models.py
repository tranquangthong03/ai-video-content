"""Internal explorer data models (not shared schemas, so not in script-schema)."""

from typing import Any

from pydantic import BaseModel, Field


class Element(BaseModel):
    ref: str
    role: str
    name: str
    region: str  # header | nav | main | aside | footer
    tag: str = ""
    href: str | None = None
    selector: str | None = None  # data-testid / id / aria-label based, None when nothing stable
    locator_role: str | None = None  # fallback: page.get_by_role(locator_role, name=locator_name)
    locator_name: str | None = None
    input_type: str | None = None
    button_type: str | None = None  # <button type=..>; defaults to "submit" when absent
    in_form: bool = False
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)  # x, y, w, h


class Heading(BaseModel):
    level: int
    text: str


class PageData(BaseModel):
    n: int
    url: str
    title: str = ""
    meta_description: str = ""
    og_description: str = ""
    headings: list[Heading] = Field(default_factory=list)
    key_texts: list[str] = Field(default_factory=list)
    elements: list[Element] = Field(default_factory=list)
    signals: dict[str, Any] = Field(default_factory=dict)
    layout: dict[str, Any] = Field(default_factory=dict)  # DOM-derived layout description
    screenshot: str | None = None
    depth: int = 0
    score: float = 0.0

    def element(self, ref: str) -> Element | None:
        return next((e for e in self.elements if e.ref == ref), None)
