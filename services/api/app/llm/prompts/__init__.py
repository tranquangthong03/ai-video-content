"""Jinja2 prompt templates; StrictUndefined turns a missing variable into an error."""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent),
    undefined=StrictUndefined,
    autoescape=False,
    keep_trailing_newline=True,
)

PROMPTS = ("page_analyzer", "product_synthesizer", "concept_proposer", "outline_editor")


def render(name: str, **variables: Any) -> str:
    return _env.get_template(f"{name}.md").render(**variables)
