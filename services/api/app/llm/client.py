"""OpenAI-compatible client configured for DeepSeek from environment variables."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class LLMSettings:
    base_url: str
    api_key: str
    model: str
    vision_model: str | None
    cache_enabled: bool
    cache_dir: Path


def load_dotenv(path: Path = REPO_ROOT / ".env") -> dict[str, str]:
    """Parse KEY=VALUE lines; never logs values. Existing process env wins over the file."""
    values: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip("\"'")
    return values


def load_settings(env: Mapping[str, str] | None = None) -> LLMSettings:
    merged = {**load_dotenv(), **(os.environ if env is None else env)}
    api_key = merged.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set (put it in .env)")
    return LLMSettings(
        base_url=merged.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        api_key=api_key,
        model=merged.get("DEEPSEEK_MODEL", "deepseek-chat"),
        vision_model=merged.get("DEEPSEEK_VISION_MODEL") or None,
        cache_enabled=merged.get("LLM_CACHE", "0") == "1",
        cache_dir=Path(merged.get("LLM_CACHE_DIR", ".cache")),
    )


def make_client(settings: LLMSettings) -> OpenAI:
    return OpenAI(base_url=settings.base_url, api_key=settings.api_key, timeout=120, max_retries=2)
