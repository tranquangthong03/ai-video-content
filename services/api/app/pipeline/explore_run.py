"""Runs the explorer steps (classify, map, analyze, synthesize, verify), resumably.

Files under <job_dir>/explore: pages/<n>.json|png, map.json, classify.json, insights/<n>.json,
profile.json (synthesized), profile_verified.json, verify/, report.json, usage.json.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.browser.enter_policy import Policy
from app.browser.session import BrowserSession
from app.browser.urls import path_prefix
from app.core.features import NAME_SIMILARITY, name_similarity
from app.core.usage import BudgetExceeded, UsageTracker
from app.explorer.analyze import analyze_pages
from app.explorer.classify import classify_site
from app.explorer.mapper import (
    BlockedByChallenge,
    crawl,
    explore_targeted,
    normalize_url,
    pick_candidates_by_description,
    same_site,
    save_map,
)
from app.explorer.models import PageData
from app.explorer.report import Deadline, DeadlineExceeded, Report
from app.explorer.stateful import run_stateful
from app.explorer.synthesize import synthesize
from app.explorer.verify import verify_features
from app.llm.json_call import JsonCaller
from app.schemas.generated.page_insight import PageInsight
from app.schemas.generated.product_profile import Feature, ProductProfile

Progress = Callable[[str, str], None]  # (step, message)


@dataclass
class ExploreState:
    url: str
    pages: list[PageData] = field(default_factory=list)
    insights: list[PageInsight] = field(default_factory=list)
    site_type: str = "landing"
    profile: ProductProfile | None = None


class ExploreRunner:
    def __init__(
        self,
        url: str,
        job_dir: Path,
        caller: JsonCaller,
        tracker: UsageTracker,
        *,
        storage_state: Path | None = None,
        max_pages: int = 15,
        timeout_s: float = 300,
        allow_mutations: bool = False,
        scope: str = "path",
        enter_policy: Policy = "strict",
        progress: Progress | None = None,
    ) -> None:
        self.url = url
        self.dir = job_dir / "explore"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.caller = caller
        self.tracker = tracker
        self.storage_state = storage_state
        self.max_pages = max_pages
        self.allow_mutations = allow_mutations
        self.scope = scope
        self.enter_policy = enter_policy
        # a start URL with a real path limits the crawl (and clicks) to that path
        self.scope_prefix = path_prefix(normalize_url(url) or url) if scope == "path" else None
        self.deadline = Deadline(timeout_s)
        self.report = Report(url)
        self._load_report()
        self.progress = progress or (lambda step, msg: None)
        self.state = ExploreState(url)

    def use_session(self, storage_state: Path | None, url: str | None = None) -> None:
        """After a (new) sign-in: explore with that session, from `url` when it changed."""
        self.storage_state = storage_state
        if url and url != self.url:
            self.url = url
            self.state.url = url
            self.report.data["start_url"] = url
            self.scope_prefix = (
                path_prefix(normalize_url(url) or url) if self.scope == "path" else None
            )

    # --- persistence -------------------------------------------------------------------------

    def _load_report(self) -> None:
        path = self.dir / "report.json"
        if path.is_file():
            self.report.data.update(json.loads(path.read_text(encoding="utf-8")))

    def save(self, status: str | None = None) -> None:
        if status:
            self.report.data["status"] = status
        self.report.data["tokens"] = self.tracker.to_dict()
        self.report.save(self.dir / "report.json")
        (self.dir / "usage.json").write_text(json.dumps(self.tracker.to_dict()), encoding="utf-8")

    def _load_pages(self) -> list[PageData]:
        files = sorted((self.dir / "pages").glob("*.json"), key=lambda p: int(p.stem))
        return [PageData.model_validate_json(f.read_text(encoding="utf-8")) for f in files]

    # --- steps -------------------------------------------------------------------------------

    def run(self) -> ExploreState:
        """Run or resume the exploration (may raise Blocked/Budget/Deadline errors)."""
        try:
            with BrowserSession(
                self.url, storage_state=self.storage_state, allow_mutations=self.allow_mutations
            ) as session:
                self._crawl(session)
                self._analyze()
                self._synthesize()
                self._verify(session)
                self._stateful(session)
            self.save("done")
        except BlockedByChallenge:
            self.save("blocked_by_challenge")
            raise
        except BudgetExceeded:
            self.save("paused_token_ceiling")
            raise
        except DeadlineExceeded:
            self.save("paused_timeout")
            raise
        finally:
            pass
        return self.state

    def _crawl(self, session: BrowserSession) -> None:
        existing = self._load_pages() if (self.dir / "map.json").is_file() else []
        classify_file = self.dir / "classify.json"
        if existing:
            self.state.pages = existing
            self.progress("crawl", f"dùng lại {len(existing)} trang đã khám phá")
        else:
            context = session.new_context()
            page = context.new_page()

            def on_page(n: int, total: int, data: PageData) -> None:
                if n == 1:
                    self.progress("classify", "Phân loại website...")
                    with self.report.timed("classify"):
                        site_type, source = classify_site(self.caller, data)
                    self.state.site_type = site_type
                    classify_file.write_text(json.dumps({"site_type": site_type, "source": source}))
                    self.report.data["site_type"] = site_type
                    self.progress("classify", f"site_type = {site_type} ({source})")
                self.progress("map", f"Đã xem {n}/{total}: {data.url}")

            try:
                with self.report.timed("map"):
                    pages, frontier = crawl(
                        page,
                        context,
                        self.url,
                        self.dir,
                        self.report,
                        self.deadline,
                        max_pages=self.max_pages,
                        on_page=on_page,
                        scope=self.scope,
                        authenticated=self.storage_state is not None,
                    )
            finally:
                context.close()
            self.state.pages = pages
            save_map(self.dir / "map.json", frontier, pages)
            self.report.data["pages_seen"] = [p.url for p in pages]
            self.report.data["request_guard"] = session.guard.report()
            self.save()
        if classify_file.is_file():
            self.state.site_type = json.loads(classify_file.read_text())["site_type"]
            self.report.data["site_type"] = self.state.site_type
        if not self.state.pages:
            raise RuntimeError("no page could be explored (see report.json for blockers)")

    def _analyze(self) -> None:
        self.deadline.check("analyze")
        self.progress("analyze", f"Phân tích {len(self.state.pages)} trang...")
        with self.report.timed("analyze"):
            self.state.insights = analyze_pages(
                self.caller,
                self.state.pages,
                self.dir,
                self.report,
                on_done=lambda done, total: self.progress(
                    "analyze", f"Phân tích {done}/{total} trang"
                ),
            )
        self.save()

    def _synthesize(self) -> None:
        profile_file = self.dir / "profile.json"
        if profile_file.is_file():
            self.state.profile = ProductProfile.model_validate_json(
                profile_file.read_text(encoding="utf-8")
            )
            return
        self.deadline.check("synthesize")
        self.progress("synthesize", "Tổng hợp hiểu biết về sản phẩm...")
        with self.report.timed("synthesize"):
            profile = synthesize(
                self.caller,
                self.url,
                self.state.site_type,
                self.state.pages,
                self.state.insights,
                self.report,
            )
        question = self.report.data.get("scope_question")
        if question and question not in profile.open_questions:
            profile.open_questions.insert(0, question)  # asked at confirm_understanding
        profile_file.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
        self.state.profile = profile
        self.save()

    def _verify(self, session: BrowserSession) -> None:
        verified_file = self.dir / "profile_verified.json"
        if verified_file.is_file():
            self.state.profile = ProductProfile.model_validate_json(
                verified_file.read_text(encoding="utf-8")
            )
            return
        assert self.state.profile is not None
        self.progress("verify", "Kiểm chứng tính năng nào demo được...")
        with self.report.timed("verify"):
            verify_features(
                session,
                self.state.profile,
                self.state.pages,
                self.url,
                self.dir,
                self.report,
                self.deadline,
                insights=self.state.insights,
                enter_policy=self.enter_policy,
                scope_prefix=self.scope_prefix,
                on_feature=lambda i, n, f: self.progress(
                    "verify", f"Kiểm chứng {i}/{n}: {f.name} → {f.demo_kind} ({f.demo_score})"
                ),
            )
        self.report.data["request_guard"] = session.guard.report()
        verified_file.write_text(self.state.profile.model_dump_json(indent=2), encoding="utf-8")
        self.save()

    def _stateful(self, session: BrowserSession) -> None:
        """Features that only appear once data exists (see explorer/stateful.py)."""
        marker = self.dir / "stateful.json"
        if marker.is_file():
            return
        assert self.state.profile is not None
        self.progress("stateful", "Tìm tính năng chỉ hiện sau khi đã có dữ liệu...")
        with self.report.timed("stateful"):
            added = run_stateful(
                session,
                self.state.profile,
                self.state.pages,
                self.state.insights,
                root_url=self.url,
                site_type=self.state.site_type,
                caller=self.caller,
                out_dir=self.dir,
                report=self.report,
                deadline=self.deadline,
                enter_policy=self.enter_policy,
                scope_prefix=self.scope_prefix,
                progress=self.progress,
            )
        for page in self.state.pages:  # keep the delta refs (sNeM) resolvable after a resume
            if page.setup_steps:
                (self.dir / "pages" / f"{page.n}.json").write_text(
                    json.dumps(page.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
                )
        self.report.data["request_guard"] = session.guard.report()
        (self.dir / "profile_verified.json").write_text(
            self.state.profile.model_dump_json(indent=2), encoding="utf-8"
        )
        marker.write_text(json.dumps({"added": [f.id for f in added]}), encoding="utf-8")
        self.save()

    # --- explore_more ------------------------------------------------------------------------

    def explore_more(self, urls: list[str], description: str | None) -> ProductProfile:
        """View extra pages (urls and/or a description) and merge their features in."""
        assert self.state.profile is not None
        known = json.loads((self.dir / "map.json").read_text(encoding="utf-8"))
        targets = [
            u for u in (normalize_url(x, self.url) for x in urls) if u and same_site(u, self.url)
        ]
        if description:
            targets += pick_candidates_by_description(
                known["candidates"], known["visited"], description
            )
        targets = [t for t in dict.fromkeys(targets) if t not in known["visited"]]
        if not targets:
            self.report.warn("explore_more: no new page matched the request")
            return self.state.profile

        self.deadline = Deadline(self.deadline.seconds)  # fresh budget for this interactive step
        with BrowserSession(
            self.url, storage_state=self.storage_state, allow_mutations=self.allow_mutations
        ) as s:
            context = s.new_context()
            page = context.new_page()
            self.progress("map", f"Xem thêm: {targets[0]}")
            new_pages = explore_targeted(
                page,
                targets,
                self.url,
                self.dir,
                self.report,
                first_n=len(self.state.pages) + 1,
                description=description,
                visited=known["visited"],
            )
            context.close()
            if not new_pages:
                return self.state.profile
            self.state.pages += new_pages
            self.report.data["pages_seen"] = [p.url for p in self.state.pages]
            new_insights = analyze_pages(self.caller, new_pages, self.dir, self.report)
            self.state.insights += new_insights
            fresh = synthesize(
                self.caller,
                self.url,
                self.state.site_type,
                new_pages,
                new_insights,
                self.report,
                existing=self.state.profile,
            )
            merged = merge_profiles(self.state.profile, fresh)
            added = [
                f
                for f in merged.features
                if f.id not in {x.id for x in self.state.profile.features}
            ]
            # shallow copy shares the Feature objects, so verification fills them in `merged`
            only_new = merged.model_copy(update={"features": added})
            verify_features(
                s,
                only_new,
                self.state.pages,
                self.url,
                self.dir,
                self.report,
                self.deadline,
                insights=self.state.insights,
                limit=3,
                enter_policy=self.enter_policy,
                scope_prefix=self.scope_prefix,
            )
        self.state.profile = merged
        known["visited"] = [p.url for p in self.state.pages]
        (self.dir / "map.json").write_text(
            json.dumps(known, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (self.dir / "profile_verified.json").write_text(
            merged.model_dump_json(indent=2), encoding="utf-8"
        )
        self.save()
        return merged


def same_feature(new: Feature, old: Feature) -> bool:
    """Same name, same intent key or a near-identical name (accents and case ignored)."""
    if new.name.strip().lower() == old.name.strip().lower():
        return True
    if new.intent_key and new.intent_key == old.intent_key:
        return True
    return name_similarity(new.name, old.name) >= NAME_SIMILARITY


def merge_profiles(old: ProductProfile, new: ProductProfile) -> ProductProfile:
    """Keep every old feature (with its demo_score); append features only the new run found."""
    merged = old.model_copy(deep=True)
    ids = {f.id for f in merged.features}
    for feature in new.features:
        if any(same_feature(feature, old) for old in merged.features):
            continue
        copy: Feature = feature.model_copy(deep=True)
        while copy.id in ids:
            copy.id += "_n"
        ids.add(copy.id)
        merged.features.append(copy)
    merged.open_questions = list(dict.fromkeys(merged.open_questions + new.open_questions))
    return merged
