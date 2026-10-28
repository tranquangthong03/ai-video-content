"""Interactive loops: confirm understanding -> choose concept -> approve outline.

Everything the user sees or answers goes through InteractionRequest / UserResponse, via a Frontend.
Artifacts under <job_dir>: confirmed_profile.json, confirmed_notes.json, concepts.json,
concept_choice.json, outline_v<n>.json, outline_approved.json, interactions.jsonl.
"""

import json
from collections.abc import Callable
from pathlib import Path

from app.core import brief as brief_mod
from app.core import flow_choice
from app.core.features import default_selection, merge_duplicates, restrict_profile
from app.core.flow_choice import FlowSelection
from app.core.interaction import make_request
from app.flows import discovery, storyboard
from app.llm.json_call import JsonCaller, LLMCallError
from app.pipeline.asker import Cancelled as Cancelled  # re-exported: callers import it from here
from app.pipeline.asker import ask as ask_user
from app.pipeline.frontend import Frontend
from app.proposal import beat_mapper, brief_suggest
from app.proposal import concepts as concepts_mod
from app.proposal import outline as outline_mod
from app.proposal import selection as selection_mod
from app.proposal import understanding as understanding_mod
from app.proposal.wordlimit import enforce_outline
from app.schemas.generated.core_flow import CoreFlow
from app.schemas.generated.flow_run import FlowRun
from app.schemas.generated.interaction import InteractionRequest
from app.schemas.generated.marketing_brief import MarketingBrief
from app.schemas.generated.outline import Outline
from app.schemas.generated.product_profile import ProductProfile
from app.schemas.generated.user_response import UserResponse
from app.schemas.generated.video_concept import VideoConcept

MAX_CLARIFY_ROUNDS = 2


