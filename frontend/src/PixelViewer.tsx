import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { Grid } from "./api";
import {
  CREDIT, DIVERGING_MAPS, SEQUENTIAL_MAPS, STRETCHES, Stretch, addPngText, download, lut, percentile,
  prefersReducedMotion, stretch,
} from "./imaging";

// Native-pixel viewer for SPHEREx cutouts. We draw every 6.15" pixel as a flat
// square (nearest neighbour) and never smooth: a cutout is ~29x29 pixels, and
// interpolation would invent detail the detector never recorded.

export interface View { zoom: number; cx: number; cy: number }
export interface Frame { label: string; data: Grid }

export interface PixelViewerProps {
  title: string;
  frames: Frame[];          // 1 frame, or 2 for a blink pair (always on one shared scale)
  masked: number[][];
  kind: "flux" | "diff" | "z";
  unit: string;
  x: number; y: number; rAp: number; annulus: [number, number]; pixelArcsec: number;
  meta: Record<string, string>; // goes into the exported PNG, as text and as tEXt chunks
  fileStem: string;
  view?: View; onView?: (v: View) => void; // lets several viewers share zoom and pan
}

type Clip = "p1max" | "p05" | "p1" | "maxabs" | "s3" | "s5" | "s10";
const CLIPS: Record<PixelViewerProps["kind"], { id: Clip; label: string }[]> = {
  flux: [{ id: "p1max", label: "1st percentile – max (as the PNGs)" }, { id: "p05", label: "0.5–99.5 percentile" }, { id: "p1", label: "1–99 percentile" }],
  diff: [{ id: "p05", label: "±99.5 percentile of |Δ| (as the PNGs)" }, { id: "maxabs", label: "± max |Δ|" }],
  z: [{ id: "s5", label: "±5σ (as the PNGs)" }, { id: "s3", label: "±3σ" }, { id: "s10", label: "±10σ" }],
};

// Inverse of each stretch, to label the colour bar with real values.
function unstretch(l: number, s: Stretch): number {
  if (s === "sqrt") return l * l;
  if (s === "asinh") return Math.sinh(l * Math.asinh(20)) / 20;
  if (s === "log") return (Math.pow(10, 3 * l) - 1) / 999;
  return l;
}

const fmtv = (v: number) => {
  const a = Math.abs(v);
  return a !== 0 && (a < 0.01 || a >= 1e4) ? v.toExponential(2) : v.toFixed(a < 1 ? 3 : a < 100 ? 2 : 1);
};

interface DrawOpts {
  grid: Grid; masked: number[][]; lo: number; hi: number; st: Stretch; cmap: string;
  showMask: boolean; showAp: boolean; x: number; y: number; rAp: number; annulus: [number, number];
}

