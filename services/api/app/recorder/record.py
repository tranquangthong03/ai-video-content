"""Record one scene of a script: drive the page like a person and write an mp4 plus a click log.

A new context per scene (the script's capture size, 1440x900 by default, video recording, request
guard on). Besides the click log it writes a focus log: boxes (clip pixels) the camera should
frame, with how long to stay (hold_ms). Steps come from the verified data in the script; a step
that fails is skipped with a warning and a screenshot, it never breaks the scene. The real
cursor is never drawn: the template paints its own from `click_log`.
"""

import random
import subprocess
import time
from dataclasses import dataclass, field
from math import hypot
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Page

from app.browser.blacklist import is_blocked, is_blocked_href
from app.browser.enter_policy import Policy, enter_decision
from app.browser.locate import Target, Unsafe, check_clickable, resolve
from app.browser.page_utils import dismiss_cookie_banner, wait_for_settle
from app.browser.session import BrowserSession
from app.core.samples import CATALOG, pick_sample, sample_path
from app.recorder import inventory, motion
from app.recorder.screenshot import take_screenshot
from app.schemas.generated.locator import LocatorSpec
from app.schemas.generated.scene import Scene
from app.script.lite import GROUP, is_lite

TAIL_MS = 300  # keep recording a little after the last step (the hold after it comes first)
HOLD_MS = 1500  # stay on the result of a main action so the viewer can read it
FOCUS_SAMPLE_MS = 400  # while scrolling: log the block in the middle of the viewport this often
INVENTORY_EVERY_MS = 1000  # scrolling, holding, filling: one frame_inventory snapshot a second
FILL_THRESHOLD_MS = 2000  # shorter than this and the renderer just holds the last frame
MAX_FILL_HOVERS = 3
CAPTURE = {"width": 1440, "height": 900}  # same as the schema default of script.capture
HOME_FRACTION = (0.5, 0.57)  # where the real mouse rests before the first move
HOLD_ACTIONS = (
    "click",
    "dblclick",
    "right_click",
    "type",
    "upload",
    "hover",
    "scroll_to",
    "highlight",
)

INIT_JS = """
(() => {
  const css = '*, *::before, *::after { cursor: none !important; }';
  const addStyle = () => {
    const s = document.createElement('style');
    s.textContent = css;
    (document.head || document.documentElement).appendChild(s);
  };
  window.__activity = [];
  const note = () => {
    const now = Date.now(), a = window.__activity;
    if (!a.length || now - a[a.length - 1] > 80) a.push(now);
  };
  const start = () => {
    addStyle();
    new MutationObserver(note).observe(document.documentElement, {
      subtree: true, childList: true, attributes: true, characterData: true,
    });
  };
  if (document.documentElement) start();
  else document.addEventListener('readystatechange', start, { once: true });
})();
"""

SCROLL_TO_JS = """
([y, ms]) => new Promise((resolve) => {
  const from = scrollY, t0 = performance.now();
  const ease = (u) => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2);
  const step = (t) => {
    const u = Math.min(1, (t - t0) / ms);
    scrollTo(0, from + (y - from) * ease(u));
    if (u < 1) requestAnimationFrame(step); else resolve(scrollY);
  };
  requestAnimationFrame(step);
})
"""

CENTER_TOP_JS = """
(el) => {
  const r = el.getBoundingClientRect();
  return Math.max(0, Math.round(r.top + scrollY - innerHeight / 2 + r.height / 2));
}
"""

HIGHLIGHT_ON_JS = """
([box, color]) => {
  const id = '__hl_overlay';
  document.getElementById(id)?.remove();
  const style = document.createElement('style');
  style.id = id + '_style';
  style.textContent = '@keyframes __hl_pulse { ' +
    `0%,100% { box-shadow: 0 0 14px ${color}99, 0 0 0 0 ${color}55; } ` +
    `50% { box-shadow: 0 0 30px ${color}cc, 0 0 0 10px ${color}00; } }`;
  document.head.appendChild(style);
  const d = document.createElement('div');
  d.id = id;
  const pad = 8;
  Object.assign(d.style, {
    position: 'fixed', left: box.x - pad + 'px', top: box.y - pad + 'px',
    width: box.width + 2 * pad + 'px', height: box.height + 2 * pad + 'px',
    border: `3px solid ${color}`, borderRadius: '12px', pointerEvents: 'none', zIndex: 2147483647,
    animation: '__hl_pulse 0.9s ease-in-out infinite',
  });
  document.body.appendChild(d);
}
"""

