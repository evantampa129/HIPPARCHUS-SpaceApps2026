// The seven scenes. Timing of each scene is set in hipparchus.tsx; frame numbers below are
// local to the scene (0 = first frame of the scene, 30 fps).
//
// Rule for everything on screen: real SPHEREx images, real app frames and the real Judge Mode
// page are shown as they are (only scaled / panned). Anything drawn by code is either a plain
// annotation (labels, dates, numbers taken from the project's results) or is tagged
// "illustration" / "concept".
import React from "react";
import { AbsoluteFill, Img, OffthreadVideo, Sequence, interpolate, random, staticFile, useCurrentFrame } from "remotion";
import { C, Credit, FONT, Headline, Tag, ramp } from "./ui";

const img = (p: string) => staticFile(p);
const pixelated: React.CSSProperties = { imageRendering: "pixelated" };

// ---------------------------------------------------------------- 1. ANCIENT CURIOSITY
// A slowly turning celestial sphere drawn line by line (graticule + ecliptic), over a faint
// random star field. Pure illustration, tagged as such.
const R = 360;
const CX = 960;
const CY = 560;
const TILT = (22 * Math.PI) / 180; // we look at the sphere from 22° above its equator
const d2r = Math.PI / 180;

// Orthographic projection; returns null for the far side of the sphere.
const proj = (lon: number, lat: number, rot: number) => {
  const l = (lon - rot) * d2r;
  const b = lat * d2r;
  const z = Math.sin(TILT) * Math.sin(b) + Math.cos(TILT) * Math.cos(b) * Math.cos(l);
  const x = R * Math.cos(b) * Math.sin(l);
  const y = R * (Math.cos(TILT) * Math.sin(b) - Math.sin(TILT) * Math.cos(b) * Math.cos(l));
  return z < 0 ? null : [CX + x, CY - y];
};
// Path through the visible part of a curve given as (lon, lat) samples.
const curve = (pts: [number, number][], rot: number) => {
  let d = "";
  let pen = false;
  for (const [lo, la] of pts) {
    const p = proj(lo, la, rot);
    if (!p) { pen = false; continue; }
    d += `${pen ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`;
    pen = true;
  }
  return d;
};
const range = (a: number, b: number, s: number) => { const r: number[] = []; for (let v = a; v <= b + 1e-9; v += s) r.push(v); return r; };
// Ecliptic: great circle inclined 23.44° to the equator.
const ecl = range(0, 360, 3).map((t): [number, number] => {
  const e = 23.44 * d2r, a = t * d2r;
  const lat = Math.asin(Math.sin(e) * Math.sin(a)) / d2r;
  const lon = Math.atan2(Math.cos(e) * Math.sin(a), Math.cos(a)) / d2r;
  return [lon, lat];
});

const Stars: React.FC<{ n: number; seed: string; opacity?: number }> = ({ n, seed, opacity = 1 }) => {
  const f = useCurrentFrame();
  return (
    <svg width={1920} height={1080} style={{ position: "absolute", opacity }}>
      {range(0, n - 1, 1).map((i) => {
        const x = random(`${seed}x${i}`) * 1920, y = random(`${seed}y${i}`) * 1080;
        const m = random(`${seed}m${i}`);
        const tw = 0.75 + 0.25 * Math.sin(f / 9 + i);
        return <circle key={i} cx={x} cy={y} r={0.6 + m * m * 1.8} fill="#cfdcff" opacity={(0.15 + 0.6 * m * m) * tw} />;
      })}
    </svg>
  );
};

