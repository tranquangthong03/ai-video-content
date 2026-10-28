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

PROMPTS = (
    "page_analyzer",
    "product_synthesizer",
    "concept_proposer",
    "outline_editor",
    "beat_feature_mapper",
    "script_writer",
    "duration_fit",
    "scene_writer",
    "edit_planner",
    "focus_planner",
    "flow_discovery",
    "flow_agent",
    "copy_critic",
    "hook_rewrite",
    "brief_suggest",
)


def render(name: str, **variables: Any) -> str:
    return _env.get_template(f"{name}.md").render(**variables)