HIGHLIGHT_OFF_JS = """
() => {
  document.getElementById('__hl_overlay')?.remove();
  document.getElementById('__hl_overlay_style')?.remove();
}
"""

# visible things near a point that are safe candidates for a harmless hover
NEARBY_JS = """
([px, py]) => {
  const sel = 'a[href], button, [role=button], [role=tab], li, label, h2, h3, td, summary';
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (r.width < 24 || r.height < 14 || r.bottom < 0 || r.right < 0) continue;
    if (r.top > innerHeight - 10 || r.left > innerWidth - 10) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    out.push({
      x, y, w: r.width, h: r.height, d: Math.hypot(x - px, y - py),
      texts: [el.innerText, el.getAttribute('aria-label'), el.getAttribute('title')]
        .map((t) => (t || '').trim()),
      href: el.getAttribute('href'),
    });
  }
  return out.sort((a, b) => a.d - b.d).slice(0, 14);
}
"""

SCROLLABLE_JS = "() => document.documentElement.scrollHeight - innerHeight"

# the main content of a section: a heading and what sits right below it (not the whole,
# often viewport-tall, section); any other element: its card / list item
CONTENT_BLOCK_JS = """
(el) => {
  const vw = innerWidth, vh = innerHeight;
  const rect = (e) => e.getBoundingClientRect();
  // the extent of the text itself: a block-level heading spans the page, its words do not
  const tight = (e) => {
    const g = document.createRange();
    g.selectNodeContents(e);
    const r = g.getBoundingClientRect();
    return r.width > 0 && r.height > 0 ? r : rect(e);
  };
  const isHeading = (e) => /^H[1-6]$/.test(e.tagName);
  const level = (e) => +e.tagName[1];
  const boxes = [tight(el)];
  if (isHeading(el)) {
    const limit = rect(el).bottom + 360;
    let node = el;
    while (node.parentElement && !node.nextElementSibling && node.parentElement !== document.body
           && rect(node.parentElement).height < vh * 0.9) node = node.parentElement;
    const stops = (e) => (isHeading(e) && level(e) <= level(el)) ||
      [...e.querySelectorAll('h1,h2,h3,h4,h5,h6')].some((h) => level(h) <= level(el));
    for (let sib = node.nextElementSibling; sib && boxes.length < 6; sib = sib.nextElementSibling) {
      const r = rect(sib);
      if (r.height === 0 || getComputedStyle(sib).display === 'none') continue;
      if (stops(sib) || r.top > limit) break;
      const t = tight(sib);
      boxes.push({ left: t.left, right: t.right, top: r.top, bottom: Math.min(r.bottom, limit) });
    }
  } else {
    const tags = new Set(['LI', 'ARTICLE', 'FIGURE', 'TR', 'FORM']);
    for (let e = el.parentElement; e && e !== document.body; e = e.parentElement) {
      const r = rect(e);
      if (r.height > vh * 0.6 || r.width > vw * 0.9) break;
      if (tags.has(e.tagName) || e.getAttribute('role') === 'listitem') { boxes[0] = r; break; }
    }
  }
  const x0 = Math.max(0, Math.min(...boxes.map((b) => b.left)));
  const y0 = Math.max(0, Math.min(...boxes.map((b) => b.top)));
  const x1 = Math.min(vw, Math.max(...boxes.map((b) => b.right)));
  const y1 = Math.min(vh, Math.max(...boxes.map((b) => b.bottom)));
  return x1 - x0 > 8 && y1 - y0 > 8 ? { x: x0, y: y0, width: x1 - x0, height: y1 - y0 } : null;
}
"""


