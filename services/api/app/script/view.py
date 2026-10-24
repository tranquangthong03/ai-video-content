"""How a script is shown to the user in script_review (rich markup lines, no I/O)."""

from rich.markup import escape

from app.media.timing import estimate_speech_ms
from app.schemas.generated.script import Script
from app.script.diff import THEME_LABELS
from app.script.fit_duration import FitReport
from app.script.theme import highlight_color

KIND_RECORD, KIND_SCROLL, KIND_PHOTO, KIND_TEXT = (
    "quay thao tác",
    "cuộn-highlight",
    "ảnh",
    "chữ",
)
SOURCE_LABELS = {
    "meta": "thẻ theme-color",
    "css": "màu nút/liên kết trên trang",
    "screenshot": "màu nổi bật trong ảnh trang chủ",
    "fallback": "màu mặc định",
}


def scene_kind(scene_root) -> str:  # type: ignore[no-untyped-def]
    """What the camera shows: operations, a scroll + highlight, a photo or just text."""
    visual = scene_root.visual
    if visual.mode == "recording":
        if any(a.do == "highlight" for a in visual.actions):
            return KIND_SCROLL
        return KIND_RECORD
    if visual.mode == "screenshot":
        return KIND_PHOTO
    return KIND_TEXT


def headline_markup(script: Script) -> str:
    text = script.headline
    mark = script.headline_highlight
    if mark and mark in text:
        before, _, after = text.partition(mark)
        color = highlight_color(script.theme.primary)
        return f"{escape(before)}[bold {color}]{escape(mark)}[/]{escape(after)}"
    return escape(text)


def scene_lines(script: Script) -> list[str]:
    lines = []
    for n, scene in enumerate(script.scenes, start=1):
        s = scene.root
        seconds = estimate_speech_ms(s.voiceover) / 1000
        key = escape(s.key_point or "—")
        kind = escape(f"[{scene_kind(s)}]")
        lines.append(f"  {n}. {s.id} {s.type:<12} {kind:<18} {key} · {seconds:.1f}s")
    return lines


def one_liners(script: Script) -> list[dict[str, str]]:
    """One line per scene for InteractionRequest.summary (plain text)."""
    out = []
    for s in (x.root for x in script.scenes):
        seconds = estimate_speech_ms(s.voiceover) / 1000
        out.append(
            {
                "scene_id": s.id,
                "one_liner": f"{s.type} [{scene_kind(s)}] {s.key_point or '—'} · {seconds:.1f}s",
            }
        )
    return out


def render_script(
    script: Script,
    fit: FitReport | None,
    theme_report: dict | None,
    version: int,  # type: ignore[type-arg]
) -> list[str]:
    primary = script.theme.primary
    lines = [f"[bold]Kịch bản v{version}[/]  ·  {escape(script.title)}"]
    badge = f"\\[{escape(script.badge)}] " if script.badge else ""
    lines.append(f"  {badge}{headline_markup(script)}")
    source = SOURCE_LABELS.get((theme_report or {}).get("source", ""), "")
    lines.append(
        f"  {THEME_LABELS['primary']}: [on {primary}]    [/] {primary}"
        + (f" ({source})" if source else "")
        + f"  ·  {THEME_LABELS['accent']}: [on {script.theme.accent}]    [/] {script.theme.accent}"
        + "   [dim](đổi: «đổi màu chủ đạo thành #RRGGBB»)[/]"
    )
    lines += scene_lines(script)
    if fit is not None:
        mark = "[green]✓[/]" if fit.within else "[yellow]![/]"
        lines.append(
            f"  {mark} Ước tính {fit.estimated_ms / 1000:.1f}s / "
            f"mục tiêu {fit.target_ms / 1000:.0f}s ({fit.deviation * 100:+.0f}%)"
        )
    return lines
