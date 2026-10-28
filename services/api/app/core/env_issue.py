"""Environment issues: the page could not load its data because of how WE browse (not the site).

Today the only kind is `guard_broke_page`: the main area stayed empty and the request guard had
refused requests just before. Issues are kept per job in env_issues.json and shown to the user.
"""

import json
from pathlib import Path
from typing import Any

ENV_FILE = "env_issues.json"
KIND_GUARD = "guard_broke_page"
MAX_URLS = 3


def load_env_issues(job_dir: Path) -> list[dict[str, Any]]:
    path = job_dir / ENV_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def add_env_issue(job_dir: Path, issue: dict[str, Any]) -> None:
    """Append (one entry per page + blocked set)."""
    issues = load_env_issues(job_dir)
    key = (issue.get("page_url"), tuple(issue.get("blocked_urls", ())))
    if any((i.get("page_url"), tuple(i.get("blocked_urls", ()))) == key for i in issues):
        return
    issues.append(issue)
    (job_dir / ENV_FILE).write_text(json.dumps(issues, ensure_ascii=False, indent=2), "utf-8")


def env_warning(issues: list[dict[str, Any]]) -> str | None:
    """One sentence for the user about the first page that could not load (vi)."""
    if not issues:
        return None
    first = issues[0]
    blocked = list(dict.fromkeys(u for i in issues for u in i.get("blocked_urls", ())))
    shown = "; ".join(blocked[:MAX_URLS])
    more = f" (+{len(blocked) - MAX_URLS})" if len(blocked) > MAX_URLS else ""
    return (
        f"Trang {first.get('page_url', '?')} không tải được dữ liệu vì hệ thống an toàn đã chặn "
        f"{len(blocked)} yêu cầu ghi dữ liệu: {shown}{more}. Video có thể thiếu nội dung trang này."
    )