class ProposalRunner:
    def __init__(
        self,
        job_id: str,
        job_dir: Path,
        caller: JsonCaller,
        frontend: Frontend,
        *,
        explore_more: Callable[[list[str], str | None], ProductProfile],
        flow_caller: JsonCaller | None = None,
    ) -> None:
        self.job_id = job_id
        self.dir = job_dir
        self.caller = caller
        self.frontend = frontend
        self.explore_more = explore_more
        self.flow_caller = flow_caller or caller  # the flow_discovery role (see llm/router)
        self.warnings: list[str] = []  # word-limit cuts etc., saved with the approved outline
        self.unselected_names: list[str] = []  # features the user left out of the video
        self.known_ids: set[str] = set()  # feature ids the user has already seen
        self.beat_mappings: list[dict] = []  # type: ignore[type-arg]  # beat_feature_mapper decisions

    # --- interaction plumbing ----------------------------------------------------------------

    def _ask(self, request: InteractionRequest) -> UserResponse:
        return ask_user(self.frontend, self.dir, request)

    # --- 1. understanding --------------------------------------------------------------------

    def confirm_understanding(self, base: ProductProfile) -> tuple[ProductProfile, str]:
        """Returns (confirmed profile, notes for the concept proposer from the answers)."""
        done = self.dir / "confirmed_profile.json"
        notes_file = self.dir / "confirmed_notes.json"
        if done.is_file():
            return ProductProfile.model_validate_json(done.read_text(encoding="utf-8")), (
                json.loads(notes_file.read_text(encoding="utf-8")) if notes_file.is_file() else ""
            )
        edits = understanding_mod.ProfileEdits()
        notice = ""
        self.known_ids = {f.id for f in base.features}
        for round_no in range(1, 30):
            profile = understanding_mod.apply_edits(base, edits)
            response = self._ask(
                understanding_mod.build_request(
                    self.job_id, profile, round_no=round_no, notice=notice
                )
            )
            if response.action == "explore_more":
                query = response.explore
                before = len(base.features)
                base = self.explore_more(
                    query.urls if query else [], query.description if query else None
                )
                self.known_ids |= {f.id for f in base.features}
                notice = f"Đã xem thêm trang: có {len(base.features) - before} tính năng mới."
                continue
            understanding_mod.merge_response(edits, response)
            if response.action == "answer":
                confirmed = understanding_mod.apply_edits(base, edits)
                notes = "\n".join(f"- {k}: {v}" for k, v in edits.answers.items())
                done.write_text(confirmed.model_dump_json(indent=2), encoding="utf-8")
                notes_file.write_text(json.dumps(notes, ensure_ascii=False), encoding="utf-8")
                return confirmed, notes
            notice = "Đã cập nhật theo yêu cầu của bạn."
        raise RuntimeError("too many confirm_understanding rounds")

    # --- 1b. feature selection ---------------------------------------------------------------

    def select_features(self, profile: ProductProfile) -> tuple[ProductProfile, list[str]]:
        """Returns (profile with duplicates merged and features found on request, ordered ids).

        The video shows only the selected features. "explore_more" looks at more pages and asks
        again, with what it found marked as new.
        """
        done = self.dir / "selected_features.json"
        if done.is_file():
            saved = json.loads(done.read_text(encoding="utf-8"))
            return self._finish_selection(
                ProductProfile.model_validate(saved["profile"]), saved["selected"], save=False
            )
        profile, dropped = merge_duplicates(profile)
        if dropped:
            self.warnings.append(
                "Đã gộp tính năng trùng ý định: " + ", ".join(f"{a}→{b}" for a, b in dropped)
            )
        self.known_ids |= {f.id for f in profile.features}
        default = default_selection(profile)
        new_ids: list[str] = []
        notice = ""
        for _ in range(30):
            response = self._ask(
                selection_mod.build_request(
                    self.job_id, profile, default, new_ids=new_ids, notice=notice
                )
            )
            if response.action == "explore_more":
                query = response.explore
                fresh = self.explore_more(
                    query.urls if query else [], query.description if query else None
                )
                found = [f for f in fresh.features if f.id not in self.known_ids]
                self.known_ids |= {f.id for f in fresh.features}
                profile, merged = merge_duplicates(
                    profile.model_copy(update={"features": [*profile.features, *found]})
                )
                gone = {a for a, _ in merged}
                new_ids = [f.id for f in found if f.id not in gone]
                notice = (
                    f"Đã xem thêm trang: có {len(new_ids)} tính năng mới."
                    if new_ids
                    else "Đã xem thêm nhưng không thấy tính năng mới."
                )
                continue
            selected = list((response.answers or {})["selected_features"])
            return self._finish_selection(profile, selected, save=True)
        raise RuntimeError("too many select_features rounds")

    def _finish_selection(
        self, full: ProductProfile, selected: list[str], *, save: bool
    ) -> tuple[ProductProfile, list[str]]:
        """Everything after this step sees only the selected features (confirmed_profile.json)."""
        restricted = restrict_profile(full, selected)
        self.unselected_names = [f.name for f in full.features if f.id not in selected]
        if save:
            (self.dir / "selected_features.json").write_text(
                json.dumps(
                    {"selected": selected, "profile": full.model_dump(mode="json")},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (self.dir / "confirmed_profile.json").write_text(
                restricted.model_dump_json(indent=2), encoding="utf-8"
            )
        return restricted, selected

    # --- 1c. core flow selection (replaces 1b when the job runs in flow mode) ----------------

    def select_flow(
        self,
        profile: ProductProfile,
        pages: list[discovery.PageSummary],
        root_url: str,
        infeasible: dict[str, tuple[CoreFlow, str]] | None = None,
    ) -> FlowSelection | None:
        """The flows the video shows, or None when discovery found nothing usable (the caller then
        falls back to select_features). Asks again after a self-described flow was added.

        infeasible: flows (with the site's message) that could not be done on this account: they
        stay on the card, marked, and discovery is asked again without them."""
        done = self.dir / "selected_flow.json"
        if done.is_file() and not infeasible:
            saved = json.loads(done.read_text(encoding="utf-8"))
            return FlowSelection(
                flows=[CoreFlow.model_validate(f) for f in saved["flows"]],
                submit_policy=saved["submit_policy"],
                warnings=saved.get("warnings", []),
            )
        try:
            avoid = [(f.title, why) for f, why in (infeasible or {}).values()]
            flows = discovery.propose_flows(self.flow_caller, profile, pages, avoid or None)
        except LLMCallError as e:
            self.warnings.append(
                f"Không xác định được luồng chính ({e}); chuyển sang chọn tính năng."
            )
            return None
        marked = {fid: why for fid, (_, why) in (infeasible or {}).items()}
        flows = [
            *flows,
            *(f for f, _ in (infeasible or {}).values() if f.id not in {x.id for x in flows}),
        ]
        if not [f for f in flows if f.id not in marked]:
            self.warnings.append("Không tìm thấy luồng chính; chuyển sang chọn tính năng.")
            return None
        (self.dir / "flows_proposed.json").write_text(
            json.dumps([f.model_dump() for f in flows], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        default = flow_choice.default_flow_ids([f for f in flows if f.id not in marked])
        notice = ""
        for flow, why in (infeasible or {}).values():
            notice += f"Luồng «{flow.title}» không khả thi trên tài khoản này: {why}\n"
        for _ in range(8):
            response = self._ask(
                flow_choice.build_request(
                    self.job_id,
                    flows,
                    root_url,
                    default=default,
                    notice=notice.strip(),
                    infeasible=marked,
                )
            )
            answer = flow_choice.read_answer(response)
            if answer.description:
                own = discovery.normalize_flow(self.flow_caller, profile, pages, answer.description)
                if own is None:
                    notice, default = (
                        "Chưa hiểu mô tả của bạn, hãy thử viết cụ thể hơn.",
                        answer.selected,
                    )
                    continue
                flows = [f for f in flows if f.id != own.id] + [own]
                keep = [i for i in answer.selected if i != own.id][
                    : flow_choice.MAX_SELECTED_FLOWS - 1
                ]
                default = [own.id, *keep]
                notice = "Đã thêm luồng bạn mô tả (đã chọn sẵn)."
                continue
            by_id = {f.id: f for f in flows}
            chosen = [by_id[i] for i in answer.selected]
            policy, refused = flow_choice.resolve_submit_policy(root_url, chosen, answer)
            selection = FlowSelection(chosen, policy, [refused] if refused else [])
            done.write_text(
                json.dumps(
                    {
                        "flows": [f.model_dump() for f in chosen],
                        "submit_policy": policy,
                        "warnings": selection.warnings,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return selection
        raise RuntimeError("too many select_flow rounds")

    # --- 1e. the marketing brief: what the website does not say ----------------------------------

    def marketing_brief(
        self,
        profile: ProductProfile,
        flow: CoreFlow | None,
        given: MarketingBrief | None = None,
    ) -> MarketingBrief | None:
        """The user's brief (None = skipped). `given`: a brief that came with the job (CLI --brief)
        is used as it is, without asking. Asked once; the answer (or the skip) is saved."""
        if brief_mod.asked(self.dir):
            return brief_mod.load_brief(self.dir)
        if given is not None:
            cleaned = brief_mod.clean_brief(given)
            brief_mod.save_brief(self.dir, cleaned)
            return None if brief_mod.is_empty(cleaned) else cleaned
        wants = getattr(self.frontend, "wants", None)
        if wants is not None and not wants("marketing_brief"):
            brief_mod.save_brief(self.dir, None)  # --auto without a brief: the old behaviour
            return None
        suggestions, warning = brief_suggest.suggest(self.caller, profile, flow)
        if warning:
            self.warnings.append(warning)
        response = self._ask(brief_mod.build_request(self.job_id, suggestions))
        if response.action == "answer" and response.brief is not None:
            cleaned = brief_mod.clean_brief(response.brief)
            brief_mod.save_brief(self.dir, cleaned)
            return None if brief_mod.is_empty(cleaned) else cleaned
        brief_mod.save_brief(self.dir, None)
        return None

    # --- 1d. storyboard review of the flow the agent ran ---------------------------------------

    def review_storyboard(
        self,
        flow: CoreFlow,
        run_flow: Callable[[str, FlowRun | None, int], FlowRun],
        *,
        max_rounds: int = 10,
    ) -> FlowRun:
        """Show what the agent did and loop until the user approves.

        run_flow(notes, previous, keep) runs the agent: notes are every change asked so far,
        previous/keep are the earlier run and how many of its leading steps are repeated as they
        are (0 = start over). The approved run is saved to flow/flow_approved.json."""
        approved = self.dir / "flow" / "flow_approved.json"
        if approved.is_file():
            return FlowRun.model_validate_json(approved.read_text(encoding="utf-8"))
        notes: list[str] = []
        run = run_flow("", None, 0)
        notice = ""
        for version in range(1, max_rounds + 1):
            versions = self.dir / "flow" / "versions"
            versions.mkdir(parents=True, exist_ok=True)
            (versions / f"v{version}.json").write_text(
                run.model_dump_json(indent=2), encoding="utf-8"
            )
            response = self._ask(
                storyboard.build_request(self.job_id, flow, run, notice=notice, version=version)
            )
            if response.action == "approve":
                if run.status == "failed" or len(run.steps) < 2:
                    notice = "Luồng chưa có bước nào để quay; hãy sửa hoặc chạy lại."
                    continue
                approved.write_text(run.model_dump_json(indent=2), encoding="utf-8")
                return run
            if response.action == "regenerate":
                notes.clear()
                run, notice = run_flow("", None, 0), "Đã chạy lại luồng từ đầu."
                continue
            instruction = ((response.edit.instruction if response.edit else "") or "").strip()
            if not instruction:
                notice = "Bạn chưa nhập yêu cầu sửa."
                continue
            notes.append(instruction)
            keep = storyboard.keep_prefix(run, instruction)
            run = run_flow("\n".join(notes), run, keep)
            notice = (
                f"Đã chạy lại theo yêu cầu, giữ {max(0, keep - 1)} bước đầu."
                if keep > 1
                else "Đã chạy lại theo yêu cầu từ đầu."
            )
        raise RuntimeError("too many flow_storyboard_review rounds")

    # --- 2. concepts -------------------------------------------------------------------------

    def choose_concept(self, profile: ProductProfile, notes: str) -> tuple[VideoConcept, str]:
        """Returns (chosen concept, free-text notes the user attached to the choice)."""
        concepts_file = self.dir / "concepts.json"
        choice_file = self.dir / "concept_choice.json"
        if concepts_file.is_file() and choice_file.is_file():
            concepts = [
                VideoConcept(**c) for c in json.loads(concepts_file.read_text(encoding="utf-8"))
            ]
            choice = json.loads(choice_file.read_text(encoding="utf-8"))
            return next(c for c in concepts if c.id == choice["concept_id"]), choice["notes"]

        guidance = notes
        for _ in range(10):
            concepts = concepts_mod.propose_concepts(
                self.caller,
                profile,
                guidance,
                warnings=self.warnings,
                unselected_names=self.unselected_names,
            )
            concepts_file.write_text(
                json.dumps([c.model_dump() for c in concepts], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            while True:
                response = self._ask(concepts_mod.build_request(self.job_id, concepts))
                try:
                    decision = concepts_mod.read_decision(concepts, response)
                except ValueError as e:
                    self.frontend.info(f"[red]{e}[/]")
                    continue
                break
            if decision.kind == "regenerate":
                guidance = f"{notes}\n{decision.notes}".strip()
                continue
            assert decision.concept is not None
            choice_file.write_text(
                json.dumps(
                    {"concept_id": decision.concept.id, "notes": decision.notes}, ensure_ascii=False
                ),
                encoding="utf-8",
            )
            return decision.concept, decision.notes
        raise RuntimeError("too many concept rounds")

    # --- 3. outline --------------------------------------------------------------------------

    def _map_beats(
        self, profile: ProductProfile, outline: Outline, only: set[str] | None = None
    ) -> tuple[Outline, list[str]]:
        """Link demo beats to features (beat_feature_mapper); on failure keep the outline."""
        if not beat_mapper.needs_mapping(outline) and only is None:
            return outline, []
        try:
            mapped = beat_mapper.map_beats(self.caller, profile, outline, only_beats=only)
        except LLMCallError as e:
            self.warnings.append(f"Chưa gắn được tính năng cho các beat: {e}")
            return outline, []
        self.warnings += mapped.warnings
        self.beat_mappings.append({"outline_version": outline.version, "mapping": mapped.mapping})
        (self.dir / "beat_mapping.json").write_text(
            json.dumps(self.beat_mappings, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return mapped.outline, mapped.changes

    def _plan_and_apply(
        self, profile: ProductProfile, concept: VideoConcept, outline: Outline, instruction: str
    ) -> tuple[Outline, list[str], str]:
        """LLM plans ops for `instruction`, code applies them: (outline, changes, notice)."""
        valid = {f.id for f in profile.features}
        text = instruction
        for _ in range(MAX_CLARIFY_ROUNDS + 1):
            try:
                plan = outline_mod.edit_outline(self.caller, profile, concept, outline, text)
            except LLMCallError as e:
                return outline, [], f"Chưa xử lý được yêu cầu ({e}). Bạn thử diễn đạt lại nhé."
            if plan.status == "needs_clarification" and plan.clarification:
                q = plan.clarification
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
                continue
            applied = outline_mod.apply_ops(outline, plan.ops, valid)
            before = {b.id: b.text for b in outline.beats}
            touched = {b.id for b in applied.outline.beats if before.get(b.id) != b.text}
            if touched:  # new or reworded beats: link them to a feature when they show one
                applied.outline, linked = self._map_beats(profile, applied.outline, touched)
                applied.changes += linked
            shortened, cut_warnings = enforce_outline(self.caller, applied.outline)  # <= 15 words
            self.warnings += cut_warnings
            notices = [f"Bị từ chối: {r.request} — {r.reason}" for r in plan.rejected]
            notices += [f"Lưu ý: {w}" for w in [*plan.warnings, *applied.warnings, *cut_warnings]]
            notices += [f"Không áp dụng được: {e}" for e in applied.errors]
            return applied.outline, [*applied.changes, *shortened], "\n".join(notices)
        return outline, [], "Yêu cầu chưa rõ, dàn ý giữ nguyên."

    def review_outline(
        self, profile: ProductProfile, concept: VideoConcept, concept_notes: str
    ) -> Outline:
        approved_file = self.dir / "outline_approved.json"
        if approved_file.is_file():
            return Outline.model_validate_json(approved_file.read_text(encoding="utf-8"))

        outline = outline_mod.outline_from_concept(concept, profile)
        outline, changes = self._map_beats(profile, outline)
        notice = ""
        if (
            concept_notes.strip()
        ):  # notes attached to the concept choice are the first edit instruction
            outline, changes, notice = self._plan_and_apply(
                profile, concept, outline, concept_notes
            )
        for _ in range(30):
            (self.dir / f"outline_v{outline.version}.json").write_text(
                outline.model_dump_json(indent=2), encoding="utf-8"
            )
            response = self._ask(
                outline_mod.build_request(
                    self.job_id, outline, changes=changes, notice=notice, profile=profile
                )
            )
            if response.action == "approve":
                approved_file.write_text(outline.model_dump_json(indent=2), encoding="utf-8")
                (self.dir / "proposal_warnings.json").write_text(
                    json.dumps(self.warnings, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                return outline
            if response.action == "regenerate":
                outline = outline_mod.outline_from_concept(concept, profile)
                outline, linked = self._map_beats(profile, outline)
                changes, notice = ["Đã tạo lại dàn ý từ hướng đã chọn", *linked], ""
                continue
            instruction = (response.edit.instruction if response.edit else "") or ""
            if not instruction.strip():
                changes, notice = [], "Bạn chưa nhập yêu cầu sửa."
                continue
            outline, changes, notice = self._plan_and_apply(profile, concept, outline, instruction)
        raise RuntimeError("too many outline rounds")
