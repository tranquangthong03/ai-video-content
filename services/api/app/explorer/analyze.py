"""Page Analyzer: one text-only LLM call per page (max 4 in parallel) -> PageInsight."""

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.explorer.models import PageData
from app.explorer.report import Report
from app.llm.json_call import JsonCaller, LLMCallError
from app.llm.prompts import render
from app.schemas.generated.page_insight import PageInsight

PARALLEL = 4


def format_elements(page: PageData) -> str:
    return "\n".join(
        f"{e.ref} | {e.role} | {e.name} | {e.region}" + (f" | {','.join(e.caps)}" if e.caps else "")
        for e in page.elements
    )


def analyze_page(caller: JsonCaller, page: PageData, step: str = "analyze") -> PageInsight:
    prompt = render(
        "page_analyzer",
        url=page.url,
        title=page.title,
        headings="; ".join(f"H{h.level}: {h.text}" for h in page.headings),
        key_texts="\n".join(f"- {t}" for t in page.key_texts),
        elements=format_elements(page),
        signals=json.dumps(page.signals, ensure_ascii=False),
    )
    insight = caller.call(step, prompt, PageInsight)
    insight.url, insight.title = page.url, page.title
    known = {e.ref for e in page.elements}
    insight.actions = [
        a for a in insight.actions if a.ref in known
    ]  # the prompt forbids invented refs
    return insight


def analyze_pages(
    caller: JsonCaller,
    pages: list[PageData],
    out_dir: Path,
    report: Report,
    *,
    on_done: Callable[[int, int], None] | None = None,
) -> list[PageInsight]:
    """Analyze every page; resumable (reads insights/<n>.json when present)."""
    insights_dir = out_dir / "insights"
    insights_dir.mkdir(parents=True, exist_ok=True)
    results: dict[int, PageInsight] = {}
    done = 0

    def work(page: PageData) -> None:
        nonlocal done
        path = insights_dir / f"{page.n}.json"
        if path.is_file():
            results[page.n] = PageInsight.model_validate_json(path.read_text(encoding="utf-8"))
        else:
            try:
                insight = analyze_page(caller, page)
            except LLMCallError as e:
                report.warn(f"analyze failed for {page.url}: {e}")
                return
            path.write_text(insight.model_dump_json(indent=2), encoding="utf-8")
            results[page.n] = insight
        done += 1
        if on_done:
            on_done(done, len(pages))

    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        futures = [pool.submit(work, p) for p in pages]
        for f in futures:
            f.result()  # re-raises BudgetExceeded etc. so the pipeline can stop and save state
    return [results[p.n] for p in pages if p.n in results]