// One drawing routine for screen and export, so the file is exactly what was shown.
function draw(ctx: CanvasRenderingContext2D, W: number, H: number, scale: number, cx: number, cy: number, o: DrawOpts) {
  const h = o.grid.length, w = o.grid[0]?.length ?? 0;
  const off = document.createElement("canvas");
  off.width = w; off.height = h;
  const octx = off.getContext("2d")!;
  const img = octx.createImageData(w, h);
  const L = lut(o.cmap);
  for (let j = 0; j < h; j++) {
    for (let i = 0; i < w; i++) {
      const v = o.grid[j][i];
      // Row 0 is the bottom of the sky image (FITS order), so we flip it here.
      const k = ((h - 1 - j) * w + i) * 4;
      if (v == null || !isFinite(v)) { img.data.set([70, 70, 70, 255], k); continue; }
      const lvl = Math.round(stretch((v - o.lo) / (o.hi - o.lo || 1), o.st) * 255);
      img.data.set([L[lvl * 3], L[lvl * 3 + 1], L[lvl * 3 + 2], 255], k);
    }
  }
  octx.putImageData(img, 0, 0);
  ctx.save();
  ctx.fillStyle = "#05070d"; ctx.fillRect(0, 0, W, H);
  ctx.imageSmoothingEnabled = false;
  // Pixel i is centred on coordinate i and spans [i-0.5, i+0.5] (0-based, as the backend's x, y).
  const sx = (p: number) => (p - cx) * scale + W / 2;
  const sy = (p: number) => H / 2 - (p - cy) * scale;
  ctx.drawImage(off, sx(-0.5), sy(h - 0.5), w * scale, h * scale);
  if (o.showMask) {
    // Masked pixels get a hatch, not a colour, so it reads the same in every colour map
    // and for colour-blind viewers.
    ctx.lineWidth = Math.max(1, scale / 10);
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
      if (!o.masked[j]?.[i]) continue;
      const x0 = sx(i - 0.5), y0 = sy(j + 0.5);
      ctx.strokeStyle = "rgba(0,0,0,0.9)"; ctx.strokeRect(x0 + 1, y0 + 1, scale - 2, scale - 2);
      ctx.strokeStyle = "rgba(255,255,255,0.95)";
      ctx.beginPath(); ctx.moveTo(x0, y0 + scale); ctx.lineTo(x0 + scale, y0); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x0 + scale, y0 + scale); ctx.stroke();
    }
  }
  if (o.showAp) {
    const ring = (r: number, color: string, dash: number[]) => {
      ctx.setLineDash(dash);
      ctx.beginPath(); ctx.arc(sx(o.x), sy(o.y), r * scale, 0, 2 * Math.PI);
      ctx.strokeStyle = "rgba(0,0,0,0.8)"; ctx.lineWidth = 3.5; ctx.stroke();
      ctx.strokeStyle = color; ctx.lineWidth = 1.6; ctx.stroke();
    };
    ring(o.rAp, "#7fd4ff", []);
    ring(o.annulus[0], "#ffc857", [5, 4]);
    ring(o.annulus[1], "#ffc857", [5, 4]);
    ctx.setLineDash([]);
  }
  ctx.restore();
}

function colourbar(ctx: CanvasRenderingContext2D, x0: number, y0: number, W: number, H: number, cmap: string, st: Stretch, lo: number, hi: number, unit: string, label: string, textColor: string) {
  const L = lut(cmap);
  for (let i = 0; i < W; i++) {
    const k = Math.round((i / (W - 1)) * 255);
    ctx.fillStyle = `rgb(${L[k * 3]},${L[k * 3 + 1]},${L[k * 3 + 2]})`;
    ctx.fillRect(x0 + i, y0, 1, H);
  }
  ctx.fillStyle = textColor; ctx.font = "11px system-ui, sans-serif"; ctx.textBaseline = "top";
  [0, 0.5, 1].forEach((l, n) => {
    const v = lo + unstretch(l, st) * (hi - lo);
    ctx.textAlign = n === 0 ? "left" : n === 1 ? "center" : "right";
    ctx.fillText(fmtv(v), x0 + l * W, y0 + H + 3);
  });
  ctx.textAlign = "left";
  ctx.fillText(`${unit} · ${label}`, x0, y0 + H + 17);
}

