import React from "react";
import { Composition, staticFile } from "remotion";
import { DURATION, FPS, Hipparchus, Props } from "./hipparchus";

const fallback: Props = { frontier: { image: "", caption: "", label: "CONCEPT — FUTURE RESEARCH" } };

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Hipparchus29"
    component={Hipparchus}
    durationInFrames={DURATION}
    fps={FPS}
    width={1920}
    height={1080}
    defaultProps={fallback}
    // The frontier scene is data-driven: public/frontier.json is read at render time,
    // unless --props already supplies a "frontier" object.
    calculateMetadata={async ({ props }) => {
      if (props.frontier.caption) return { props };
      const res = await fetch(staticFile("frontier.json"));
      return { props: { ...props, frontier: { ...props.frontier, ...(await res.json()) } } };
    }}
  />
);