@dataclass
class RecordResult:
    kind: str  # recording | screenshot | fallback_screenshot
    clip_path: Path | None = None
    image_path: Path | None = None
    start_offset_ms: int = 0  # the page was loading until here
    setup_end_ms: int = 0  # setup steps are done here (== start_offset_ms without setup)
    click_log: list[dict[str, Any]] = field(default_factory=list)
    # camera targets: {t_ms, bbox: {x, y, w, h} in clip pixels, kind, hold_ms}
    focus_log: list[dict[str, Any]] = field(default_factory=list)
    # frame_inventory: [{t_ms, items: [{id, role, tag, text, bbox, kind, is_new, region}]}]
    inventory: list[dict[str, Any]] = field(default_factory=list)
    # what was done: [{t_ms, end_ms, do, target_text, item_id}], times on the clip axis
    action_log: list[dict[str, Any]] = field(default_factory=list)
    width: int = 0  # clip size in pixels (the capture viewport)
    height: int = 0
    content_ms: int = 0  # length of the clip
    idle_gaps_ms: list[int] = field(default_factory=list)  # gaps of >= 0.5 s with nothing happening
    warnings: list[str] = field(default_factory=list)
    steps_ok: int = 0
    steps_failed: int = 0
    filled_ms: int = 0  # time spent on the filler hovers
    activity_ms: list[float] = field(default_factory=list)  # clip times where anything happened


