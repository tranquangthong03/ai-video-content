"""Internal explorer data models (not shared schemas, so not in script-schema)."""

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.generated.locator import Bbox, LocatorSpec


class FormData(BaseModel):
    method: str = "get"
    action: str = ""
    text_inputs: int = 0
    sensitive: bool = False


class Element(BaseModel):
    ref: str
    role: str
    name: str  # accessible name as the browser computes it (falls back to the visible text)
    region: str  # header | nav | main | aside | footer
    tag: str = ""
    text: str = ""  # innerText, at most 80 characters
    href: str | None = None
    selector: str | None = None  # stable unique css (data-testid / id / aria-label), else None
    locator: LocatorSpec = Field(default_factory=LocatorSpec)
    input_type: str | None = None
    button_type: str | None = None  # <button type=..>; "submit" when absent
    accept: str | None = None  # <input type=file accept=..>
    in_form: bool = False
    form: FormData | None = None
    caps: list[str] = Field(default_factory=list)  # e.g. ["upload"]

    def spec(self) -> LocatorSpec:
        """The locator to resolve; elements built by hand fall back to role/name/selector."""
        if self.locator.model_dump(exclude_none=True):
            return self.locator
        return LocatorSpec(
            role=self.role, name=self.name, text=self.text or None, css=self.selector, tag=self.tag
        )

    @property
    def bbox(self) -> Bbox | None:
        return self.locator.bbox


class Heading(BaseModel):
    level: int
    text: str


class Anchor(BaseModel):
    """A same-page section reached by a `#id` link (e.g. /#pricing); never crawled as a page."""

    id: str
    selector: str
    text: str = ""


class PageData(BaseModel):
    n: int
    url: str
    title: str = ""
    meta_description: str = ""
    og_description: str = ""
    headings: list[Heading] = Field(default_factory=list)
    key_texts: list[str] = Field(default_factory=list)
    elements: list[Element] = Field(default_factory=list)
    anchors: list[Anchor] = Field(default_factory=list)
    signals: dict[str, Any] = Field(default_factory=dict)
    layout: dict[str, Any] = Field(default_factory=dict)  # DOM-derived layout description
    screenshot: str | None = None
    depth: int = 0
    score: float = 0.0

    def element(self, ref: str) -> Element | None:
        return next((e for e in self.elements if e.ref == ref), None)
