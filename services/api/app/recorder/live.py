"""Filming a flow while the Flow Agent runs it (the film behind FlowRun.live).

The agent's own browser context records its video. The visible mouse and slow typing of the
recorder are used for every action (Ops), each action is held on screen like a recorded scene, and
the logs the camera needs (focus, clicks, frame_inventory, what was done) are kept on the clip's
clock. Besides that three kinds of time are noted so the producer can cut them out:

- llm_wait: from the moment the agent starts asking the model until it has the answer. Nothing is
  done on the page in that time (no mouse, no hover, no filler): the stretch is cut by its times,
  whatever the page animates meanwhile.
- retry / rejected: an action that failed (an option that is not there, a refused click, a made-up
  ref). It is a retry when a later action succeeded on the SAME resolved element (tag, bbox within
  8 px, accessible name, index among the elements of that name), else it was only rejected.
"""

import json
import random
import shutil
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Page

from app.browser.form_actions import Ops
from app.browser.session import BrowserSession
from app.recorder import inventory, sync
from app.recorder.record import CAPTURE, INIT_JS, TAIL_MS, _Recorder, to_mp4
from app.schemas.generated.action import BrowserAction

BBOX_TOLERANCE_PX = 8
HOLD_AS = {"navigate": "click"}  # what the recorder calls it


def element_signature(element: Any, state: Any) -> dict[str, Any] | None:
    """What identifies the element an action resolved to: tag, name, where it is, and which of the
    elements of that name it is (two «yyyy-dd-mm» fields are told apart by place and index)."""
    if element is None:
        return None
    bbox = element.locator.bbox
    same = [e for e in state.elements if e.tag == element.tag and e.name == element.name]
    index = next((i for i, e in enumerate(same) if e.ref == element.ref), 0)
    return {
        "tag": element.tag,
        "name": element.name,
        "x": bbox.x if bbox else None,
        "y": bbox.y if bbox else None,
        "index": index,
    }


