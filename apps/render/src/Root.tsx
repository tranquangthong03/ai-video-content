import React from "react";
import { Composition } from "remotion";
import sampleScript from "../../../packages/script-schema/examples/sample_script.json";
import { COMPOSITION_ID } from "./compositionId";
import { buildSampleProps } from "./dev/sampleProps";
import { ScriptSchema } from "./generated";
import { InputPropsSchema, type InputPropsInput } from "./props";
import { FPS, HEIGHT, WIDTH, totalFrames } from "./timing";
import { Video } from "./Video";


const defaultProps = buildSampleProps(ScriptSchema.parse(sampleScript));

export const Root: React.FC = () => (
  <Composition
    id={COMPOSITION_ID}
    component={Video}
    width={WIDTH}
    height={HEIGHT}
    fps={FPS}
    durationInFrames={totalFrames(ScriptSchema.parse(sampleScript), FPS)}
    defaultProps={defaultProps}
    calculateMetadata={({ props }) => ({
      durationInFrames: totalFrames(InputPropsSchema.parse(props as InputPropsInput).script, FPS),
    })}
  />
);
