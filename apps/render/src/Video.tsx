import React from "react";
import { InputPropsSchema, type InputPropsInput } from "./props";
import { DesktopFrameVideo } from "./templates/DesktopFrame/DesktopFrameVideo";
import { DesktopFocusVideo } from "./templates/DesktopFocus/DesktopFocusVideo";
import { DesktopVideo } from "./templates/DesktopShowcase/DesktopVideo";
import { PhoneVideo } from "./templates/PhoneShowcase/PhoneVideo";
import { ThemeProvider } from "./theme/ThemeProvider";

/** Picks the template from script.template; all share the theme provider (fonts, colors, motion). */
export const Video: React.FC<InputPropsInput> = (raw) => {
  const props = InputPropsSchema.parse(raw);
  const Template =
    props.script.template === "phone_showcase"
      ? PhoneVideo
      : props.script.template === "desktop_showcase"
        ? DesktopVideo
        : props.script.template === "desktop_focus"
          ? DesktopFocusVideo
          : DesktopFrameVideo;
  return (
    <ThemeProvider theme={props.script.theme}>
      <Template {...props} />
    </ThemeProvider>
  );
};
