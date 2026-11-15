/*
 * HIPPARCHUS · extended scientific film (80.8 s, 1920x1080, 30 fps). Same parts as the 29.4 s
 * film (src/hipparchus.tsx), but every Manim scene plays in full and the method is shown step by
 * step: wavelength compatibility, WCS, aperture and PSF photometry, the real app, uncertainty,
 * robustness, refusal, the compatibility graph, the Kleopatra check and the simulated Planet X idea.
 * Render: ./scripts/build_cut.sh extended   (captions: src/captions_extended.ts)
 * Timeline generated from the clip lengths; each scene overlaps the next by 10 frames.
 * Ambient cut times (s): 5.8 11.8 17.6 23.6 29.3 37.0 44.6 51.7 58.5 64.9 71.3 77.4
 */
import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile } from "remotion";
import { Captions, SceneFade } from "./ui";
import { SceneAction, SceneIdentity, SceneManim } from "./scenes";
import { CUES_EXTENDED } from "./captions_extended";

export const EXTENDED_DURATION = 2424;

export const Extended: React.FC = () => (
  <AbsoluteFill style={{ background: "#000" }}>
    <Sequence name="m11" from={0} durationInFrames={183}>
      <SceneFade inF={1}><SceneManim src="manim/m11_change_real.mp4" headline="TWO REAL SPHEREx IMAGES, ONE YEAR APART" /></SceneFade>
    </Sequence>
    <Sequence name="m02" from={173} durationInFrames={192}>
      <SceneFade ><SceneManim src="manim/m02_filters.mp4" headline="A DIFFERENT WAVELENGTH CAN FAKE A CHANGE" /></SceneFade>
    </Sequence>
    <Sequence name="m12" from={355} durationInFrames={183}>
      <SceneFade ><SceneManim src="manim/m12_wcs.mp4" headline="FROM PIXELS TO THE SKY" /></SceneFade>
    </Sequence>
    <Sequence name="m03" from={528} durationInFrames={189}>
      <SceneFade ><SceneManim src="manim/m03_aperture.mp4" headline="MEASURING THE STAR" /></SceneFade>
    </Sequence>
    <Sequence name="m04" from={707} durationInFrames={183}>
      <SceneFade ><SceneManim src="manim/m04_epsf.mp4" headline="A SECOND, INDEPENDENT MEASUREMENT" /></SceneFade>
    </Sequence>
    <Sequence name="app" from={880} durationInFrames={240}>
      <SceneFade ><SceneAction /></SceneFade>
    </Sequence>
    <Sequence name="m13" from={1110} durationInFrames={237}>
      <SceneFade ><SceneManim src="manim/m13_uncertainty.mp4" headline="IS IT BIGGER THAN THE ERRORS?" /></SceneFade>
    </Sequence>
    <Sequence name="m05" from={1337} durationInFrames={225}>
      <SceneFade ><SceneManim src="manim/m05_fingerprint.mp4" headline="DOES IT SURVIVE EVERY ANALYSIS CHOICE?" /></SceneFade>
    </Sequence>
    <Sequence name="m14" from={1552} durationInFrames={213}>
      <SceneFade ><SceneManim src="manim/m14_barnard_refusal.mp4" headline="WHEN THE DATA CANNOT ANSWER, WE SAY SO" /></SceneFade>
    </Sequence>
    <Sequence name="m09" from={1755} durationInFrames={201}>
      <SceneFade ><SceneManim src="manim/m09_compat_graph.mp4" headline="WHICH EXPOSURES MAY BE COMPARED?" /></SceneFade>
    </Sequence>
    <Sequence name="m06" from={1946} durationInFrames={204}>
      <SceneFade ><SceneManim src="manim/m06_kleopatra.mp4" headline="FROM CHANGING STARS TO MOVING WORLDS" tag="KNOWN ASTEROID, NOT PLANET X" /></SceneFade>
    </Sequence>
    <Sequence name="m07" from={2140} durationInFrames={192}>
      <SceneFade ><SceneManim src="manim/m07_shift_stack.mp4" headline="THE PLANET X IDEA" /></SceneFade>
    </Sequence>
    <Sequence name="identity" from={2322} durationInFrames={102}>
      <SceneFade outF={1}><SceneIdentity /></SceneFade>
    </Sequence>
    <Captions cues={CUES_EXTENDED} />
    <Audio src={staticFile("audio/ambient_extended.wav")} />
  </AbsoluteFill>
);
