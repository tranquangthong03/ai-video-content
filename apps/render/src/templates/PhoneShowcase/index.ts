import type React from "react";
import type { LayoutOf } from "../../generated/layouts";
import { BeforeAfterSplit } from "./BeforeAfterSplit";
import { BeforeAfterSwipe } from "./BeforeAfterSwipe";
import { CtaButtonPulse } from "./CtaButtonPulse";
import { CtaLogo } from "./CtaLogo";
import { DemoFull } from "./DemoFull";
import { DemoPhone } from "./DemoPhone";
import { FallbackScene } from "./FallbackScene";
import { HookBigText } from "./HookBigText";
import { HookEmoji } from "./HookEmoji";
import type { SceneProps, SceneType } from "./types";

/**
 * scene type -> layout -> component. Keyed by the generated LayoutOf<T>, so adding a layout to
 * scene.json makes this table fail to compile until a component is registered.
 */
export type SceneTable = {
  [T in SceneType]: Record<LayoutOf<T>, React.FC<SceneProps<T>>>;
};

export const SCENES: SceneTable = {
  hook: { big_text_over_blur: HookBigText, emoji_pop: HookEmoji },
  feature_demo: { full_screen: DemoFull, phone_mockup: DemoPhone },
  before_after: { split_vertical: BeforeAfterSplit, swipe: BeforeAfterSwipe },
  cta: { logo_center: CtaLogo, button_pulse: CtaButtonPulse },
};

/** Component for a scene; FallbackScene when the type/layout pair is not registered. */
export type AnySceneComponent = React.FC<SceneProps>;

export function resolveScene(type: string, layout: string): AnySceneComponent {
  // Runtime lookup by arbitrary strings: the typed table is deliberately widened here
  const table = SCENES as unknown as Record<string, Record<string, AnySceneComponent> | undefined>;
  return table[type]?.[layout] ?? (FallbackScene as unknown as AnySceneComponent);
}

export { FallbackScene };
