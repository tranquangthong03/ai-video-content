import React from "react";
import { InputPropsSchema, type InputPropsInput } from "./props";
import { DesktopVideo } from "./templates/DesktopShowcase/DesktopVideo";
import { PhoneVideo } from "./templates/PhoneShowcase/PhoneVideo";
import { ThemeProvider } from "./theme/ThemeProvider";

/** Picks the template from script.template; both share the theme provider (fonts, colors, motion). */
export const Video: React.FC<InputPropsInput> = (raw) => {
  const props = InputPropsSchema.parse(raw);
  const Template = props.script.template === "phone_showcase" ? PhoneVideo : DesktopVideo;
  return (
    <ThemeProvider theme={props.script.theme}>
      <Template {...props} />
    </ThemeProvider>
  );
};