export default function PixelViewer(p: PixelViewerProps) {
  const h = p.frames[0].data.length, w = p.frames[0].data[0]?.length ?? 0;
  const home: View = { zoom: 1, cx: (w - 1) / 2, cy: (h - 1) / 2 };
  const [ownView, setOwnView] = useState<View>(home);
  const view = p.view ?? ownView;
  const setView = useCallback((v: View) => (p.onView ? p.onView(v) : setOwnView(v)), [p.onView]);

  const [st, setSt] = useState<Stretch>(p.kind === "flux" ? "asinh" : "linear");
  const [clip, setClip] = useState<Clip>(CLIPS[p.kind][0].id);
  const [cmap, setCmap] = useState(p.kind === "flux" ? "gray" : "rdbu");
  const [showMask, setShowMask] = useState(true);
  const [showAp, setShowAp] = useState(true);
  const [fi, setFi] = useState(0);
  // Blinking is opt-in for people who asked their system for less motion.
  const [blink, setBlink] = useState(p.frames.length > 1 && !prefersReducedMotion());
  const [hover, setHover] = useState<string>("");
  const [size, setSize] = useState(320);
  const wrap = useRef<HTMLDivElement>(null);
  const cv = useRef<HTMLCanvasElement>(null);
  const cb = useRef<HTMLCanvasElement>(null);
  const helpId = useId();

  useEffect(() => {
    if (!blink || p.frames.length < 2) return;
    const id = setInterval(() => setFi((f) => 1 - f), 650);
    return () => clearInterval(id);
  }, [blink, p.frames.length]);

  // Shared limits over all frames and unmasked pixels: a blink then compares like with like.
  const [lo, hi] = useMemo(() => {
    const vals: number[] = [];
    for (const f of p.frames) f.data.forEach((row, j) => row.forEach((v, i) => {
      if (v != null && isFinite(v) && !p.masked[j]?.[i]) vals.push(v);
    }));
    if (!vals.length) return [0, 1];
    if (p.kind === "z") { const s = clip === "s3" ? 3 : clip === "s10" ? 10 : 5; return [-s, s]; }
    if (p.kind === "diff") {
      const a = vals.map(Math.abs);
      const m = clip === "maxabs" ? Math.max(...a) : percentile(a, 99.5);
      return [-(m || 1), m || 1];
    }
    if (clip === "p05") return [percentile(vals, 0.5), percentile(vals, 99.5)];
    if (clip === "p1") return [percentile(vals, 1), percentile(vals, 99)];
    // As the server PNGs: top at the brightest pixel, so the star's core never clips.
    return [percentile(vals, 1), Math.max(...vals)];
  }, [p.frames, p.masked, p.kind, clip]);

  const stEff: Stretch = p.kind === "flux" ? st : "linear";
  const stretchLabel = p.kind === "flux" ? `${STRETCHES.find((s) => s.id === st)!.label} stretch` : "linear, symmetric about 0";
  const opts: DrawOpts = {
    grid: p.frames[Math.min(fi, p.frames.length - 1)].data, masked: p.masked, lo, hi, st: stEff, cmap,
    showMask, showAp, x: p.x, y: p.y, rAp: p.rAp, annulus: p.annulus,
  };

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize(Math.max(200, Math.min(420, el.clientWidth))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const fit = size / Math.max(w, h);
  useEffect(() => {
    const c = cv.current;
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = size * dpr; c.height = size * dpr;
    const ctx = c.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw(ctx, size, size, fit * view.zoom, view.cx, view.cy, opts);
    // Scale bar: 30 arcsec, in real pixels of this cutout.
    const bar = (30 / p.pixelArcsec) * fit * view.zoom;
    if (bar < size * 0.8) {
      ctx.fillStyle = "rgba(0,0,0,0.6)"; ctx.fillRect(6, size - 26, bar + 12, 20);
      ctx.fillStyle = "#fff"; ctx.fillRect(12, size - 12, bar, 3);
      ctx.font = "11px system-ui, sans-serif"; ctx.fillText("30″", 12, size - 15);
    }
    const b = cb.current;
    if (b) {
      b.width = size * dpr; b.height = 44 * dpr;
      const bctx = b.getContext("2d")!;
      bctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      bctx.clearRect(0, 0, size, 44);
      colourbar(bctx, 4, 2, size - 8, 10, cmap, stEff, lo, hi, p.unit, stretchLabel,
        getComputedStyle(document.body).color || "#e6ebf5");
    }
  });

  // Wheel zoom about the cursor. React's onWheel is passive, so we attach it ourselves.
  useEffect(() => {
    const c = cv.current;
    if (!c) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = c.getBoundingClientRect();
      const s = fit * view.zoom;
      const px = view.cx + (e.clientX - r.left - size / 2) / s;
      const py = view.cy + (size / 2 - (e.clientY - r.top)) / s;
      const z = Math.min(16, Math.max(1, view.zoom * (e.deltaY < 0 ? 1.25 : 0.8)));
      const s2 = fit * z;
      setView({ zoom: z, cx: px - (e.clientX - r.left - size / 2) / s2, cy: py - (size / 2 - (e.clientY - r.top)) / s2 });
    };
    c.addEventListener("wheel", onWheel, { passive: false });
    return () => c.removeEventListener("wheel", onWheel);
  }, [view, fit, size, setView]);

  const drag = useRef<{ x: number; y: number; v: View } | null>(null);
  const pixelAt = (e: React.PointerEvent) => {
    const r = cv.current!.getBoundingClientRect();
    const s = fit * view.zoom;
    const i = Math.round(view.cx + (e.clientX - r.left - size / 2) / s);
    const j = Math.round(view.cy + (size / 2 - (e.clientY - r.top)) / s);
    return [i, j];
  };
  const onMove = (e: React.PointerEvent) => {
    if (drag.current) {
      const s = fit * view.zoom;
      setView({ ...drag.current.v, cx: drag.current.v.cx - (e.clientX - drag.current.x) / s, cy: drag.current.v.cy + (e.clientY - drag.current.y) / s });
      return;
    }
    const [i, j] = pixelAt(e);
    const v = opts.grid[j]?.[i];
    if (i < 0 || j < 0 || i >= w || j >= h) { setHover(""); return; }
    setHover(`pixel (${i}, ${j}): ${v == null ? "no data" : `${fmtv(v)} ${p.unit}`}${p.masked[j]?.[i] ? " · masked" : ""}`);
  };

  const zoomBy = (f: number) => setView({ ...view, zoom: Math.min(16, Math.max(1, view.zoom * f)) });
  const onKey = (e: React.KeyboardEvent) => {
    const step = e.shiftKey ? 5 : 1;
    const k = e.key;
    if (k === "ArrowLeft") setView({ ...view, cx: view.cx - step });
    else if (k === "ArrowRight") setView({ ...view, cx: view.cx + step });
    else if (k === "ArrowUp") setView({ ...view, cy: view.cy + step });
    else if (k === "ArrowDown") setView({ ...view, cy: view.cy - step });
    else if (k === "+" || k === "=") zoomBy(1.5);
    else if (k === "-") zoomBy(1 / 1.5);
    else if (k === "0") setView(home);
    else if ((k === "b" || k === " ") && p.frames.length > 1) { setBlink(false); setFi((f) => 1 - f); }
    else return;
    e.preventDefault();
  };

  const exportPng = async () => {
    // Full cutout at 16 screen pixels per SPHEREx pixel, whatever the current zoom.
    const S = 16, pad = 14, imgW = w * S, imgH = h * S;
    const lines = [
      `${p.title} — ${p.frames[Math.min(fi, p.frames.length - 1)].label}`,
      ...Object.entries(p.meta).map(([k, v]) => `${k}: ${v}`),
      `Display: ${stretchLabel}; limits ${fmtv(lo)} to ${fmtv(hi)} ${p.unit}; colour map ${cmap}; nearest-neighbour, no smoothing.`,
      `Overlays: ${showAp ? `aperture r=${p.rAp} px (cyan), sky annulus ${p.annulus[0]}–${p.annulus[1]} px (yellow, dashed)` : "none"}${showMask ? "; masked pixels hatched" : ""}; grey = no data.`,
    ];
    const W = Math.max(imgW + 2 * pad, 760);
    const H = pad + imgH + 52 + lines.length * 16 + 34;
    const c = document.createElement("canvas");
    c.width = W; c.height = H;
    const ctx = c.getContext("2d")!;
    ctx.fillStyle = "#0b1020"; ctx.fillRect(0, 0, W, H);
    ctx.save(); ctx.translate((W - imgW) / 2, pad);
    draw(ctx, imgW, imgH, S, (w - 1) / 2, (h - 1) / 2, opts);
    ctx.restore();
    colourbar(ctx, (W - imgW) / 2, pad + imgH + 8, imgW, 10, cmap, stEff, lo, hi, p.unit, stretchLabel, "#e6ebf5");
    ctx.fillStyle = "#e6ebf5"; ctx.font = "12px system-ui, sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "top";
    let yy = pad + imgH + 52;
    for (const l of lines) { ctx.fillText(l, pad, yy, W - 2 * pad); yy += 16; }
    ctx.fillStyle = "#93a0bd"; ctx.fillText(CREDIT, pad, yy + 8, W - 2 * pad);
    const blob: Blob = await new Promise((res) => c.toBlob((b) => res(b!), "image/png"));
    const tagged = await addPngText(blob, {
      Title: lines[0], Source: "NASA SPHEREx via NASA/IPAC IRSA", Software: "HIPPARCHUS (team AETHENOVA)",
      Copyright: CREDIT, Description: lines.slice(1).join("\n"),
    });
    download(tagged, `${p.fileStem}_${p.frames[Math.min(fi, p.frames.length - 1)].label.replace(/[^A-Za-z0-9_.-]+/g, "_")}.png`);
  };

  const maps = p.kind === "flux" ? SEQUENTIAL_MAPS : DIVERGING_MAPS;
  return (
    <div className="pv" ref={wrap}>
      <canvas ref={cv} className="pv-canvas" style={{ width: size, height: size }} tabIndex={0} role="img"
        aria-label={`${p.title}, ${p.frames[Math.min(fi, p.frames.length - 1)].label}. ${w} by ${h} native pixels.`}
        aria-describedby={helpId}
        onKeyDown={onKey}
        onPointerDown={(e) => { (e.target as Element).setPointerCapture(e.pointerId); drag.current = { x: e.clientX, y: e.clientY, v: view }; }}
        onPointerUp={() => { drag.current = null; }}
        onPointerMove={onMove} onPointerLeave={() => setHover("")} />
      <canvas ref={cb} className="pv-bar" style={{ width: size, height: 44 }} aria-hidden="true" />
      <p className="pv-read mono" aria-live="off">{hover || `${p.frames[Math.min(fi, p.frames.length - 1)].label} · zoom ×${view.zoom.toFixed(1)}`}</p>
      <p id={helpId} className="sr-only">Arrow keys pan, plus and minus zoom, 0 resets{p.frames.length > 1 ? ", B switches between the two epochs" : ""}.</p>
      <div className="pv-tools">
        {p.frames.length > 1 && (
          <>
            {p.frames.map((f, k) => (
              <button key={f.label} aria-pressed={fi === k && !blink} onClick={() => { setBlink(false); setFi(k); }}>{k === 0 ? "Earlier" : "Later"}</button>
            ))}
            <button aria-pressed={blink} onClick={() => setBlink(!blink)}>{blink ? "Stop blink" : "Blink"}</button>
          </>
        )}
        <button onClick={() => zoomBy(1.5)} aria-label="Zoom in">+</button>
        <button onClick={() => zoomBy(1 / 1.5)} aria-label="Zoom out">−</button>
        <button onClick={() => setView(home)}>Reset</button>
        <button onClick={exportPng}>Export PNG</button>
      </div>
      <details className="pv-opts">
        <summary>Display: {stretchLabel}, {maps.find((m) => m.id === cmap)?.label}</summary>
        <div className="row">
          {p.kind === "flux" && (
            <label>Stretch<select value={st} onChange={(e) => setSt(e.target.value as Stretch)}>
              {STRETCHES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}</select></label>
          )}
          <label>Limits<select value={clip} onChange={(e) => setClip(e.target.value as Clip)}>
            {CLIPS[p.kind].map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}</select></label>
          <label>Colour map<select value={cmap} onChange={(e) => setCmap(e.target.value)}>
            {maps.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}</select></label>
          <label className="check"><input type="checkbox" checked={showAp} onChange={(e) => setShowAp(e.target.checked)} /> Aperture and sky annulus</label>
          <label className="check"><input type="checkbox" checked={showMask} onChange={(e) => setShowMask(e.target.checked)} /> Hatch masked pixels</label>
        </div>
        <p className="hint">
          Limits {fmtv(lo)} to {fmtv(hi)} {p.unit}{p.frames.length > 1 ? ", shared by both epochs" : ""}; flagged pixels are left out of the limits.
          Cyan: photometry aperture, r = {p.rAp} px ({(p.rAp * p.pixelArcsec).toFixed(1)}″). Yellow dashed: sky annulus {p.annulus[0]}–{p.annulus[1]} px.
          One square = one SPHEREx pixel ({p.pixelArcsec.toFixed(2)}″); zooming only enlarges it.
        </p>
      </details>
    </div>
  );
}
