// Shared look: colours, the Inter font (local files in public/fonts, SIL OFL), and the
// small building blocks every scene uses (headline, labels, credit line, burned-in captions).
import React from "react";
import { AbsoluteFill, continueRender, delayRender, interpolate, Easing, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { CUES } from "./captions";

export const C = {
  bg: "#05080f",
  navy: "#0b1220",
  fg: "#e9edf5",
  muted: "#93a0b8",
  line: "#2a3a5c",
  acc: "#7cc4ff", // same accent as the app and the Judge Mode page
  warm: "#e8b04a",
  red: "#e0525e",
  ok: "#3fb27a",
};
export const FONT = "Inter, sans-serif";

// Load the font once before the first frame is captured, so every frame uses the same metrics.
const weights: [string, string][] = [["300", "light"], ["400", "regular"], ["500", "medium"], ["600", "semibold"], ["700", "bold"]];
if (typeof document !== "undefined") {
  const h = delayRender("Loading Inter");
  Promise.all(
    weights.map(([w, f]) => {
      const face = new FontFace("Inter", `url(${staticFile(`fonts/inter-${f}.otf`)})`, { weight: w });
      document.fonts.add(face);
      return face.load();
    }),
  ).then(() => continueRender(h));
}

export const ease = Easing.bezier(0.33, 0, 0.2, 1);

// 0→1 between two frames, eased and clamped.
export const ramp = (f: number, a: number, b: number) =>
  interpolate(f, [a, b], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });

// Fade a whole scene in and out (scenes overlap by OVERLAP frames, so this is a cross-fade).
export const SceneFade: React.FC<{ children: React.ReactNode; inF?: number; outF?: number; bg?: string }> = ({ children, inF = 12, outF = 12, bg }) => {
  const f = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const o = Math.min(ramp(f, 0, inF), 1 - ramp(f, durationInFrames - outF, durationInFrames));
  return <AbsoluteFill style={{ opacity: o, background: bg }}>{children}</AbsoluteFill>;
};

// Big spaced headline; letters ease in from a slight blur.
export const Headline: React.FC<{ text: string; at?: number; top?: number; size?: number; color?: string }> = ({ text, at = 8, top = 96, size = 76, color = C.fg }) => {
  const f = useCurrentFrame();
  const p = ramp(f, at, at + 22);
  return (
    <div style={{ position: "absolute", top, left: 0, right: 0, textAlign: "center", fontFamily: FONT, fontWeight: 600, fontSize: size,
      letterSpacing: "0.16em", color, opacity: p, transform: `translateY(${(1 - p) * 14}px)`, filter: `blur(${(1 - p) * 6}px)`,
      textShadow: "0 2px 24px rgba(0,0,0,0.6)" }}>
      {text}
    </div>
  );
};

// Small uppercase tag, e.g. "illustration" or "CONCEPT — FUTURE RESEARCH".
export const Tag: React.FC<{ children: React.ReactNode; style?: React.CSSProperties; color?: string }> = ({ children, style, color = C.muted }) => (
  <div style={{ position: "absolute", fontFamily: FONT, fontWeight: 600, fontSize: 22, letterSpacing: "0.14em", textTransform: "uppercase",
    color, border: `1.5px solid ${color}`, borderRadius: 6, padding: "5px 12px", background: "rgba(5,8,15,0.7)", ...style }}>
    {children}
  </div>
);

// Source line for real data, bottom-left above the captions.
export const Credit: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => (
  <div style={{ position: "absolute", left: 80, bottom: 176, fontFamily: FONT, fontSize: 22, color: C.muted, letterSpacing: "0.02em", ...style }}>
    {children}
  </div>
);

// Burned-in English captions (exact narration text), bottom centre.
export const Captions: React.FC<{ cues?: typeof CUES; bottom?: number; size?: number; maxWidth?: number }> = ({ cues = CUES, bottom = 64, size = 40, maxWidth = 1780 }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const ms = (f / fps) * 1000;
  const cue = cues.find((c) => ms >= c.startMs && ms < c.endMs);
  if (!cue) return null;
  const o = Math.min(1, (ms - cue.startMs) / 200, (cue.endMs - ms) / 200);
  return (
    <div style={{ position: "absolute", left: 0, right: 0, bottom, display: "flex", justifyContent: "center", opacity: o }}>
      <div style={{ maxWidth, fontFamily: FONT, fontWeight: 500, fontSize: size, lineHeight: 1.3, color: "#fff", textAlign: "center",
        background: "rgba(3,6,12,0.78)", padding: "10px 26px", borderRadius: 10 }}>
        {cue.text}
      </div>
    </div>
  );
};
