"""Frontends: turn an InteractionRequest into a UserResponse (terminal, scripted, web later)."""

import json
from pathlib import Path
from typing import Any, Protocol

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from app.core.interaction import make_response
from app.proposal.understanding import score_dots
from app.schemas.generated.interaction import InteractionRequest
from app.schemas.generated.user_response import UserResponse

# What --auto answers with when answers.json has nothing left for a kind
DEFAULT_ACTION = {
    "confirm_understanding": ("answer", {}),
    "choose_concept": ("answer", {"answers": {"concept_id": "recommended"}}),
    "outline_review": ("approve", {}),
    "clarify": ("cancel", {}),
}


class Frontend(Protocol):
    def info(self, text: str) -> None: ...

    def ask(self, request: InteractionRequest) -> UserResponse: ...


class ScriptedFrontend:
    """Non-interactive: answers come from answers.json = {kind: [partial UserResponse, ...]}."""

    def __init__(
        self, answers: dict[str, list[dict[str, Any]]], console: Console | None = None
    ) -> None:
        self.queues = {k: list(v) for k, v in answers.items()}
        self.console = console or Console()
        self.log: list[str] = []

    @classmethod
    def from_file(cls, path: Path) -> "ScriptedFrontend":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def info(self, text: str) -> None:
        self.console.print(text)

    def ask(self, request: InteractionRequest) -> UserResponse:
        queue = self.queues.get(request.kind, [])
        if queue:
            fields = queue.pop(0)
        else:
            action, extra = DEFAULT_ACTION.get(request.kind, ("cancel", {}))
            fields = {"action": action, **extra}
            self.console.print(
                f"[yellow]--auto: no scripted answer left for {request.kind}, using {action}[/]"
            )
        self.console.print(
            f"[dim]auto-answer {request.kind}: {json.dumps(fields, ensure_ascii=False)[:300]}[/]"
        )
        return make_response(request, **fields)


