"""What a scene may contain: catalog sent to the LLM and the limits every scene must respect."""

import json
from typing import Any, get_args

from app.schemas.generated.layouts import LAYOUTS_BY_TYPE
from app.schemas.generated.scene import HookScene
from app.schemas.generated.scene_meta import FIELDS_BY_TYPE

SCENE_TYPES = ("hook", "feature_demo", "before_after", "cta")
DEMOABLE = ("interaction", "navigation", "showcase")  # demo_kind values usable in a feature_demo

BADGE_MAX = 24
HEADLINE_MAX = 40
KEY_POINT_MAX = 60
ON_SCREEN_MAX_WORDS = 5
HOOK_MAX_WORDS = 12
HOOK_KINDS = ("pain_question", "result_first", "shocking_number", "counterintuitive",
              "you_are_doing_it_wrong")  # fmt: skip
# empty marketing phrases the writer may not use (compared without accents, lower case)
FORBIDDEN_PHRASES = ("giải pháp toàn diện", "tối ưu hóa trải nghiệm", "nâng tầm", "đột phá",
                     "hoàn hảo")  # fmt: skip
STAT_VALUE_MAX, STAT_LABEL_MAX = 12, 30
# the before/after of a flow video is a card of about three seconds on two real screens
BEFORE_AFTER_FLOW_MIN_WORDS, BEFORE_AFTER_FLOW_MAX_WORDS = 4, 7
BEFORE_AFTER_FLOW_LABEL_WORDS = 3
BEFORE_AFTER_FLOW_LAYOUT = "split_frames"
BEFORE_AFTER_MAX_WORDS = 6
VOICEOVER_MIN_WORDS = 8
VOICEOVER_MAX_WORDS = 30
DEMO_VOICEOVER_MAX_WORDS = 30
# when the user insists on a video longer than the product can fill (core/budget.py)
FORCED_DEMO_MAX_WORDS = 35
FORCED_OTHER_MAX_WORDS = 20  # hook / cta may be lengthened up to this by the duration fit


def _icons() -> tuple[str, ...]:
    """The icon names scene.json allows, read from the generated model (never hardcoded)."""
    annotation = HookScene.model_fields["icon"].annotation
    names: list[str] = []
    for arg in get_args(annotation):
        if arg is type(None):
            continue
        names += [a for a in get_args(arg) if isinstance(a, str)] or (
            [arg] if isinstance(arg, str) else []
        )
    return tuple(names)


ICONS: tuple[str, ...] = _icons()

# fields the writer sets itself; the rest of FIELDS_BY_TYPE is filled by code (visual, duration_ms)
WRITER_FIELDS = (
    "id", "type", "layout", "feature", "before_text", "after_text", "voiceover",
    "on_screen_text", "key_point", "icon", "stat",
)  # fmt: skip


def scene_catalog() -> dict[str, Any]:
    """{type: {layouts, fields}} for the prompt, from the generated tables."""
    return {
        t: {
            "layouts": list(LAYOUTS_BY_TYPE[t]),
            "fields": [f for f in FIELDS_BY_TYPE[t] if f in WRITER_FIELDS],
            "visual": 'luôn đặt visual = {"mode": "auto"}; hệ thống tự điền',
        }
        for t in SCENE_TYPES
    }


def scene_catalog_json() -> str:
    return json.dumps(scene_catalog(), ensure_ascii=False, indent=1)


def word_count(text: str | None) -> int:
    return len((text or "").split())