class _Recorder:
    def __init__(
        self,
        session: BrowserSession,
        page: Page,
        root_url: str,
        out_dir: Path,
        scene_id: str,
        *,
        color: str,
        policy: Policy,
        rng: random.Random,
        viewport: dict[str, int],
    ) -> None:
        self.session, self.page, self.root_url, self.out_dir = session, page, root_url, out_dir
        self.scene_id, self.color, self.policy, self.rng = scene_id, color, policy, rng
        self.vw, self.vh = viewport["width"], viewport["height"]
        self.t0 = time.time()
        self.log: list[dict[str, Any]] = []
        self.focus_log: list[dict[str, Any]] = []
        self.inventory: list[dict[str, Any]] = []
        self.action_log: list[dict[str, Any]] = []
        self.last_handle: Any = None  # element of the latest action: always in the inventory
        self.last_snap = -INVENTORY_EVERY_MS
        self.warnings: list[str] = []
        self.typed: set[str] = set()
        self.mouse = self.home
        self.holding = True
        self.activity: list[float] = []  # page changes seen so far, wall-clock ms
        self.marks: list[int] = []  # clip times where the cursor moved, text was typed, ...
        self.hover_boxes: list[
            dict[str, float]
        ] = []  # boxes of the slow hovers since the last outline
        self.pointed = 0  # showcase_lite: elements hovered or outlined
        self.ok = self.failed = 0

    # --- clock ----------------------------------------------------------------------------

    def now(self) -> int:
        return round((time.time() - self.t0) * 1000)

    def mark(self) -> None:
        """Something is visibly moving right now (cursor, typing, scrolling): not an idle moment."""
        self.marks.append(self.now())

    @property
    def home(self) -> tuple[float, float]:
        return (self.vw * HOME_FRACTION[0], self.vh * HOME_FRACTION[1])

    def event(self, kind: str, x: float, y: float) -> None:
        self.log.append({"t_ms": self.now(), "x": round(x), "y": round(y), "type": kind})

    def focus(self, kind: str, box: dict[str, float] | None, hold_ms: int = 0) -> None:
        """Remember a box the camera should frame (clip pixels), clipped to the viewport."""
        if not box:
            return
        x0, y0 = max(0.0, box["x"]), max(0.0, box["y"])
        x1 = min(float(self.vw), box["x"] + box["width"])
        y1 = min(float(self.vh), box["y"] + box["height"])
        if x1 - x0 < 4 or y1 - y0 < 4:
            return
        self.focus_log.append(
            {
                "t_ms": self.now(),
                "bbox": {"x": round(x0), "y": round(y0), "w": round(x1 - x0), "h": round(y1 - y0)},
                "kind": kind,
                "hold_ms": hold_ms,
            }
        )

    def snap(self) -> None:
        """One frame_inventory snapshot of what is on screen now."""
        self.last_snap = self.now()
        items = inventory.snapshot(self.page, self.last_handle)
        if items:
            self.inventory.append({"t_ms": self.last_snap, "items": items})

    def snap_every(self, ms: int = INVENTORY_EVERY_MS) -> None:
        if self.now() - self.last_snap >= ms:
            self.snap()

    def note_action(self, do: str, target: Target | None) -> None:
        """Log what is being done and to which element (its inventory id)."""
        handle, text = None, ""
        if target is not None:
            try:
                handle = target.handle()
                text = (target.info().text or "")[:80]
            except Exception:
                pass
        self.last_handle = handle
        item_id = inventory.element_id(self.page, handle) if handle is not None else None
        now = self.now()
        self.action_log.append(
            {"t_ms": now, "end_ms": now, "do": do, "target_text": text, "item_id": item_id}
        )

    def content_block_of(self, target: Target) -> dict[str, float] | None:
        """What to frame for a section: its heading and the content right below it."""
        try:
            return self.page.evaluate(CONTENT_BLOCK_JS, target.handle()) or target.box()
        except Exception:
            return target.box()

    def collect_activity(self) -> None:
        """Page changes live in the page: read them before a navigation throws them away."""
        try:
            self.activity += [float(a) for a in self.page.evaluate("window.__activity || []")]
        except Exception:
            pass

    # --- primitives -----------------------------------------------------------------------

    def move_to(self, x: float, y: float, ms: int | None = None) -> None:
        sx, sy = self.mouse
        duration = ms or motion.move_duration_ms(hypot(x - sx, y - sy))
        for i, (px, py, wait) in enumerate(motion.mouse_path((sx, sy), (x, y), duration)):
            began = time.monotonic()
            self.page.mouse.move(px, py)
            if i % 8 == 0:
                self.mark()
            if ms:  # a requested duration is wall-clock: the move call itself already took time
                wait = max(0.0, wait - (time.monotonic() - began) * 1000)
            self.page.wait_for_timeout(wait)
        self.mouse = (x, y)

    def settle(self) -> None:
        wait_for_settle(self.page)

    def target_of(self, spec: LocatorSpec | None, label: str) -> Target:
        if spec is None:
            raise RuntimeError(f"{label}: no locator")
        found = resolve(self.page, spec)
        if found.target is None:
            raise RuntimeError(f"{label}: element not found ({'; '.join(found.tried)[:160]})")
        return found.target

    def center_of(self, target: Target) -> tuple[float, float]:
        box = target.box()
        if box is None or box["y"] < 0 or box["y"] + box["height"] > self.vh:
            target.scroll_into_view_if_needed()
            self.page.wait_for_timeout(250)
            box = target.box()
        if box is None:
            raise RuntimeError("element has no box")
        return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

    def safe(self, target: Target) -> None:
        info = target.info()
        check_clickable(info, self.root_url, scope_prefix=None, ignore_texts=self.typed)

    # --- actions --------------------------------------------------------------------------

    def run(self, action: Any, label: str) -> None:
        do = action.do
        handler = getattr(self, f"do_{do}", None)
        if handler is None:
            raise RuntimeError(f"unsupported action {do}")
        before = len(self.focus_log)
        acted = len(self.action_log)
        self.last_handle = None
        inventory.mark_baseline(self.page)
        handler(action, label)
        if len(self.action_log) > acted:
            self.action_log[-1]["end_ms"] = self.now()
        self.settle()
        self.snap()
        self.hold(action, before)

    def hold(self, a: Any, focus_before: int) -> None:
        """Stay on the result of a main action, and record how long so the camera can stay too.

        Slow pointing hovers and highlights already wait as long as they were asked to."""
        if a.do not in HOLD_ACTIONS or not self.holding:
            return
        own = a.ms if a.do in ("hover", "highlight") and a.ms else 0
        if not own:
            for waited in range(0, HOLD_MS, INVENTORY_EVERY_MS):  # snapshot about once a second
                self.page.wait_for_timeout(min(INVENTORY_EVERY_MS, HOLD_MS - waited))
                if waited + INVENTORY_EVERY_MS < HOLD_MS:
                    self.snap()
        if len(self.focus_log) > focus_before:
            self.focus_log[-1]["hold_ms"] = own or HOLD_MS

    def do_goto(self, a: Any, label: str) -> None:
        self.collect_activity()
        self.page.goto(a.url, wait_until="domcontentloaded")
        self.settle()
        dismiss_cookie_banner(self.page)

    def do_wait(self, a: Any, label: str) -> None:
        self.page.wait_for_timeout(a.ms or 800)

    def _pointer_action(self, a: Any, label: str, kind: str) -> None:
        target = self.target_of(a.locator, label)
        self.safe(target)
        x, y = self.center_of(target)
        slow = kind == "hover" and bool(a.ms)  # showcase_lite: a slow, deliberate hover
        self.note_action(kind, target)
        self.move_to(x, y, self.rng.randint(900, 1200) if slow else None)
        self.event(kind, x, y)
        self.focus(kind, target.box())
        if kind == "click":
            target.click()
        elif kind == "dblclick":
            target.dblclick()
        else:
            target.hover()
            self.page.wait_for_timeout(a.ms if slow and a.ms else 600)
            if slow:
                box = target.box()
                if box:
                    self.hover_boxes.append(box)
                    self.pointed += 1

    def do_click(self, a: Any, label: str) -> None:
        self._pointer_action(a, label, "click")

    def do_dblclick(self, a: Any, label: str) -> None:
        self._pointer_action(a, label, "dblclick")

    def do_hover(self, a: Any, label: str) -> None:
        self._pointer_action(a, label, "hover")

    def do_right_click(self, a: Any, label: str) -> None:
        target = self.target_of(a.locator, label)
        self.safe(target)
        x, y = self.center_of(target)
        self.note_action("right_click", target)
        self.move_to(x, y)
        self.event("click", x, y)
        self.focus("click", target.box())
        target.right_click()

    def do_type(self, a: Any, label: str) -> None:
        target = self.target_of(a.locator, label)
        info = target.info()
        if not info.is_text_input:
            raise RuntimeError(f"{label}: not a text field")
        x, y = self.center_of(target)
        self.note_action("type", target)
        self.move_to(x, y)
        self.event("click", x, y)
        self.focus("type", target.box())
        target.click()
        text = a.text or ""
        target.fill("")
        for ch, delay in zip(text, motion.typing_delays(text, self.rng), strict=True):
            self.mark()
            self.page.keyboard.type(ch)
            self.page.wait_for_timeout(delay)
        if text:
            self.typed.add(text.strip().lower())
        allowed, _ = enter_decision(
            info, self.page.url, guard_on=not self.session.guard.allow_mutations, policy=self.policy
        )
        if allowed:
            self.page.wait_for_timeout(250)
            self.page.keyboard.press("Enter")

    def do_scroll(self, a: Any, label: str) -> None:
        self.note_action("scroll", None)
        self.event("scroll", self.mouse[0], self.mouse[1])
        self.wheel(a.ms or 700)

    def wheel(self, total: float) -> None:
        """Scroll by `total` px in eased steps, logging the centre block every FOCUS_SAMPLE_MS."""
        last = self.now()
        for dy in motion.scroll_steps(total):
            self.mark()
            self.page.mouse.wheel(0, dy)
            self.page.wait_for_timeout(40)
            if self.now() - last >= FOCUS_SAMPLE_MS:
                last = self.now()
                self.snap_every()

    def _scroll_center(self, target: Target) -> tuple[float, float]:
        handle = target.handle()
        y = self.page.evaluate(CENTER_TOP_JS, handle)
        self.mark()
        self.page.evaluate(SCROLL_TO_JS, [y, 700])
        self.mark()
        self.page.wait_for_timeout(150)
        box = target.box()
        if box is None:
            raise RuntimeError("element has no box")
        return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

    def do_scroll_to(self, a: Any, label: str) -> None:
        target = self.target_of(a.locator, label)
        self.note_action("scroll_to", target)
        self.event("scroll", self.mouse[0], self.mouse[1])
        self._scroll_center(target)
        self.focus("section", self.content_block_of(target))

    def do_highlight(self, a: Any, label: str) -> None:
        group = a.text == GROUP and self.hover_boxes
        if group:  # outline the area that holds every element hovered just before
            box = union_box(self.hover_boxes)
            self.hover_boxes = []
        else:
            target = self.target_of(a.locator, label)
            box = target.box()
            if box is None or box["y"] < 0 or box["y"] + box["height"] > self.vh:
                self._scroll_center(target)
                box = target.box()
        if box is None:
            raise RuntimeError(f"{label}: element has no box")
        self.pointed += 1
        self.note_action("highlight", None if group else target)
        self.page.evaluate(HIGHLIGHT_ON_JS, [box, self.color])
        self.event("highlight", box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        self.focus("highlight", box if group else self.content_block_of(target))
        self.snap()
        self.page.wait_for_timeout(a.ms or 1800)
        self.page.evaluate(HIGHLIGHT_OFF_JS)

    def do_upload(self, a: Any, label: str) -> None:
        target = self.target_of(a.locator, label)
        info = target.info()
        name = a.file if a.file in CATALOG else pick_sample(info.file_accept, label)
        self.note_action("upload", target)
        handle = target.file_input()
        if handle is None:
            raise RuntimeError(f"{label}: not a file input")
        handle.set_input_files(str(sample_path(name)))

    # --- one step with error handling -------------------------------------------------------

    def step(self, action: Any, index: int, part: str) -> None:
        label = f"{part}[{index}] {action.do}"
        self.holding = part == "action"  # setup steps are only the means: no hold after them
        try:
            self.run(action, label)
            self.ok += 1
        except Unsafe as e:
            self.failed += 1
            self.warnings.append(f"{label}: bị chặn vì an toàn ({e})")
            self._snap_error(label)
        except Exception as e:
            self.failed += 1
            text = str(e).splitlines()[0][:200] if str(e) else type(e).__name__
            self.warnings.append(text if text.startswith(label) else f"{label}: {text}")
            self._snap_error(label)
            try:
                self.page.evaluate(HIGHLIGHT_OFF_JS)
            except Exception:
                pass

    def _snap_error(self, label: str) -> None:
        try:
            safe = "".join(c if c.isalnum() else "_" for c in label)
            path = self.out_dir / "errors" / f"{self.scene_id}_{safe}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(path))
        except Exception:
            pass

    # --- filling a quiet stretch ------------------------------------------------------------

    def fill(self, missing_ms: int) -> int:
        """Harmless hovers (and a little scroll) near where we last worked; returns ms spent."""
        started = self.now()
        px, py = self.mouse
        try:
            candidates = self.page.evaluate(NEARBY_JS, [px, py])
        except Exception:
            candidates = []
        safe = [
            c
            for c in candidates
            if not is_blocked(*c["texts"], strict=True, ignore=self.typed)
            and not is_blocked_href(c.get("href"))
        ]
        for c in safe[:MAX_FILL_HOVERS]:
            if self.now() - started >= missing_ms:
                break
            self.move_to(c["x"], c["y"], self.rng.randint(800, 1200))
            self.event("hover", c["x"], c["y"])  # filler: the camera does not follow it
            self.snap_every()
            self.page.wait_for_timeout(250)
        remaining = missing_ms - (self.now() - started)
        if remaining > 1200:
            try:
                room = self.page.evaluate(SCROLLABLE_JS)
            except Exception:
                room = 0
            if room > 200:
                self.event("scroll", self.mouse[0], self.mouse[1])
                self.wheel(min(320, room))
                self.page.wait_for_timeout(500)
                self.event("scroll", self.mouse[0], self.mouse[1])
                self.wheel(-min(320, room))
        return self.now() - started


def union_box(boxes: list[dict[str, float]]) -> dict[str, float]:
    """The smallest box that holds all the given boxes."""
    x0 = min(b["x"] for b in boxes)
    y0 = min(b["y"] for b in boxes)
    x1 = max(b["x"] + b["width"] for b in boxes)
    y1 = max(b["y"] + b["height"] for b in boxes)
    return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}