def same_element(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    if a is None or b is None:
        return False
    if a["tag"] != b["tag"] or a["name"] != b["name"] or a["index"] != b["index"]:
        return False
    if a["x"] is None or b["x"] is None:  # no place known: the rest has to do
        return True
    return abs(a["x"] - b["x"]) <= BBOX_TOLERANCE_PX and abs(a["y"] - b["y"]) <= BBOX_TOLERANCE_PX


def classify_failures(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Segments for the failed attempts: `retry` when a later attempt of the same kind succeeded on
    the same element, else `rejected`."""
    out = []
    for n, a in enumerate(attempts):
        if a["ok"]:
            continue
        later_ok = any(
            b["ok"] and b["do"] == a["do"] and same_element(a["sig"], b["sig"])
            for b in attempts[n + 1 :]
        )
        out.append(
            {
                "from_ms": a["start"], "to_ms": a["end"], "step": a.get("step"),
                "kind": "retry" if later_ok else "rejected",
                "note": f"{a['do']} «{(a['sig'] or {}).get('name', '')}»",
            }
        )  # fmt: skip
    return out


class LiveFilm:
    def __init__(
        self,
        session: BrowserSession,
        job_dir: Path,
        *,
        root_url: str,
        viewport: dict[str, int] | None = None,
        color: str = "#756eeb",
        seed: str = "flow",
    ) -> None:
        self.session, self.job_dir, self.root_url = session, job_dir, root_url
        self.dir = job_dir / "flow" / "live"
        self.raw_dir = self.dir / "raw"
        self.viewport = viewport or CAPTURE
        self.color, self.seed = color, seed
        self.rec: _Recorder | None = None
        self.ops = Ops()
        self.marks: list[dict[str, int]] = []
        self.waits: list[dict[str, Any]] = []
        self.attempts: list[dict[str, Any]] = []
        self.start_offset_ms = 0
        self.content_ms = 0
        self.pulse_at_ms = 0
        self._video: Any = None
        self._wait_from: int | None = None
        self._cur: dict[str, Any] | None = None
        shutil.rmtree(self.dir, ignore_errors=True)  # a new run starts a new film
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    # --- setting up ---------------------------------------------------------------------------

    def prepare(self, context: BrowserContext) -> None:
        context.add_init_script(INIT_JS)

    def start(self, page: Page, *, allow_submit: bool) -> None:
        rec = _Recorder(
            self.session, page, self.root_url, self.dir, "live", color=self.color, policy="strict",
            rng=random.Random(self.seed), viewport=self.viewport,
        )  # fmt: skip
        rec.submit_ok = allow_submit
        rec.hover_submit = True  # the climax of a stopped flow points at the submit button
        self.rec, self._video = rec, page.video
        page.mouse.move(*rec.home)
        self.pulse_at_ms = sync.emit_pulse(page, rec.now)
        self.ops = rec._visible_ops()
        self.ops.scroll = self._scroll

    def opened(self) -> None:
        rec = self._rec()
        shown_from = self.pulse_at_ms + sync.PULSE_MS + sync.PULSE_SETTLE_MS
        if rec.now() < shown_from:
            rec.page.wait_for_timeout(shown_from - rec.now())
        self.start_offset_ms = rec.now()

    def _rec(self) -> _Recorder:
        assert self.rec is not None, "start() first"
        return self.rec

    def _scroll(self, pixels: int) -> None:
        rec = self._rec()
        rec.note_action("scroll", None)
        rec.event("scroll", rec.mouse[0], rec.mouse[1])
        rec.wheel(pixels)

    # --- waiting for the model -----------------------------------------------------------------

    def begin_wait(self) -> None:
        self._wait_from = self._rec().now()

    def end_wait(self) -> None:
        if self._wait_from is not None:
            now = self._rec().now()
            if now > self._wait_from:
                self.waits.append(
                    {"from_ms": self._wait_from, "to_ms": now, "kind": "llm_wait", "step": None,
                     "note": ""}
                )  # fmt: skip
            self._wait_from = None

    # --- one action ---------------------------------------------------------------------------

    def attempt_start(self) -> None:
        rec = self._rec()
        inventory.mark_baseline(rec.page)
        self._cur = {"start": rec.now(), "focus0": len(rec.focus_log), "do": None, "sig": None}

    def on_target(self, do: str, element: Any, state: Any, target: Any) -> None:
        if self._cur is None:
            return
        self._cur["do"] = do
        self._cur["sig"] = element_signature(element, state)
        if target is not None:  # a scroll notes itself
            self._rec().note_action(HOLD_AS.get(do, do), target)

    def attempt_end(self, ok: bool, step: int | None, do: str) -> None:
        rec, cur = self._rec(), self._cur
        if cur is None:
            return
        cur["do"] = cur["do"] or do
        if ok:
            rec.snap()
            rec.hold(BrowserAction(do=HOLD_AS.get(do, do)), cur["focus0"])  # type: ignore[arg-type]
            if step is not None:
                self.marks.append({"i": step, "start_ms": cur["start"], "end_ms": rec.now()})
        self.attempts.append(
            {
                "start": cur["start"],
                "end": rec.now(),
                "ok": ok,
                "do": cur["do"],
                "sig": cur["sig"],
                "step": step,
            }  # fmt: skip
        )
        self._cur = None

    def point_at(self, spec: dict[str, Any], name: str, first_step: int) -> bool:
        """Hover and outline a button with the recorder's own steps (two numbered steps)."""
        rec = self._rec()
        ok = True
        for offset, do in enumerate(("hover", "highlight")):
            action = BrowserAction.model_validate(
                {"do": do, "locator": spec, "ms": 1800 if do == "highlight" else None}
            )
            start, failed = rec.now(), rec.failed
            rec.step(action, first_step + offset, "action")
            if rec.failed > failed:
                ok = False
                break
            self.marks.append({"i": first_step + offset, "start_ms": start, "end_ms": rec.now()})
        return ok

    # --- the end ---------------------------------------------------------------------------------

    def stop(self) -> None:
        rec = self._rec()
        rec.page.wait_for_timeout(TAIL_MS)
        rec.collect_activity()
        self.content_ms = rec.now()

    def finish(self) -> dict[str, Any] | None:
        rec = self._rec()
        if self._video is None:
            return None
        clip = self.dir / "flow.mp4"
        to_mp4(Path(self._video.path()), clip)
        shutil.rmtree(self.raw_dir, ignore_errors=True)  # the webm is no longer needed
        offset = sync.measure_offset(clip, self.pulse_at_ms)
        activity = (
            [t - rec.t0 * 1000 for t in rec.activity] + [e["t_ms"] for e in rec.log] + rec.marks
        )
        logs = {
            "focus_log": rec.focus_log, "click_log": rec.log, "inventory": rec.inventory,
            "action_log": rec.action_log, "activity_ms": activity,
            "warnings": rec.warnings if offset is not None else
            [*rec.warnings, "không đo được độ lệch đồng hồ log/hình (xung đồng bộ), dùng 0"],
            "width": self.viewport["width"], "height": self.viewport["height"],
        }  # fmt: skip
        (self.dir / "logs.json").write_text(json.dumps(logs, ensure_ascii=False), encoding="utf-8")
        segments = sorted(
            [*self.waits, *classify_failures(self.attempts)], key=lambda s: s["from_ms"]
        )
        return {
            "clip": clip.relative_to(self.job_dir).as_posix(),
            "logs": (self.dir / "logs.json").relative_to(self.job_dir).as_posix(),
            "content_ms": self.content_ms, "start_offset_ms": self.start_offset_ms,
            "sync_offset_ms": offset or 0, "pulse_at_ms": self.pulse_at_ms,
            "segments": segments, "marks": self.marks,
        }  # fmt: skip
