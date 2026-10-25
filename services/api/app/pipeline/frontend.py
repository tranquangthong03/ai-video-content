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
    "script_review": ("approve", {}),
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
        elif request.kind == "select_features" and request.selection:
            picks = request.selection.default
            fields = {"action": "answer", "answers": {"selected_features": picks}}
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
        names = {f.id: f.name for f in request.profile.features} if request.profile else {}
        for n, b in enumerate(outline.beats, start=1):
            # b2 · [Tạo việc cần làm] Gõ 'Buy milk'…: the feature a beat shows, editable by the user
            tag = f"\\[{names.get(b.feature_id, b.feature_id)}] " if b.feature_id else ""
            self.console.print(f"  {n}. {b.id} · {tag}{b.text}")
        for change in request.changes or []:
            self.console.print(f"[green]✓ {change}[/]")

    # --- asking ------------------------------------------------------------------------------

    def ask(self, request: InteractionRequest) -> UserResponse:
        import questionary

        kind = request.kind
        if kind == "confirm_understanding":
            self._show_profile(request)
            return self._ask_understanding(request, questionary)
        if kind == "select_features":
            return self._ask_selection(request, questionary)
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
        if kind == "script_review":
            return self._ask_script_review(request, questionary)
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

    def _ask_selection(self, request: InteractionRequest, questionary: Any) -> UserResponse:
        profile, sel = request.profile, request.selection
        assert profile is not None and sel is not None
        self.console.print(Panel(request.message, title="Chọn tính năng", border_style="cyan"))
        picks = questionary.checkbox(
            "Chọn tính năng (khoảng trắng để chọn, tối đa 4):",
            choices=[
                questionary.Choice(
                    f"{f.name} — {score_dots(f)}" + (" [mới]" if f.id in sel.new_ids else ""),
                    f.id,
                    checked=f.id in sel.default,
                )
                for f in profile.features
            ],
        ).ask()
        if picks is None:
            return make_response(request, "cancel")
        ordered: list[str] = []
        names = {f.id: f.name for f in profile.features}
        rest = list(picks)
        while len(rest) > 1:  # who comes first? one question per priority place
            first = questionary.select(
                f"Ưu tiên số {len(ordered) + 1}:",
                choices=[questionary.Choice(names[i], i) for i in rest],
            ).ask()
            if first is None:
                return make_response(request, "cancel")
            ordered.append(first)
            rest.remove(first)
        return make_response(request, "answer", answers={"selected_features": ordered + rest})

    def _ask_script_review(self, request: InteractionRequest, questionary: Any) -> UserResponse:
        version = request.script_version
        while True:
            action = questionary.select(
                "Bạn muốn làm gì?",
                choices=[
                    questionary.Choice("a — Duyệt kịch bản", "a"),
                    questionary.Choice("e — Sửa bằng câu tự do", "e"),
                    questionary.Choice("s — Sửa nhanh một trường", "s"),
                    questionary.Choice("r — Sinh lại toàn bộ", "r"),
                    questionary.Choice("v — Quay về bản cũ", "v"),
                    questionary.Choice("j — Xem JSON", "j"),
                    questionary.Choice("q — Thoát", "q"),
                ],
            ).ask()
            if action == "j":
                self.console.print_json(getattr(self, "script_json", "{}"))
                continue
            break
        if action in (None, "q"):
            return make_response(request, "cancel")
        if action == "a":
            return make_response(request, "approve", base_version=version)
        if action == "r":
            return make_response(request, "regenerate", base_version=version)
        if action == "e":
            text = questionary.text("Yêu cầu sửa (ví dụ: scene 2: nói ngắn hơn):").ask() or ""
            return make_response(request, "edit", base_version=version, edit={"instruction": text})
        if action == "v":
            older = [str(n) for n in range(1, (version or 1))]
            if not older:
                self.console.print("[yellow]Chưa có bản cũ.[/]")
                return self._ask_script_review(request, questionary)
            pick = questionary.select("Về bản nào?", choices=older).ask()
            return make_response(
                request, "revert", base_version=version, revert_to=int(pick or older[-1])
            )
        return self._quick_set(request, questionary)

    def _quick_set(self, request: InteractionRequest, questionary: Any) -> UserResponse:
        """[s]: pick a scene, a field and a value; becomes one explicit set / set_theme op."""
        version = request.script_version
        fields = [
            questionary.Choice("Lời đọc (voiceover)", "voiceover"),
            questionary.Choice("Chữ trên màn hình (on_screen_text)", "on_screen_text"),
            questionary.Choice("Bố cục (layout)", "layout"),
            questionary.Choice("Tính năng (feature)", "feature"),
            questionary.Choice("Màu chủ đạo (primary)", "primary"),
        ]
        field = questionary.select("Sửa trường nào?", choices=fields).ask()
        if field is None:
            return make_response(request, "cancel")
        if field == "primary":
            value = questionary.text("Màu (#RRGGBB):").ask() or ""
            op = {"op": "set_theme", "field": "primary", "value": value}
        else:
            scenes = [
                questionary.Choice(f"{s.scene_id}: {s.one_liner}", s.scene_id)
                for s in request.summary or []
            ]
            scene = questionary.select("Scene nào?", choices=scenes).ask()
            value = questionary.text("Nội dung mới:").ask() or ""
            op = {"op": "set", "scene_id": scene, "field": field, "value": value}
        return make_response(request, "edit", base_version=version, edit={"ops": [op]})

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
