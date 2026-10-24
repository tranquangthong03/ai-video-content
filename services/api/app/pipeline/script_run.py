"""Script step: theme -> beat links -> Script Writer -> duration fit -> script_review loop.

Artifacts under <job_dir>: theme.json, beat_mapping_script.json, scripts/v{n}.json,
script_approved.json, script_report.json, interactions.jsonl (shared with the proposal steps).
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.markup import escape

from app.core.budget import budget_for, oversize_warning
from app.core.interaction import check_response, make_request
from app.llm.json_call import JsonCaller, LLMCallError
from app.pipeline.frontend import Frontend
from app.pipeline.proposal_run import Cancelled
from app.proposal import beat_mapper
from app.schemas.generated.interaction import InteractionRequest
from app.schemas.generated.outline import Outline
from app.schemas.generated.product_profile import ProductProfile
from app.schemas.generated.script import Script
from app.schemas.generated.theme import Theme
from app.schemas.generated.user_response import UserResponse
from app.script.diff import diff_scripts
from app.script.edit import EditOutcome, apply_edit, apply_global
from app.script.fit_duration import FitReport, fit_duration
from app.script.footage import SceneFacts, footage_ratio, min_ratio
from app.script.lite import LiteContext, load_page_index
from app.script.theme import ThemeResult
from app.script.versions import ScriptStore
from app.script.view import one_liners, render_script
from app.script.visuals import load_setup_counts
from app.script.writer import WriterContext, WriterResult, write_script

MAX_ROUNDS = 30
MAX_CLARIFY_ROUNDS = 2
SCRIPT_REVIEW_ACTIONS = ["approve", "edit", "regenerate", "revert", "cancel"]


def build_request(
    job_id: str,
    script: Script,
    version: int,
    *,
    changes: list[str] | None = None,
    notice: str = "",
) -> InteractionRequest:
    message = (
        "Đây là kịch bản video. Bạn duyệt, hoặc nhập yêu cầu sửa bằng câu tự do "
        "(ví dụ: «scene 2: nói ngắn hơn», «đổi màu chủ đạo thành #0F766E»)."
    )
    return make_request(
        job_id,
        "script_review",
        f"{notice}\n{message}" if notice else message,
        summary=one_liners(script),
        changes=changes,
        script_version=version,
        allowed_actions=SCRIPT_REVIEW_ACTIONS,
    )


class ScriptRunner:
    def __init__(
        self,
        job_id: str,
        job_dir: Path,
        caller: JsonCaller,
        frontend: Frontend,
        profile: ProductProfile,
        outline: Outline,
        url: str,
        *,
        theme_fn: Callable[[], ThemeResult],
        capture: tuple[int, int] | None = None,
    ) -> None:
        self.job_id, self.dir, self.caller, self.frontend = job_id, job_dir, caller, frontend
        self.profile, self.outline, self.url = profile, outline, url
        self.theme_fn = theme_fn
        self.capture = capture
        self.store = ScriptStore(job_dir)
        self.report: dict[str, Any] = {"warnings": []}
        saved = job_dir / "script_report.json"
        if saved.is_file():  # a resumed run keeps what only the first generation knows
            old = json.loads(saved.read_text(encoding="utf-8"))
            for key in ("fit_generation", "generation"):
                if key in old:
                    self.report[key] = old[key]
        self.ctx: WriterContext | None = None
        self.fit: FitReport | None = None
        self.last_write: WriterResult | None = None

    # --- preparation ---------------------------------------------------------------------------

    def _theme(self) -> Theme:
        file = self.dir / "theme.json"
        report_file = self.dir / "theme_report.json"
        if file.is_file():
            if report_file.is_file():
                self.report["theme"] = json.loads(report_file.read_text(encoding="utf-8"))
            return Theme.model_validate_json(file.read_text(encoding="utf-8"))
        result = self.theme_fn()
        file.write_text(result.theme.model_dump_json(indent=2), encoding="utf-8")
        report_file.write_text(
            json.dumps(result.report(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.report["theme"] = result.report()
        return result.theme

    def _link_beats(self) -> Outline:
        """An outline from before the beat mapper existed gets its demo beats linked now."""
        if not beat_mapper.needs_mapping(self.outline):
            return self.outline
        file = self.dir / "beat_mapping_script.json"
        if file.is_file():  # resumed run: reuse the decision instead of asking again
            saved = json.loads(file.read_text(encoding="utf-8"))
            self.report["beat_mapping"] = {"changes": saved["changes"], "mapping": saved["mapping"]}
            return Outline.model_validate(saved["outline"])
        try:
            mapped = beat_mapper.map_beats(self.caller, self.profile, self.outline)
        except LLMCallError as e:
            self.report["warnings"].append(f"chưa gắn được tính năng cho các beat: {e}")
            return self.outline
        file.write_text(
            json.dumps(
                {
                    "mapping": mapped.mapping,
                    "changes": mapped.changes,
                    "warnings": mapped.warnings,
                    "outline": mapped.outline.model_dump(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self.report["beat_mapping"] = {"changes": mapped.changes, "mapping": mapped.mapping}
        self.report["warnings"] += mapped.warnings
        return mapped.outline

    def prepare(self) -> WriterContext:
        theme = self._theme()
        outline = self._link_beats()
        self.ctx = WriterContext(
            self.profile,
            outline,
            theme,
            self.url,
            load_setup_counts(self.dir / "explore", self.profile),
        )
        self.ctx.capture = self.capture
        self.ctx.lite = LiteContext(self.profile, load_page_index(self.dir / "explore"), self.url)
        budget = budget_for(self.profile)
        self.report.update(
            content_budget_s=budget.content_budget_s,
            content_budget_formula=budget.formula,
            recommended_duration_s=budget.recommended_duration_s,
        )
        warning = oversize_warning(outline.duration_s, budget)
        if warning:
            self.ctx.forced = True
            self.report["warnings"].append(warning)
        return self.ctx

    # --- generation ----------------------------------------------------------------------------

    def _generate(self) -> Script:
        assert self.ctx is not None
        written = write_script(self.caller, self.ctx)
        self.last_write = written
        script, fit = fit_duration(self.caller, written.script, self.ctx)
        self.fit = fit
        self.report["generation"] = {
            "attempts": written.attempts,
            "errors_history": written.errors_history,
        }
        self.report["fit"] = self.report["fit_generation"] = fit.as_dict()
        self.report["warnings"] += [*written.warnings, *fit.warnings]
        self._footage(script)
        return script

    def _measure(self, script: Script) -> None:
        """After a user edit the fit is only measured: the user's words are not overridden."""
        assert self.ctx is not None
        _, self.fit = fit_duration(self.caller, script, self.ctx, adjust=False)
        self.report["fit"] = self.fit.as_dict()
        self._footage(script)

    def _footage(self, script: Script) -> None:
        """footage_ratio of the script as it stands (estimated from the speech time)."""
        facts = [
            SceneFacts(
                s.root.type,
                getattr(s.root, "feature", None),
                s.root.voiceover,
                s.root.visual.mode == "recording",
            )
            for s in script.scenes
        ]
        self.report["footage_ratio"] = round(footage_ratio(facts), 3)
        self.report["footage_min"] = min_ratio(script.target_duration_s)

    # --- interaction ---------------------------------------------------------------------------

    def _ask(self, request: InteractionRequest) -> UserResponse:
        while True:
            response = self.frontend.ask(request)
            errors = check_response(request, response)
            if not errors:
                break
            self.frontend.info(f"[red]Phản hồi không hợp lệ: {'; '.join(errors)}[/]")
        with (self.dir / "interactions.jsonl").open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "request": request.model_dump(mode="json", exclude_none=True),
                        "response": response.model_dump(mode="json", exclude_none=True),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        if response.action == "cancel":
            raise Cancelled(request.kind)
        return response

    def _edit(
        self,
        script: Script,
        version: int,
        instruction: str | None,
        ops: list[Any],
        targets: list[Any],
    ) -> EditOutcome:
        assert self.ctx is not None
        text = instruction
        for _ in range(MAX_CLARIFY_ROUNDS + 1):
            outcome = apply_edit(
                self.caller,
                script,
                self.ctx,
                instruction=text,
                ops=ops,
                targets=targets,
                version=version,
            )
            q = outcome.clarification
            if q is None:
                return outcome
            request = make_request(
                self.job_id,
                "clarify",
                q.question,
                allowed_actions=["answer", "cancel"],
                questions=[
                    {
                        "id": "clarify",
                        "text": q.question,
                        "type": "single",
                        "options": [o.model_dump() for o in q.options],
                        "allow_custom": True,
                    }
                ],
            )
            answer = (self._ask(request).answers or {}).get("clarify", "")
            label = next((o.label for o in q.options if o.id == answer), str(answer))
            text = f"{instruction}\n(Làm rõ: {label})"
        return outcome

    def _show(self, script: Script, version: int, changes: list[str], notice: str) -> None:
        self.frontend.script_json = json.dumps(script.model_dump(), ensure_ascii=False, indent=2)
        for line in render_script(script, self.fit, self.report.get("theme"), version):
            self.frontend.info(line)
        for change in changes:
            self.frontend.info(f"[green]✓ {escape(change)}[/]")
        for line in notice.splitlines():
            self.frontend.info(f"[yellow]{escape(line)}[/]")

    def run(self) -> Script:
        approved_file = self.dir / "script_approved.json"
        if approved_file.is_file():
            return Script.model_validate_json(approved_file.read_text(encoding="utf-8"))
        ctx = self.prepare()
        latest = self.store.latest()
        if latest is None:
            script = self._generate()
            version = self.store.save(script)
        else:  # resume: continue from the newest version
            script = self.store.load(latest)
            version = latest
            ctx.theme = script.theme
            self._measure(script)
        changes: list[str] = []
        notice = ""
        for _ in range(MAX_ROUNDS):
            self._save_report(version)
            self._show(script, version, changes, notice)
            response = self._ask(
                build_request(self.job_id, script, version, changes=changes, notice=notice)
            )
            changes, notice = [], ""
            if response.base_version not in (None, version):
                notice = f"Bản bạn xem là v{response.base_version}, bản mới nhất là v{version}."
                continue
            if response.action == "approve":
                approved_file.write_text(
                    json.dumps(script.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
                )
                self._save_report(version, approved=True)
                return script
            previous = script
            if response.action == "regenerate":
                script = self._generate()
            elif response.action == "revert":
                target = response.revert_to if response.revert_to is not None else version - 1
                try:
                    version = self.store.revert(target)
                except KeyError as e:
                    notice = str(e.args[0])
                    continue
                script = self.store.load(version)
                ctx.theme = script.theme
                self._measure(script)
                changes = diff_scripts(previous, script) or ["Bản này giống bản hiện tại"]
                continue
            else:  # edit
                edit = response.edit
                outcome = self._edit(
                    script,
                    version,
                    edit.instruction if edit else None,
                    list(edit.ops) if edit else [],
                    [t.model_dump() for t in edit.targets] if edit else [],
                )
                notice = self._notice(outcome)
                if outcome.full_regen:
                    ctx.theme = outcome.script.theme
                    self.ctx, extra = apply_global(ctx, outcome.global_ops)
                    ctx = self.ctx
                    notice = "\n".join(x for x in [notice, *[f"Lưu ý: {w}" for w in extra]] if x)
                    script = self._generate()
                else:
                    script = outcome.script
                if script != previous:
                    ctx.theme = script.theme
            if script == previous:
                notice = notice or "Chưa có thay đổi nào."
                continue
            version = self.store.save(script)
            if response.action == "edit" and not (outcome.full_regen):
                self._measure(script)
                if self.fit and not self.fit.within:
                    notice = "\n".join(x for x in [notice, f"Lưu ý: {self.fit.warnings[-1]}"] if x)
            changes = diff_scripts(previous, script)
        raise RuntimeError("too many script review rounds")

    @staticmethod
    def _notice(outcome: EditOutcome) -> str:
        lines = [f"Bị từ chối: {r}" for r in outcome.rejected]
        lines += [f"Lưu ý: {w}" for w in outcome.warnings]
        lines += [f"Không áp dụng được: {e}" for e in outcome.errors]
        return "\n".join(lines)

    def _save_report(self, version: int, approved: bool = False) -> None:
        self.report.update(
            {
                "versions": self.store.versions(),
                "current_version": version,
                "approved": approved,
                "tokens": self.caller.tracker.to_dict(),
            }
        )
        (self.dir / "script_report.json").write_text(
            json.dumps(self.report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