export const SceneAncient: React.FC = () => {
  const f = useCurrentFrame();
  const rot = 20 + f * 0.35;
  const draw = (start: number) => ramp(f, start, start + 40);
  const zoom = interpolate(f, [80, 130], [1, 1.25], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const merid = range(0, 330, 30);
  const paral = range(-60, 60, 20);
  return (
    <AbsoluteFill style={{ background: `radial-gradient(ellipse at 50% 55%, #0c1630 0%, ${C.bg} 70%)` }}>
      <Stars n={260} seed="s1" opacity={ramp(f, 0, 30)} />
      <svg width={1920} height={1080} style={{ position: "absolute", transform: `scale(${zoom})`, transformOrigin: `${CX}px ${CY}px` }}>
        <circle cx={CX} cy={CY} r={R} fill="none" stroke={C.line} strokeWidth={1.5} opacity={draw(0)} />
        {paral.map((la, i) => (
          <path key={`p${la}`} d={curve(range(0, 360, 4).map((lo): [number, number] => [lo, la]), rot)} fill="none"
            stroke={la === 0 ? C.acc : "#5a7bb0"} strokeWidth={la === 0 ? 2 : 1.2} opacity={la === 0 ? 0.9 : 0.55}
            pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw(4 + i * 4)} />
        ))}
        {merid.map((lo, i) => (
          <path key={`m${lo}`} d={curve(range(-90, 90, 3).map((la): [number, number] => [lo, la]), rot)} fill="none"
            stroke="#5a7bb0" strokeWidth={1.2} opacity={0.55} pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw(10 + i * 3)} />
        ))}
        <path d={curve(ecl, rot)} fill="none" stroke={C.warm} strokeWidth={2} opacity={0.85} pathLength={1} strokeDasharray={1}
          strokeDashoffset={1 - draw(40)} />
      </svg>
      <Headline text="2,000 YEARS OF LOOKING UP" at={14} />
      <Tag style={{ right: 80, bottom: 176 }}>illustration</Tag>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- 2. A NEW WINDOW
// The sphere becomes a flat RA/Dec chart around RW Aurigae (RA 76.956°, Dec +30.401°), the
// chart zooms onto the star, and the real SPHEREx cutouts take over.
const RA0 = 76.956;
const DEC0 = 30.401;
const raLabel = (ra: number) => { const h = ra / 15; const hh = Math.floor(h); const mm = Math.round((h - hh) * 60); return `${hh}h${String(mm).padStart(2, "0")}m`; };

const Chart: React.FC<{ f: number }> = ({ f }) => {
  // 1 degree = 260 px at the start, zooming in towards the target.
  const z = interpolate(f, [0, 70], [1, 4.2], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: (t) => t * t * (3 - 2 * t) });
  const s = 260 * z;
  const cosd = Math.cos(DEC0 * d2r);
  const X = (ra: number) => 960 - (ra - RA0) * cosd * s; // RA grows to the left on the sky
  const Y = (dec: number) => 540 - (dec - DEC0) * s;
  const ras = range(70, 84, 1);
  const decs = range(25, 36, 1);
  const lab = { fontFamily: FONT, fontSize: 20, fill: C.muted } as const;
  return (
    <svg width={1920} height={1080} style={{ position: "absolute" }}>
      {ras.map((ra) => <line key={ra} x1={X(ra)} x2={X(ra)} y1={0} y2={1080} stroke="#4a6496" strokeWidth={1} opacity={0.5} />)}
      {decs.map((de) => <line key={de} x1={0} x2={1920} y1={Y(de)} y2={Y(de)} stroke="#4a6496" strokeWidth={1} opacity={0.5} />)}
      {ras.map((ra) => X(ra) > 60 && X(ra) < 1860 ? <text key={`t${ra}`} x={X(ra) + 6} y={1040 - 160} {...lab}>{raLabel(ra)}</text> : null)}
      {decs.map((de) => Y(de) > 220 && Y(de) < 860 ? <text key={`d${de}`} x={70} y={Y(de) - 6} {...lab}>{`${de > 0 ? "+" : ""}${de}°`}</text> : null)}
    </svg>
  );
};

const Cutout: React.FC<{ src: string; size: number; x: number; y: number; o: number; label?: string; sub?: string }> = ({ src, size, x, y, o, label, sub }) => (
  <div style={{ position: "absolute", left: x - size / 2, top: y - size / 2, width: size, opacity: o }}>
    <Img src={img(src)} style={{ width: size, height: size, display: "block", border: `1px solid ${C.line}`, boxShadow: "0 10px 40px rgba(0,0,0,0.6)", ...pixelated }} />
    {label ? (
      <div style={{ marginTop: 14, textAlign: "center", fontFamily: FONT, fontSize: 28, fontWeight: 600, color: C.fg }}>
        {label}
        {sub ? <div style={{ fontSize: 22, fontWeight: 400, color: C.muted, marginTop: 4 }}>{sub}</div> : null}
      </div>
    ) : null}
  </div>
);

