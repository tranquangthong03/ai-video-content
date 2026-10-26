"""Per-role model configuration: get_client(role) returns the caller a pipeline step should use.

Each role reads LLM_<ROLE>_MODEL (text model) and LLM_<ROLE>_VISION (true/false: may the role send
images). Unset values keep today's behaviour (DEEPSEEK_MODEL, DEEPSEEK_VISION_MODEL); .env.example
sets LLM_FLOW_AGENT_VISION=true. LLM_<ROLE>_PROVIDER picks the client class from PROVIDERS; adding a
provider later means adding one ChatLLM class and one entry there.
"""

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Literal, get_args

from app.llm.client import LLMSettings, load_dotenv, load_settings
from app.llm.json_call import ChatLLM, JsonCaller, OpenAIChat, UsageTracker

Role = Literal[
    "analyze",
    "synthesize",
    "flow_discovery",
    "flow_agent",
    "outline",
    "script",
    "copy_critic",
    "focus_planner",
    "edit_planner",
]
ROLES: tuple[str, ...] = get_args(Role)

ChatFactory = Callable[[LLMSettings], ChatLLM]
PROVIDERS: dict[str, ChatFactory] = {"deepseek": OpenAIChat}
DEFAULT_PROVIDER = "deepseek"


@dataclass(frozen=True)
class RoleConfig:
    role: str
    provider: str
    model: str
    vision: bool  # may this role send images (needs a vision model in the settings)
    vision_model: str | None
    vision_mode: str = "on"  # on | off | auto (auto: images only once the work gets hard)


# roles that look at the screen only when needed, unless the .env says otherwise
AUTO_ROLES = {"flow_agent": "auto"}


def _mode(raw: str | None, default: str) -> str:
    """on | off | auto from LLM_<ROLE>_VISION (true / false as before)."""
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    return "auto" if value == "auto" else ("on" if _flag(value, True) else "off")


def _flag(raw: str | None, default: bool) -> bool:
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def merged_env(env: Mapping[str, str] | None = None) -> Mapping[str, str]:
    return {**load_dotenv(), **os.environ} if env is None else env


def role_config(
    role: str, settings: LLMSettings, env: Mapping[str, str] | None = None
) -> RoleConfig:
    """The model and vision switch for a role: .env override first, then the global defaults."""
    if role not in ROLES:
        raise ValueError(f"unknown LLM role {role!r} (expected one of {', '.join(ROLES)})")
    values = merged_env(env)
    prefix = f"LLM_{role.upper()}_"
    # on by default: with DEEPSEEK_VISION_MODEL set every role may send images, as before
    mode = _mode(values.get(prefix + "VISION"), AUTO_ROLES.get(role, "on"))
    vision = mode != "off"
    return RoleConfig(
        role=role,
        provider=(values.get(prefix + "PROVIDER") or DEFAULT_PROVIDER).strip().lower(),
        model=(values.get(prefix + "MODEL") or settings.model).strip(),
        vision=vision and settings.vision_model is not None,
        vision_model=settings.vision_model if vision else None,
        vision_mode=mode if settings.vision_model is not None else "off",
    )


def get_client(
    role: str,
    *,
    settings: LLMSettings | None = None,
    env: Mapping[str, str] | None = None,
    tracker: UsageTracker | None = None,
    providers: Mapping[str, ChatFactory] | None = None,
) -> JsonCaller:
    """A JsonCaller configured for the role (shares `tracker` so token totals stay per job)."""
    settings = settings or load_settings(env)
    config = role_config(role, settings, env)
    registry = providers if providers is not None else PROVIDERS
    if config.provider not in registry:
        raise ValueError(f"LLM provider {config.provider!r} is not available for role {role}")
    role_settings = replace(settings, model=config.model, vision_model=config.vision_model)
    caller = JsonCaller(
        registry[config.provider](role_settings),
        tracker=tracker,
        cache_enabled=settings.cache_enabled,
        cache_dir=settings.cache_dir,
    )
    caller.vision_mode = config.vision_mode
    return caller
