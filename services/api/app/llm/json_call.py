"""JSON-mode LLM calls: Pydantic validation, self-repair, token accounting, disk cache."""

import hashlib
import json
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.core.usage import UsageTracker
from app.llm.client import LLMSettings, make_client
from app.llm.images import prepare_image

T = TypeVar("T", bound=BaseModel)

MAX_REPAIRS = 2
MAX_OUTPUT_TOKENS = 8192  # reasoning models spend part of this on thinking
_log_lock = threading.Lock()


class VisionUnavailable(RuntimeError):
    """Images were passed but no DEEPSEEK_VISION_MODEL is configured."""


class LLMCallError(RuntimeError):
    """The model never produced valid output within the repair budget."""


@dataclass
class Completion:
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    truncated: bool = False


class ChatLLM(Protocol):
    model: str
    vision_model: str | None

    def complete(self, model: str, messages: list[dict[str, Any]]) -> Completion: ...


class OpenAIChat:
    """ChatLLM backed by the OpenAI SDK pointed at DeepSeek."""

    def __init__(self, settings: LLMSettings, client: OpenAI | None = None) -> None:
        self.client = client or make_client(settings)
        self.model = settings.model
        self.vision_model = settings.vision_model

    def complete(self, model: str, messages: list[dict[str, Any]]) -> Completion:
        res = self.client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            response_format={"type": "json_object"},
            max_tokens=MAX_OUTPUT_TOKENS,
        )
        choice = res.choices[0]
        usage = res.usage
        return Completion(
            content=choice.message.content or "",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            truncated=choice.finish_reason == "length",
        )


def _summarize_errors(error: ValidationError) -> str:
    lines = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()[:12]]
    return "\n".join(lines)[:1500]


class JsonCaller:
    def __init__(
        self,
        llm: ChatLLM,
        *,
        tracker: UsageTracker | None = None,
        cache_enabled: bool = False,
        cache_dir: Path = Path(".cache"),
    ) -> None:
        self.llm = llm
        self.tracker = tracker or UsageTracker()
        self.cache_enabled = cache_enabled
        self.cache_dir = cache_dir

    @property
    def can_see_images(self) -> bool:
        return self.llm.vision_model is not None

    def call(
        self,
        step: str,
        prompt: str,
        schema: type[T],
        images: Sequence[Path | bytes] = (),
    ) -> T:
        if "json" not in prompt.lower():
            raise ValueError("prompt must contain the word 'json' (json_object mode requirement)")
        model = self.llm.model
        data_urls: list[str] = []
        image_hashes: list[str] = []
        if images:
            if not self.llm.vision_model:
                raise VisionUnavailable("no vision model configured")
            model = self.llm.vision_model
            for image in images:
                url, digest = prepare_image(image)
                data_urls.append(url)
                image_hashes.append(digest)

        key = hashlib.sha256(
            "\0".join([model, schema.__name__, prompt, *image_hashes]).encode()
        ).hexdigest()
        cached = self._cache_read(key, schema)
        if cached is not None:
            self._log(step, model, 0, 0, 0.0, 0, cached=True, ok=True)
            return cached

        content: Any = prompt
        if data_urls:
            content = [
                {"type": "text", "text": prompt},
                *({"type": "image_url", "image_url": {"url": u}} for u in data_urls),
            ]
        messages: list[dict[str, Any]] = [{"role": "user", "content": content}]

        started = time.time()
        in_tokens = out_tokens = 0
        last_error = ""
        for attempt in range(MAX_REPAIRS + 1):
            self.tracker.check()
            completion = self.llm.complete(model, messages)
            in_tokens += completion.prompt_tokens
            out_tokens += completion.completion_tokens
            self.tracker.add(step, completion.prompt_tokens, completion.completion_tokens)
            try:
                if not completion.content.strip():
                    raise ValueError(
                        "empty response" + (" (output truncated)" if completion.truncated else "")
                    )
                result = schema.model_validate(json.loads(completion.content))
            except (ValueError, ValidationError) as e:  # JSONDecodeError is a ValueError
                last_error = _summarize_errors(e) if isinstance(e, ValidationError) else str(e)
                messages += [
                    {"role": "assistant", "content": completion.content or "{}"},
                    {
                        "role": "user",
                        "content": "Kết quả json không hợp lệ:\n"
                        f"{last_error}\nHãy trả lại json hợp lệ đã sửa, đúng cấu trúc, chỉ json.",
                    },
                ]
                continue
            self._cache_write(key, completion.content)
            self._log(
                step, model, in_tokens, out_tokens, time.time() - started, attempt + 1, ok=True
            )
            return result

        self._log(
            step, model, in_tokens, out_tokens, time.time() - started, MAX_REPAIRS + 1, ok=False
        )
        raise LLMCallError(f"{step}: invalid output after {MAX_REPAIRS} repairs: {last_error}")

    # --- cache / log -------------------------------------------------------------------------

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / "llm-cache" / f"{key}.json"

    def _cache_read(self, key: str, schema: type[T]) -> T | None:
        if not self.cache_enabled:
            return None
        path = self._cache_path(key)
        try:
            return schema.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None

    def _cache_write(self, key: str, content: str) -> None:
        if not self.cache_enabled:
            return
        path = self._cache_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _log(
        self,
        step: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        seconds: float,
        attempts: int,
        *,
        cached: bool = False,
        ok: bool,
    ) -> None:
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "step": step,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "seconds": round(seconds, 2),
            "attempts": attempts,
            "cached": cached,
            "ok": ok,
        }
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with _log_lock, (self.cache_dir / "llm-log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
