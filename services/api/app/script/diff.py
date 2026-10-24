"""What changed between two scripts, as Vietnamese sentences for the user."""

from typing import Any

from app.schemas.generated.script import Script

SCENE_LABELS = {
    "voiceover": "lời đọc",
    "on_screen_text": "chữ trên màn hình",
    "key_point": "ý chính",
    "icon": "icon",
    "layout": "bố cục",
    "feature": "tính năng",
    "before_text": "chữ «trước»",
    "after_text": "chữ «sau»",
}
SCRIPT_LABELS = {
    "headline": "tiêu đề",
    "headline_highlight": "cụm nhấn",
    "badge": "huy hiệu",
    "title": "tên video",
}
THEME_LABELS = {
    "primary": "màu chủ đạo",
    "accent": "màu nhấn",
    "motion_preset": "kiểu chuyển động",
    "caption_style": "kiểu phụ đề",
    "music_mood": "nhạc nền",
    "voice_id": "giọng đọc",
}


def _show(value: Any) -> str:
    return "—" if value in (None, "") else str(value)


def _visual_change(old: dict[str, Any], new: dict[str, Any]) -> str | None:
    if old == new:
        return None
    if old["mode"] != new["mode"]:
        return f"cách quay {old['mode']} → {new['mode']}"
    if old["show_setup"] != new["show_setup"]:
        return "hiện phần chuẩn bị" if new["show_setup"] else "ẩn phần chuẩn bị"
    return f"thao tác quay ({len(old['actions'])} → {len(new['actions'])} bước)"


def diff_scripts(old: Script, new: Script) -> list[str]:
    """Differences old -> new; empty when they are identical."""
    out: list[str] = []
    a, b = old.model_dump(), new.model_dump()
    for key, label in SCRIPT_LABELS.items():
        if a[key] != b[key]:
            out.append(f"Đổi {label}: «{_show(a[key])}» → «{_show(b[key])}»")
    for key, label in THEME_LABELS.items():
        if a["theme"][key] != b["theme"][key]:
            out.append(f"Đổi {label}: {a['theme'][key]} → {b['theme'][key]}")

    old_scenes = {s["id"]: s for s in a["scenes"]}
    new_scenes = {s["id"]: s for s in b["scenes"]}
    for sid, s in old_scenes.items():
        if sid not in new_scenes:
            out.append(f"Xóa scene {sid} ({s['type']}): «{s['voiceover']}»")
    for sid, s in new_scenes.items():
        if sid not in old_scenes:
            out.append(f"Thêm scene {sid} ({s['type']}): «{s['voiceover']}»")
    for sid, s in new_scenes.items():
        before = old_scenes.get(sid)
        if before is None:
            continue
        for key, label in SCENE_LABELS.items():
            if before.get(key) != s.get(key):
                out.append(
                    f"Scene {sid}: đổi {label} «{_show(before.get(key))}» → «{_show(s.get(key))}»"
                )
        visual = _visual_change(before["visual"], s["visual"])
        if visual:
            out.append(f"Scene {sid}: đổi {visual}")
    common_old = [i for i in old_scenes if i in new_scenes]
    common_new = [i for i in new_scenes if i in old_scenes]
    if common_old != common_new:
        out.append("Đổi thứ tự các scene: " + " → ".join(new_scenes))
    return out
