/*
 * HIPPARCHUS · vertical cut for social feeds (18 s, 1080x1920, 30 fps).
 * One question, the working app, one verified result, the identity. Nothing new is claimed here:
 * every picture is a Manim scene or the real screen recording also used in the 29.4 s film.
 *   0.0– 4.0 s  M11: two real SPHEREx images of RW Aur and their difference; IS THIS CHANGE REAL?
 *   4.0–10.0 s  real screen recording: quality checks + timeline, then the comparison
 *  10.0–14.5 s  M13: 175 sigma formal, 12.4 sigma with the 12.5% calibration floor
 *  14.5–18.0 s  identity
 * Render: ./scripts/build_cut.sh vertical   (captions: src/captions_vertical.ts)
 * Ambient cut times (s): 4 10 14.5
 */
import React from "react";
import { AbsoluteFill, Audio, Img, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame } from "remotion";
import { C, Captions, FONT, SceneFade, ramp } from "./ui";
import { CUES_VERTICAL } from "./captions_vertical";

export const VERTICAL_DURATION = 540;
const W = 1080;
const OV = 10;

// A 16:9 clip shown full width, with a large question above it.
const Panel: React.FC<{ src: string; startFrom: number; title: string; sub?: string; titleColor?: string }> = ({ src, startFrom, title, sub, titleColor = C.fg }) => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: C.bg }}>
      <div style={{ position: "absolute", top: 250, left: 60, right: 60, fontFamily: FONT, fontWeight: 700, fontSize: 84,
        lineHeight: 1.08, color: titleColor, letterSpacing: "0.02em", opacity: ramp(f, 4, 16) }}>{title}</div>
      {sub ? <div style={{ position: "absolute", top: 500, left: 60, right: 60, fontFamily: FONT, fontSize: 38, color: C.muted, opacity: ramp(f, 10, 22) }}>{sub}</div> : null}
      <div style={{ position: "absolute", left: 0, top: 640, width: W, height: (W * 9) / 16, border: `1px solid ${C.line}` }}>
        <OffthreadVideo src={staticFile(src)} trimBefore={startFrom} muted style={{ width: W, height: (W * 9) / 16 }} />
      </div>
    </AbsoluteFill>
  );
};

// The same recording as the 29.4 s film, cropped onto the area that shows the result.
const AppCut: React.FC<{ from: number; len: number; step: string; cx: number; cy: number }> = ({ from, len, step, cx, cy }) => {
  const f = useCurrentFrame();
  const z = interpolate(f, [0, len], [1.0, 1.08]);
  const S = 0.75; // the 1920x1080 recording at 75%: the useful 1440 px of it fill the phone width
  return (
    <AbsoluteFill style={{ background: C.bg }}>
      <div style={{ position: "absolute", top: 250, left: 60, right: 60, fontFamily: FONT, fontWeight: 700, fontSize: 72, color: C.fg }}>THE WORKING APP</div>
      <div style={{ position: "absolute", top: 350, left: 60, fontFamily: FONT, fontWeight: 600, fontSize: 36, color: C.bg, background: C.acc, padding: "6px 16px", borderRadius: 8 }}>{step}</div>
      <div style={{ position: "absolute", left: 0, top: 460, width: W, height: 1000, overflow: "hidden", borderTop: `1px solid ${C.line}`, borderBottom: `1px solid ${C.line}` }}>
        <div style={{ position: "absolute", left: W / 2 - cx * S, top: 500 - cy * S, transform: `scale(${z})`, transformOrigin: `${cx * S}px ${cy * S}px`, opacity: ramp(f, 0, 6) }}>
          <OffthreadVideo src={staticFile("rec/app.mp4")} trimBefore={Math.round(from * 30)} muted style={{ width: 1920 * S, height: 1080 * S }} />
        </div>
      </div>
      <div style={{ position: "absolute", left: 60, right: 60, top: 1480, fontFamily: FONT, fontSize: 24, lineHeight: 1.35, color: C.muted }}>Real screen recording of the app (2026-11-15 UTC). IRSA returned HTTP 502, so the app used its cached listing, as labelled.</div>
    </AbsoluteFill>
  );
};

const Identity: React.FC = () => {
  const f = useCurrentFrame();
  const a = ramp(f, 0, 14), b = ramp(f, 12, 26);
  const line: React.CSSProperties = { position: "absolute", left: 40, right: 40, textAlign: "center", fontFamily: FONT, color: C.fg };
  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <Img src={staticFile("brand/hipparchus-logo_ai.png")} style={{ position: "absolute", left: 90, top: 330, width: 900, opacity: a }} />
      <div style={{ ...line, top: 840, fontSize: 52, fontWeight: 600, letterSpacing: "0.08em", opacity: a }}>THE UNIVERSE IS NEVER STILL.</div>
      <Img src={staticFile("brand/aethenova-logo_ai.png")} style={{ position: "absolute", left: 190, top: 960, width: 700, opacity: b }} />
      <div style={{ ...line, top: 1560, fontSize: 26, color: C.muted, opacity: b }}>AI-generated logos · Team AETHENOVA · NASA Space Apps Challenge 2026</div>
      <div style={{ ...line, top: 1600, fontSize: 26, color: C.muted, opacity: b }}>independent project, not endorsed by NASA</div>
    </AbsoluteFill>
  );
};

export const Vertical: React.FC = () => (
  <AbsoluteFill style={{ background: "#000" }}>
    <Sequence from={0} durationInFrames={120 + OV}>
      <SceneFade inF={1}><Panel src="manim/m11_change_real.mp4" startFrom={63} title="IS THIS CHANGE REAL?" sub="RW Aurigae · two real SPHEREx images · one year apart" titleColor={C.warm} /></SceneFade>
    </Sequence>
    <Sequence from={120} durationInFrames={90 + OV}>
      <SceneFade><AppCut from={24.6} len={90} step="QUALITY CHECKS · TIMELINE" cx={740} cy={540} /></SceneFade>
    </Sequence>
    <Sequence from={210} durationInFrames={90 + OV}>
      <SceneFade><AppCut from={30.4} len={90} step="COMPARISON" cx={1200} cy={600} /></SceneFade>
    </Sequence>
    <Sequence from={300} durationInFrames={135 + OV}>
      <SceneFade><Panel src="manim/m13_uncertainty.mp4" startFrom={102} title="BIGGER THAN THE ERRORS?" sub="175σ formal → 12.4σ with a 12.5% calibration floor" /></SceneFade>
    </Sequence>
    <Sequence from={435} durationInFrames={105}>
      <SceneFade outF={1}><Identity /></SceneFade>
    </Sequence>
    <Captions cues={CUES_VERTICAL} bottom={150} size={44} maxWidth={960} />
    <Audio src={staticFile("audio/ambient_vertical.wav")} />
  </AbsoluteFill>
);