export const SceneWindow: React.FC = () => {
  const f = useCurrentFrame();
  const chartO = 1 - ramp(f, 62, 84);
  const reticle = ramp(f, 30, 44) * chartO;
  // Cutout of RW Aur: appears at the reticle, then slides left as the other two arrive.
  const a = ramp(f, 56, 76);
  const spread = ramp(f, 76, 100);
  const size = 380;
  const xs = [960 - spread * 450, 960, 960 + spread * 450];
  const side = ramp(f, 84, 104); // side cutouts only fade in once they are clear of the centre one
  return (
    <AbsoluteFill style={{ background: C.bg }}>
      <Stars n={140} seed="s2" opacity={0.6 * chartO} />
      <AbsoluteFill style={{ opacity: chartO * ramp(f, 0, 12) }}><Chart f={f} /></AbsoluteFill>
      <svg width={1920} height={1080} style={{ position: "absolute", opacity: reticle }}>
        <circle cx={960} cy={540} r={60} fill="none" stroke={C.acc} strokeWidth={2} />
        {[[-110, -70], [70, 110]].map(([p, q], i) => (
          <g key={i}><line x1={960 + p} x2={960 + q} y1={540} y2={540} stroke={C.acc} strokeWidth={2} /><line y1={540 + p} y2={540 + q} x1={960} x2={960} stroke={C.acc} strokeWidth={2} /></g>
        ))}
        <text x={1040} y={470} fontFamily={FONT} fontSize={26} fill={C.acc}>RW Aurigae · RA 76.956°  Dec +30.401°</text>
      </svg>
      <Cutout src="img/wise0855_a.png" size={size} x={xs[0]} y={480} o={side} label="WISE 0855−0714" sub="coldest known brown dwarf" />
      <Cutout src="img/rw_aur_a.png" size={size} x={xs[1]} y={480} o={a} label={side > 0.01 ? "RW Aurigae" : undefined} sub="young variable star" />
      <Cutout src="img/barnard_epoch.png" size={size} x={xs[2]} y={480} o={side} label="Barnard’s Star" sub="nearby red dwarf" />
      <Headline text="THE INFRARED UNIVERSE" at={50} />
      <Credit style={{ opacity: a }}>
        Real SPHEREx cutouts · SPHEREx / NASA/IPAC IRSA, processed by HIPPARCHUS · flagged pixels in dark red
      </Credit>
      <Tag style={{ right: 80, bottom: 176, opacity: 1 - a }}>RA/Dec chart · illustration</Tag>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- 3. THE CHALLENGE
// RW Aur, same detector, one year apart (the pair with the largest |σ|), then the difference.
export const SceneChallenge: React.FC = () => {
  const f = useCurrentFrame();
  const push = interpolate(f, [0, 130], [1, 1.04]);
  const size = 380;
  const panel = (i: number) => 330 + i * (size + 70);
  const pA = ramp(f, 0, 14), pB = ramp(f, 12, 26), pD = ramp(f, 40, 56);
  const q = ramp(f, 66, 80);
  const qTag: React.CSSProperties = { fontSize: 30, letterSpacing: "0.04em", textTransform: "none", fontWeight: 600 };
  return (
    <AbsoluteFill style={{ background: C.bg }}>
      <AbsoluteFill style={{ transform: `scale(${push})` }}>
        <Cutout src="img/rw_aur_a.png" size={size} x={panel(0) + size / 2} y={500} o={pA} label="2025-09-02" sub="λ 0.763 µm · earlier" />
        <Cutout src="img/rw_aur_b.png" size={size} x={panel(1) + size / 2} y={500} o={pB} label="2026-09-08" sub="λ 0.770 µm · later" />
        <Cutout src="img/rw_aur_diff.png" size={size} x={panel(2) + size / 2} y={500} o={pD} label="Difference" sub="later − earlier · red = brighter" />
      </AbsoluteFill>
      <Tag color={C.warm} style={{ ...qTag, left: panel(0) + 60, top: 250, opacity: q }}>wavelength?</Tag>
      <Tag color={C.warm} style={{ ...qTag, left: panel(2) + 70, top: 250, opacity: ramp(f, 76, 90) }}>uncertainty?</Tag>
      <Headline text="NOT EVERY CHANGE IS REAL" at={52} />
      <Credit>RW Aurigae, SPHEREx detector D1 · SPHEREx / NASA/IPAC IRSA, processed by HIPPARCHUS</Credit>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- 4. HIPPARCHUS IN ACTION
// Real screen recording of the app (public/rec/app.mp4, made by scripts/record_app.mjs).
// Four cuts at 1× speed; times in seconds of the recording (see public/rec/marks.json).
const SEGMENTS = [
  { from: 1.2, len: 63, step: 0, ox: 420, oy: 180, z0: 1.0, z1: 1.18 }, // pick RW Aurigae, "1. Search archive"
  { from: 19.0, len: 52, step: 1, ox: 900, oy: 420, z0: 1.08, z1: 1.16 }, // archive answer
  { from: 24.6, len: 70, step: 2, ox: 960, oy: 520, z0: 1.0, z1: 1.1 }, // quality checks + timeline playback
  { from: 30.4, len: 55, step: 3, ox: 640, oy: 640, z0: 1.12, z1: 1.2 }, // comparison: blink, difference, significance
];
const STEPS = ["Search", "Archive answer", "Quality checks · timeline", "Comparison"];
const WX = 320, WY = 146, WW = 1280, WH = 720;

export const SceneAction: React.FC = () => {
  const f = useCurrentFrame();
  let start = 0;
  const seqs = SEGMENTS.map((s) => { const st = start; start += s.len; return { ...s, st }; });
  const cur = seqs.findIndex((s) => f >= s.st && f < s.st + s.len);
  const active = cur < 0 ? (f < 0 ? 0 : 3) : seqs[cur].step;
  return (
    <AbsoluteFill style={{ background: `radial-gradient(ellipse at 50% 40%, #0e1830 0%, ${C.bg} 75%)` }}>
      <div style={{ position: "absolute", top: 70, left: 0, right: 0, display: "flex", justifyContent: "center", gap: 18, fontFamily: FONT }}>
        {STEPS.map((t, i) => (
          <div key={t} style={{ fontSize: 26, fontWeight: 600, letterSpacing: "0.06em", padding: "8px 18px", borderRadius: 8,
            color: i === active ? C.bg : C.muted, background: i === active ? C.acc : "transparent", border: `1.5px solid ${i === active ? C.acc : C.line}` }}>
            {`${i + 1}  ${t.toUpperCase()}`}
          </div>
        ))}
      </div>
      <div style={{ position: "absolute", left: WX, top: WY, width: WW, height: WH, overflow: "hidden", borderRadius: 14,
        border: `1.5px solid ${C.line}`, boxShadow: "0 30px 80px rgba(0,0,0,0.7)", background: "#0d1220" }}>
        {seqs.map((s) => (
          <Sequence key={s.st} from={s.st} durationInFrames={s.len} layout="none">
            <SegmentVideo s={s} />
          </Sequence>
        ))}
      </div>
      <Credit style={{ left: WX }}>
        Real screen recording of the app (2026-11-15 UTC) · IRSA returned HTTP 502, so the app used its cached listing, as labelled
      </Credit>
    </AbsoluteFill>
  );
};

const SegmentVideo: React.FC<{ s: (typeof SEGMENTS)[number] & { st: number } }> = ({ s }) => {
  const f = useCurrentFrame();
  const z = interpolate(f, [0, s.len], [s.z0, s.z1]);
  const o = ramp(f, 0, 4);
  return (
    <div style={{ position: "absolute", inset: 0, opacity: o, transform: `scale(${z})`, transformOrigin: `${(s.ox / 1920) * 100}% ${(s.oy / 1080) * 100}%` }}>
      <OffthreadVideo src={img("rec/app.mp4")} trimBefore={Math.round(s.from * 30)} muted style={{ width: WW, height: WH }} />
    </div>
  );
};

// ---------------------------------------------------------------- 5. THE EVIDENCE
// Three real crops of the public Judge Mode page (scripts/capture_judge.mjs).
export const SceneEvidence: React.FC = () => {
  const f = useCurrentFrame();
  const words = ["OBSERVE.", "VERIFY.", "CHALLENGE.", "EXPLAIN."];
  const focus = f < 62 ? 0 : f < 118 ? 1 : 2;
  const dim = (i: number) => (i === focus ? 1 : 0.42);
  const rise = (at: number) => ({ o: ramp(f, at, at + 16), y: (1 - ramp(f, at, at + 16)) * 24 });
  const c0 = rise(4), c1 = rise(56), c2 = rise(112);
  const cardH = 640, cardW = (cardH * 636) / 1142;
  return (
    <AbsoluteFill style={{ background: C.bg }}>
      <div style={{ position: "absolute", top: 70, left: 0, right: 0, display: "flex", justifyContent: "center", gap: 34, fontFamily: FONT, fontWeight: 600, fontSize: 56, letterSpacing: "0.12em" }}>
        {words.map((w, i) => {
          const p = ramp(f, 2 + i * 14, 18 + i * 14);
          return <span key={w} style={{ opacity: p, color: i === 2 ? C.acc : C.fg, transform: `translateY(${(1 - p) * 10}px)` }}>{w}</span>;
        })}
      </div>
      <Img src={img("judge/card_rwaur.png")} style={{ position: "absolute", left: 150, top: 180 + c0.y, height: cardH, width: cardW, borderRadius: 10, opacity: c0.o * dim(0), boxShadow: "0 20px 60px rgba(0,0,0,0.6)" }} />
      <div style={{ position: "absolute", left: 150 + cardW + 60, top: 230 + c1.y, width: 1920 - 2 * (150 + cardW + 60), opacity: c1.o * dim(1), fontFamily: FONT, textAlign: "center" }}>
        <Img src={img("judge/heatmap.png")} style={{ width: "100%", borderRadius: 8, border: `1px solid ${C.line}` }} />
        <div style={{ marginTop: 22, fontSize: 30, fontWeight: 600, color: C.fg }}>
          “×1.5 at ≥5σ” holds in <span style={{ color: C.ok }}>24 / 24</span> settings → <span style={{ color: C.ok }}>ROBUST</span>
        </div>
        <div style={{ marginTop: 8, fontSize: 22, color: C.muted }}>RW Aur robustness check: aperture × sky annulus (one slice of the 24)</div>
      </div>
      <Img src={img("judge/card_barnard.png")} style={{ position: "absolute", right: 150, top: 180 + c2.y, height: cardH, width: cardW, borderRadius: 10, opacity: c2.o * dim(2), boxShadow: "0 20px 60px rgba(0,0,0,0.6)" }} />
      <Credit>Real result cards from the public Judge Mode page · evantampa129.github.io/HIPPARCHUS-SpaceApps2026</Credit>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- 6. THE NEXT FRONTIER
// Reads image / caption / label from public/frontier.json (via calculateMetadata in root.tsx),
// so a real result can replace the concept later without touching code. With no image, a
// programmatic concept is shown: a fixed star field over five epochs, one dot that moves.
export type Frontier = { image: string; caption: string; label: string };

const FW = 900, FH = 440;
const Concept: React.FC<{ f: number }> = ({ f }) => {
  const epoch = Math.min(4, Math.floor(interpolate(f, [8, 68], [0, 5], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })));
  const mover = (k: number) => [200 + k * 120, 300 - k * 38];
  return (
    <svg width={FW} height={FH} style={{ display: "block" }}>
      <rect width={FW} height={FH} fill="#070c18" stroke={C.line} />
      {range(0, 70, 1).map((i) => {
        const m = random(`c${i}`);
        return <circle key={i} cx={random(`cx${i}`) * FW} cy={random(`cy${i}`) * FH} r={1 + m * 2.5} fill="#cfdcff" opacity={0.3 + 0.6 * m} />;
      })}
      {range(0, epoch, 1).map((k) => {
        const [x, y] = mover(k);
        const cur = k === epoch;
        return <g key={k}>
          <circle cx={x} cy={y} r={cur ? 7 : 5} fill={C.warm} opacity={cur ? 1 : 0.35} />
          {cur ? <circle cx={x} cy={y} r={20} fill="none" stroke={C.warm} strokeWidth={2} /> : null}
          <text x={x - 14} y={y + 42} fontFamily={FONT} fontSize={20} fill={C.muted}>{`t${k + 1}`}</text>
        </g>;
      })}
      {epoch >= 2 ? <line x1={mover(0)[0]} y1={mover(0)[1]} x2={mover(epoch)[0]} y2={mover(epoch)[1]} stroke={C.warm} strokeDasharray="6 8" strokeWidth={2} opacity={0.7} /> : null}
      <text x={FW - 20} y={36} textAnchor="end" fontFamily={FONT} fontSize={24} fontWeight={600} fill={C.fg}>{`epoch ${epoch + 1} / 5`}</text>
    </svg>
  );
};

export const SceneFrontier: React.FC<{ frontier: Frontier }> = ({ frontier }) => {
  const f = useCurrentFrame();
  const o = ramp(f, 0, 14);
  return (
    <AbsoluteFill style={{ background: `radial-gradient(ellipse at 50% 55%, #101a33 0%, ${C.bg} 75%)` }}>
      <Headline text="THE NEXT FRONTIER" at={2} top={70} />
      <div style={{ position: "absolute", top: 172, left: 0, right: 0, display: "flex", justifyContent: "center" }}>
        <Tag color={C.warm} style={{ position: "relative", fontSize: 26 }}>{frontier.label}</Tag>
      </div>
      <div style={{ position: "absolute", left: (1920 - FW) / 2, top: 250, width: FW, opacity: o }}>
        {frontier.image ? (
          <Img src={img(frontier.image)} style={{ width: FW, height: FH, objectFit: "contain", background: "#070c18", border: `1px solid ${C.line}` }} />
        ) : (
          <Concept f={f} />
        )}
        <div style={{ marginTop: 18, textAlign: "center", fontFamily: FONT, fontSize: 28, color: C.fg }}>{frontier.caption}</div>
      </div>
      {frontier.image ? null : <Tag style={{ left: (1920 - FW) / 2 + 16, top: 250 + FH - 52 }}>illustration</Tag>}
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- 7. FINAL IDENTITY
// Both logos are AI-generated and carry their own "AI-generated" mark; an extra label is added
// because the mark in the team logo is small at this size.
export const SceneIdentity: React.FC = () => {
  const f = useCurrentFrame();
  const a = ramp(f, 0, 14), b = ramp(f, 12, 26), out = 1 - ramp(f, 86, 102);
  const line: React.CSSProperties = { position: "absolute", left: 0, right: 0, textAlign: "center", fontFamily: FONT, letterSpacing: "0.14em", color: C.fg };
  return (
    <AbsoluteFill style={{ background: "#000", opacity: out }}>
      <Img src={img("brand/hipparchus-logo_ai.png")} style={{ position: "absolute", left: 510, top: 6, width: 900, opacity: a }} />
      <div style={{ ...line, top: 452, fontSize: 40, fontWeight: 600, opacity: a }}>HIPPARCHUS — THE UNIVERSE IS NEVER STILL.</div>
      <Img src={img("brand/aethenova-logo_ai.png")} style={{ position: "absolute", left: 660, top: 512, width: 600, opacity: b }} />
      <div style={{ position: "absolute", left: 1272, top: 868, fontFamily: FONT, fontSize: 20, color: "#cfd6e4", opacity: b }}>AI-generated logo</div>
      <div style={{ ...line, top: 920, fontSize: 32, fontWeight: 500, opacity: b }}>ANCIENT CURIOSITY. INFINITE DISCOVERY.</div>
      <div style={{ ...line, top: 1000, fontSize: 20, letterSpacing: "0.04em", color: C.muted, opacity: b }}>
        Team AETHENOVA · NASA Space Apps Challenge 2026 · “Planet X and SPHEREx” · independent project, not endorsed by NASA
      </div>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- MANIM CLIPS (scenes 1 and 6)
// We show a Manim scene from visualizations/manim/renders as it was rendered, scaled into a
// frame under a headline. The clip carries its own label (CONCEPTUAL / DATA-DRIVEN) and source
// line, so nothing is added on top of it; startFrom picks the part of the clip we have room for.
const MW = 1344, MH = 756;
export const SceneManim: React.FC<{ src: string; headline: string; startFrom?: number; tag?: string }> = ({ src, headline, startFrom = 0, tag }) => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: C.bg }}>
      <Headline text={headline} at={2} top={34} size={60} />
      <div style={{ position: "absolute", left: (1920 - MW) / 2, top: 130, width: MW, height: MH, opacity: ramp(f, 0, 10),
        border: `1px solid ${C.line}` }}>
        <OffthreadVideo src={staticFile(src)} startFrom={startFrom} muted style={{ width: MW, height: MH }} />
      </div>
      {tag ? <Tag color={C.warm} style={{ left: (1920 - MW) / 2, top: 130 + MH + 12, fontSize: 22 }}>{tag}</Tag> : null}
    </AbsoluteFill>
  );
};