def to_mp4(webm: Path, mp4: Path) -> None:
    """webm (what Playwright records) -> h264 mp4, 30 fps, yuv420p, no audio."""
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(webm),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-r", "30", "-an", str(mp4),
        ],
        capture_output=True,
        text=True,
    )  # fmt: skip
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[:300]}")


def first_goto(actions: list[Any]) -> str | None:
    return next((a.url for a in actions if a.do == "goto" and a.url), None)


def record_scene(
    session: BrowserSession,
    scene: Scene,
    out_dir: Path,
    speech_ms: int,
    *,
    root_url: str,
    highlight_color: str = "#756eeb",
    enter_policy: Policy = "strict",
    seed: int | None = None,
    viewport: dict[str, int] | None = None,
) -> RecordResult:
    """Record (or photograph) one scene into out_dir; never raises for a failing step."""
    s = scene.root
    visual = s.visual
    viewport = viewport or CAPTURE
    out_dir.mkdir(parents=True, exist_ok=True)
    if visual.mode == "template":
        return RecordResult(kind="template")  # drawn by the renderer, nothing to capture
    if visual.mode != "recording":
        url = visual.page or root_url
        image = take_screenshot(session, url, out_dir / f"{s.id}.png", viewport)
        return RecordResult(kind="screenshot", image_path=image)

    rng = random.Random(seed if seed is not None else s.id)
    setup, actions = list(visual.setup), list(visual.actions)
    start_url = first_goto(setup) or first_goto(actions) or visual.page or root_url
    raw_dir = out_dir / "raw" / s.id
    raw_dir.mkdir(parents=True, exist_ok=True)
    context: BrowserContext = session.new_context(record_video_dir=raw_dir, viewport=viewport)
    context.add_init_script(INIT_JS)
    try:
        page = context.new_page()
        rec = _Recorder(
            session,
            page,
            root_url,
            out_dir,
            s.id,
            color=highlight_color,
            policy=enter_policy,
            rng=rng,
            viewport=viewport,
        )
        page.mouse.move(*rec.home)
        try:
            page.goto(start_url, wait_until="domcontentloaded")
            rec.settle()
            dismiss_cookie_banner(page)
            rec.settle()
        except Exception as e:
            rec.warnings.append(f"không mở được {start_url}: {type(e).__name__}")
        start_offset = rec.now()

        def pending(steps: list[Any]) -> list[tuple[int, Any]]:
            """(1-based position in the script, step); the opening goto was the page load above."""
            numbered = list(enumerate(steps, start=1))
            first = steps[0] if steps else None
            skip = first is not None and first.do == "goto" and first.url == start_url
            return numbered[1:] if skip else numbered

        for i, a in pending(setup):
            rec.step(a, i, "setup")
        setup_end = rec.now() if setup else start_offset
        todo = list(enumerate(actions, start=1)) if setup else pending(actions)
        for i, a in todo:
            rec.step(a, i, "action")

        shown_from = start_offset if (visual.show_setup or not setup) else setup_end
        usable = rec.now() - shown_from
        missing = speech_ms - usable
        filled = 0
        if missing > FILL_THRESHOLD_MS and rec.ok + rec.failed > 0:
            filled = rec.fill(missing)
        page.wait_for_timeout(TAIL_MS)
        rec.collect_activity()
        content_ms = rec.now()
        video = page.video
    finally:
        context.close()
    clip_path: Path | None = None
    if video is not None:
        webm = Path(video.path())
        clip_path = out_dir / f"{s.id}.mp4"
        to_mp4(webm, clip_path)

    warnings = list(rec.warnings)
    pointed_nothing = is_lite(visual) and rec.pointed == 0
    if (rec.ok == 0 or pointed_nothing) and (setup or actions):
        # nothing could be carried out: a photo of the page is better than an empty recording
        image = take_screenshot(session, start_url, out_dir / f"{s.id}.png", viewport)
        warnings.append("không bước nào chạy được, dùng ảnh trang đích thay cho clip")
        return RecordResult(
            kind="fallback_screenshot", image_path=image, warnings=warnings, steps_failed=rec.failed
        )
    activity = [t - rec.t0 * 1000 for t in rec.activity] + [e["t_ms"] for e in rec.log] + rec.marks
    gaps = motion.idle_gaps(activity, shown_from, content_ms)
    return RecordResult(
        kind="recording",
        clip_path=clip_path,
        start_offset_ms=start_offset,
        setup_end_ms=setup_end,
        click_log=rec.log,
        focus_log=rec.focus_log,
        inventory=rec.inventory,
        action_log=rec.action_log,
        width=viewport["width"],
        height=viewport["height"],
        content_ms=content_ms,
        idle_gaps_ms=gaps,
        activity_ms=activity,
        warnings=warnings,
        steps_ok=rec.ok,
        steps_failed=rec.failed,
        filled_ms=filled,
    )
