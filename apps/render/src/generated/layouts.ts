// AUTO-GENERATED — DO NOT EDIT. Run 'make codegen'.

export const LAYOUTS_BY_TYPE = {
  "hook": [
    "big_text_over_blur",
    "emoji_pop"
  ],
  "feature_demo": [
    "full_screen",
    "phone_mockup"
  ],
  "before_after": [
    "split_vertical",
    "swipe"
  ],
  "cta": [
    "logo_center",
    "button_pulse"
  ]
} as const;

export const FIELDS_BY_TYPE = {
  "hook": [
    "id",
    "type",
    "layout",
    "voiceover",
    "on_screen_text",
    "key_point",
    "icon",
    "visual",
    "duration_ms"
  ],
  "feature_demo": [
    "id",
    "type",
    "layout",
    "feature",
    "voiceover",
    "on_screen_text",
    "key_point",
    "icon",
    "visual",
    "duration_ms"
  ],
  "before_after": [
    "id",
    "type",
    "layout",
    "before_text",
    "after_text",
    "voiceover",
    "on_screen_text",
    "key_point",
    "icon",
    "visual",
    "duration_ms"
  ],
  "cta": [
    "id",
    "type",
    "layout",
    "voiceover",
    "on_screen_text",
    "key_point",
    "icon",
    "visual",
    "duration_ms"
  ]
} as const;

export type SceneType = keyof typeof LAYOUTS_BY_TYPE;
export type LayoutOf<T extends SceneType> = (typeof LAYOUTS_BY_TYPE)[T][number];
