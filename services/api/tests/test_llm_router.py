from pathlib import Path

import pytest
from pydantic import BaseModel

from app.llm.client import LLMSettings
from app.llm.json_call import ChatLLM
from app.llm.router import PROVIDERS, ROLES, get_client, role_config
from tests.conftest import FakeLLM


class Answer(BaseModel):
    ok: bool


def settings(vision: str | None = "deepseek-flash") -> LLMSettings:
    return LLMSettings(
        base_url="http://x", api_key="k", model="deepseek-chat", vision_model=vision,
        cache_enabled=False, cache_dir=Path(".cache-test"),
    )  # fmt: skip


def test_every_role_defaults_to_the_global_models() -> None:
    for role in ROLES:
        cfg = role_config(role, settings(), env={})
        assert (cfg.model, cfg.vision_model, cfg.provider) == (
            "deepseek-chat", "deepseek-flash", "deepseek",
        )  # fmt: skip


def test_the_env_overrides_one_role_only() -> None:
    env = {"LLM_FLOW_AGENT_MODEL": "deepseek-reasoner", "LLM_SCRIPT_VISION": "false"}
    assert role_config("flow_agent", settings(), env).model == "deepseek-reasoner"
    assert role_config("script", settings(), env).vision_model is None
    assert not role_config("script", settings(), env).vision
    assert role_config("outline", settings(), env).model == "deepseek-chat"


def test_flow_agent_sees_images_unless_switched_off_or_there_is_no_vision_model() -> None:
    assert role_config("flow_agent", settings(), {"LLM_FLOW_AGENT_VISION": "true"}).vision
    assert not role_config("flow_agent", settings(), {"LLM_FLOW_AGENT_VISION": "false"}).vision
    assert not role_config("flow_agent", settings(vision=None), {}).vision


def test_an_unknown_role_or_provider_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown LLM role"):
        role_config("nope", settings(), {})
    with pytest.raises(ValueError, match="provider"):
        get_client("script", settings=settings(), env={"LLM_SCRIPT_PROVIDER": "other"})


def test_a_new_provider_is_one_class_in_the_registry() -> None:
    made: list[FakeLLM] = []

    def factory(s: LLMSettings) -> ChatLLM:
        fake = FakeLLM(lambda _p: {"ok": True}, vision_model=s.vision_model)
        fake.model = s.model
        made.append(fake)
        return fake

    env = {"LLM_FLOW_AGENT_PROVIDER": "fake", "LLM_FLOW_AGENT_MODEL": "m-agent"}
    caller = get_client(
        "flow_agent", settings=settings(), env=env, providers={**PROVIDERS, "fake": factory}
    )
    assert caller.can_see_images and made[0].model == "m-agent"
    assert caller.call("flow_agent", "Return json", Answer).ok
    assert made[0].calls[0]["model"] == "m-agent"


def test_a_role_without_vision_cannot_send_images() -> None:
    caller = get_client(
        "script", settings=settings(), env={"LLM_SCRIPT_VISION": "false"},
        providers={"deepseek": lambda s: FakeLLM(lambda _p: {"ok": True}, s.vision_model)},
    )  # fmt: skip
    assert not caller.can_see_images


def test_callers_of_different_roles_share_the_job_tracker() -> None:
    from app.core.usage import UsageTracker

    tracker = UsageTracker()
    providers = {"deepseek": lambda s: FakeLLM(lambda _p: {"ok": True}, s.vision_model)}
    for role in ("outline", "flow_agent"):
        get_client(role, settings=settings(), env={}, tracker=tracker, providers=providers).call(
            role, "json please", Answer
        )
    assert tracker.total == 300 and set(tracker.steps) == {"outline", "flow_agent"}
