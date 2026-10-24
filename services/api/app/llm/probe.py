"""Probe which DeepSeek models accept images: `uv run python -m app.llm.probe`.

Writes out/llm-probe.json. Never prints or stores the API key.
"""

import base64
import io
import json
import re
import time
from pathlib import Path
from typing import Any

from PIL import Image

from app.llm.client import load_settings, make_client

EXTRA_CANDIDATES = [
    "deepseek-v4.1-flash",
    "deepseek-v4-flash",
    "deepseek-v4-flash-vision-exp",
    "deepseek-flash",
]
KEYWORDS = ("flash", "vision", "v4")
OUT = Path("out/llm-probe.json")


def red_png_data_url() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (230, 20, 20)).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def ask(client: Any, model: str, content: Any) -> dict[str, Any]:
    started = time.time()
    try:
        res = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            response_format={"type": "json_object"},
            max_tokens=1500,  # reasoning models spend tokens thinking before the answer
        )
        text = res.choices[0].message.content or ""
        return {"ok": True, "answer": text, "seconds": round(time.time() - started, 2)}
    except Exception as e:  # probe: record any failure mode
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}


def is_red(answer: str) -> bool:
    try:
        color = str(json.loads(answer).get("color", ""))
    except (json.JSONDecodeError, AttributeError):
        color = answer
    return bool(re.search(r"red|đỏ|do\b|crimson|#e6|#f00|#ff0000", color, re.I))


def main() -> None:
    settings = load_settings()
    client = make_client(settings)
    listed: list[str] = []
    list_error: str | None = None
    try:
        listed = sorted(m.id for m in client.models.list().data)
    except Exception as e:
        list_error = f"{type(e).__name__}: {str(e)[:300]}"

    candidates = [m for m in listed if any(k in m.lower() for k in KEYWORDS)]
    candidates += [m for m in EXTRA_CANDIDATES if m not in candidates]
    image_prompt = [
        {"type": "text", "text": 'Màu chủ đạo của ảnh là gì? Trả lời json {"color": ...}'},
        {"type": "image_url", "image_url": {"url": red_png_data_url()}},
    ]
    results: dict[str, Any] = {}
    winner: str | None = None
    for model in candidates:
        r = ask(client, model, image_prompt)
        r["correct"] = bool(r.get("ok") and is_red(r["answer"]))
        results[model] = r
        if r["correct"] and winner is None:
            winner = model

    text_check = None
    if winner:
        text_check = ask(client, winner, 'Trả lời json {"sum": 2+3}')

    report = {
        "base_url": settings.base_url,
        "current_text_model": settings.model,
        "listed_models": listed,
        "list_error": list_error,
        "image_results": results,
        "vision_model": winner,
        "text_check_with_vision_model": text_check,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "image_results"}, ensure_ascii=False))
    for model, r in results.items():
        print(model, "->", "OK" if r["correct"] else r.get("error") or r.get("answer"))


if __name__ == "__main__":
    main()