class TerminalFrontend:
    """Interactive rich/questionary rendering of the proposal interactions."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def info(self, text: str) -> None:
        self.console.print(text)

    # --- rendering ---------------------------------------------------------------------------

    def _show_profile(self, request: InteractionRequest) -> None:
        profile = request.profile
        assert profile is not None
        self.console.print(
            Panel(request.message, title="Hiểu biết về sản phẩm", border_style="cyan")
        )
        self.console.print(f"Đối tượng: {', '.join(profile.target_users) or '—'}")
        table = Table(show_lines=False)
        for col in ("#", "id", "Tính năng", "Mô tả", "Demo", "Ảnh"):
            table.add_column(col)
        for i, f in enumerate(profile.features, start=1):
            table.add_row(
                str(i),
                f.id,
                f.name,
                f.description[:70],
                score_dots(f),
                "có" if f.thumbnail else "không",
            )
        self.console.print(table)
        for f in profile.features:
            if f.thumbnail:
                self.console.print(f"[dim]Thumbnail {f.id}: {Path(f.thumbnail).resolve()}[/]")
        for q in request.questions:
            self.console.print(f"[yellow]Câu hỏi mở:[/] {q.text}")

    def _show_concepts(self, request: InteractionRequest) -> None:
        self.console.print(Panel(request.message, title="Chọn hướng video", border_style="cyan"))
        for i, c in enumerate(request.concepts or [], start=1):
            star = " ★ đề xuất" if c.recommended else ""
            body = (
                f"[bold]{c.title}[/]{star}\n"
                f"Góc kể: {c.angle} · Mục tiêu: {c.goal} · {c.duration_s}s\n"
                f"Hook: «{c.hook_example}»\n"
                + "\n".join(f"  {n}. {b}" for n, b in enumerate(c.beats, start=1))
                + f"\n[dim]{c.why}[/]"
            )
            self.console.print(
                Panel(
                    body, title=f"[{i}] {c.id}", border_style="green" if c.recommended else "white"
                )
            )

    def _show_outline(self, request: InteractionRequest) -> None:
        outline = request.outline
        assert outline is not None
        self.console.print(
            Panel(request.message, title=f"Dàn ý v{outline.version}", border_style="cyan")
        )
        self.console.print(f"[bold]{outline.title}[/] · {outline.goal} · {outline.duration_s}s")
        for n, b in enumerate(outline.beats, start=1):
            link = f" [dim]({b.feature_id})[/]" if b.feature_id else ""
            self.console.print(f"  {n}. [{b.id}] {b.text}{link}")
        for change in request.changes or []:
            self.console.print(f"[green]✓ {change}[/]")

    # --- asking ------------------------------------------------------------------------------

    def ask(self, request: InteractionRequest) -> UserResponse:
        import questionary

        kind = request.kind
        if kind == "confirm_understanding":
            self._show_profile(request)
            return self._ask_understanding(request, questionary)
        if kind == "choose_concept":
            self._show_concepts(request)
            concepts = request.concepts or []
            choices = [
                questionary.Choice(f"{c.id}: {c.title}" + (" ★" if c.recommended else ""), c.id)
                for c in concepts
            ]
            choices += [
                questionary.Choice("Đề xuất lại", "__regen"),
                questionary.Choice("Hủy", "__cancel"),
            ]
            default = next((c.id for c in concepts if c.recommended), None)
            pick = questionary.select("Bạn chọn hướng nào?", choices=choices, default=default).ask()
            if pick in (None, "__cancel"):
                return make_response(request, "cancel")
            notes = questionary.text("Ghi chú (Enter để bỏ qua):").ask() or ""
            if pick == "__regen":
                return make_response(request, "regenerate", answers={"notes": notes})
            return make_response(request, "answer", answers={"concept_id": pick, "notes": notes})
        if kind == "outline_review":
            self._show_outline(request)
            action = questionary.select(
                "Bạn muốn làm gì?",
                choices=[
                    questionary.Choice("Duyệt dàn ý", "approve"),
                    questionary.Choice("Sửa bằng câu tự do", "edit"),
                    questionary.Choice("Tạo lại dàn ý từ hướng đã chọn", "regenerate"),
                    questionary.Choice("Hủy", "cancel"),
                ],
            ).ask()
            if action == "edit":
                text = questionary.text("Yêu cầu sửa:").ask() or ""
                return make_response(request, "edit", edit={"instruction": text})
            return make_response(request, action or "cancel")
        if kind == "clarify":
            q = request.questions[0]
            self.console.print(Panel(q.text, title="Cần làm rõ", border_style="yellow"))
            choices = [questionary.Choice(o.label, o.id) for o in q.options] + [
                questionary.Choice("Hủy", "__cancel")
            ]
            pick = questionary.select("Chọn:", choices=choices).ask()
            if pick in (None, "__cancel"):
                return make_response(request, "cancel")
            return make_response(request, "answer", answers={q.id: pick})
        raise ValueError(f"TerminalFrontend cannot render {kind}")

    def _ask_understanding(self, request: InteractionRequest, questionary: Any) -> UserResponse:
        profile = request.profile
        assert profile is not None
        action = questionary.select(
            "Bạn muốn làm gì?",
            choices=[
                questionary.Choice("Xác nhận, tiếp tục", "confirm"),
                questionary.Choice("Bỏ bớt tính năng", "exclude"),
                questionary.Choice("Sửa mô tả sản phẩm / đối tượng", "texts"),
                questionary.Choice("Thêm tính năng", "add"),
                questionary.Choice("Trả lời câu hỏi mở", "answer_q"),
                questionary.Choice("Xem thêm trang", "explore"),
                questionary.Choice("Hủy", "cancel"),
            ],
        ).ask()
        if action in (None, "cancel"):
            return make_response(request, "cancel")
        if action == "confirm":
            return make_response(request, "answer")
        if action == "exclude":
            keep = questionary.checkbox(
                "Giữ lại các tính năng:",
                choices=[
                    questionary.Choice(f"{f.id}: {f.name}", f.id, checked=True)
                    for f in profile.features
                ],
            ).ask()
            dropped = [f.id for f in profile.features if f.id not in (keep or [])]
            return make_response(request, "edit", profile_edit={"exclude_feature_ids": dropped})
        if action == "texts":
            one = questionary.text("One-liner mới (Enter để giữ):", default=profile.one_liner).ask()
            users = questionary.text(
                "Đối tượng (cách nhau bằng dấu phẩy):", default=", ".join(profile.target_users)
            ).ask()
            return make_response(
                request,
                "edit",
                profile_edit={
                    "one_liner": one,
                    "target_users": [u.strip() for u in (users or "").split(",") if u.strip()],
                },
            )
        if action == "add":
            name = questionary.text("Tên tính năng:").ask() or ""
            desc = questionary.text("Mô tả ngắn:").ask() or ""
            return make_response(
                request,
                "edit",
                profile_edit={"added_features": [{"name": name, "description": desc}]},
            )
        if action == "answer_q":
            answers = {q.id: questionary.text(q.text).ask() or "" for q in request.questions}
            return make_response(request, "edit", answers=answers)
        text = questionary.text("URL hoặc mô tả trang cần xem thêm:").ask() or ""
        urls = [t for t in text.replace(",", " ").split() if t.startswith("http")]
        return make_response(
            request, "explore_more", explore={"urls": urls, "description": None if urls else text}
        )
