import { useEffect, useMemo, useState } from "react";
import { Analysis, HipsStatus, SpecPoint, Spectrum, Target, get } from "./api";
import { lut } from "./imaging";

// Spectral Explorer: where in wavelength each single SPHEREx exposure caught the
// star, and what it measured there. Every point is one exposure; nothing here
// is stacked or co-added, so the time axis is a real time axis.

const mjdToDate = (m: number) => new Date((m - 40587) * 86400000).toISOString().slice(0, 10);

function ticks(lo: number, hi: number, n = 5): number[] {
  const span = hi - lo || Math.abs(hi) || 1;
  const step0 = span / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => span / s <= n) ?? 10 * mag;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Number(v.toPrecision(10)));
  return out;
}

const pad = (lo: number, hi: number, f = 0.06): [number, number] => {
  const d = (hi - lo) || Math.abs(hi) * 0.1 || 1;
  return [lo - d * f, hi + d * f];
};

// Colour by date with cividis, which stays readable for colour-blind viewers.
const CIV = lut("cividis");
const civ = (t: number) => { const k = Math.round(Math.min(1, Math.max(0, t)) * 230) * 3; return `rgb(${CIV[k]},${CIV[k + 1]},${CIV[k + 2]})`; };

interface Frame { W: number; H: number; L: number; R: number; T: number; B: number }
const FR: Frame = { W: 640, H: 300, L: 70, R: 14, T: 14, B: 46 };

function Axes({ xr, yr, xt, yt, xlab, ylab, xfmt }: { xr: [number, number]; yr: [number, number]; xt: number[]; yt: number[]; xlab: string; ylab: string; xfmt: (v: number) => string }) {
  const X = (v: number) => FR.L + ((v - xr[0]) / (xr[1] - xr[0])) * (FR.W - FR.L - FR.R);
  const Y = (v: number) => FR.H - FR.B - ((v - yr[0]) / (yr[1] - yr[0])) * (FR.H - FR.T - FR.B);
  return (
    <g className="axes">
      <rect x={FR.L} y={FR.T} width={FR.W - FR.L - FR.R} height={FR.H - FR.T - FR.B} className="frame" />
      {xt.map((v) => <g key={`x${v}`}><line x1={X(v)} x2={X(v)} y1={FR.H - FR.B} y2={FR.H - FR.B + 5} /><text x={X(v)} y={FR.H - FR.B + 18} textAnchor="middle">{xfmt(v)}</text></g>)}
      {yt.map((v) => <g key={`y${v}`}><line x1={FR.L - 5} x2={FR.L} y1={Y(v)} y2={Y(v)} /><line x1={FR.L} x2={FR.W - FR.R} y1={Y(v)} y2={Y(v)} className="grid" /><text x={FR.L - 8} y={Y(v) + 4} textAnchor="end">{Math.abs(v) >= 1e4 ? v.toExponential(1) : v}</text></g>)}
      <text x={(FR.L + FR.W - FR.R) / 2} y={FR.H - 6} textAnchor="middle" className="lab">{xlab}</text>
      <text transform={`translate(14 ${(FR.T + FR.H - FR.B) / 2}) rotate(-90)`} textAnchor="middle" className="lab">{ylab}</text>
    </g>
  );
}

interface Props {
  res: Analysis | null;
  targets: Target[];
  busy: boolean;
  onAnalyzeTarget: (t: Target) => void;
  onOpenChannel: (frame: number) => void;
}

export default function SpectralExplorer({ res, targets, busy, onAnalyzeTarget, onOpenChannel }: Props) {
  const [spec, setSpec] = useState<Spectrum | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [channels, setChannels] = useState<{ um: number[]; source: string } | null>(null);
  const [chan, setChan] = useState<number | null>(null);
  const [unit, setUnit] = useState<"native" | "mjy">("native");
  const [sel, setSel] = useState<string | null>(null);

  useEffect(() => {
    get<HipsStatus>("/explore/hips", {}).then((h) => setChannels({ um: h.channels_um, source: h.channels_source })).catch(() => setChannels(null));
  }, []);
  useEffect(() => {
    setSpec(null); setErr(null);
    if (!res) return;
    get<Spectrum>(`/explore/spectrum/${res.analysis_id}`, {}).then(setSpec).catch((e) => setErr(String((e as Error).message)));
  }, [res]);

  const band = spec ? Number(spec.detector.replace(/\D/g, "")) : 1;
  const bandCh = channels ? channels.um.slice((band - 1) * 17, band * 17) : [];

  // Default channel: the one that holds the most usable epochs, so the band is not empty.
  const pts = spec?.points ?? [];
  useEffect(() => {
    if (!bandCh.length || !pts.length) return;
    const best = bandCh.map((c, k) => [k, pts.filter((p) => p.usable && Math.abs(p.wavelength_um - c) <= 0.5 * p.bandwidth_um).length])
      .sort((a, b) => b[1] - a[1])[0][0];
    setChan(best);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spec, channels]);

  const tol = spec?.max_dlambda_fraction ?? 0.5;
  const lc = chan != null ? bandCh[chan] : null;
  const inChan = (p: SpecPoint) => lc != null && Math.abs(p.wavelength_um - lc) <= tol * p.bandwidth_um;

  const tr = useMemo<[number, number]>(() => pts.length ? pad(Math.min(...pts.map((p) => p.mjd)), Math.max(...pts.map((p) => p.mjd))) : [0, 1], [pts]);
  const t01 = (m: number) => (m - tr[0]) / (tr[1] - tr[0] || 1);

  if (!res) {
    return (
      <section className="card" aria-labelledby="spec-h">
        <h2 id="spec-h">Spectral Explorer</h2>
        <p>The Spectral Explorer reads the per-epoch measurements of an analysis. Pick a target to analyse it (real IRSA data; the first run of a target can take a few minutes):</p>
        <div className="presets">{targets.map((t) => <button key={t.id} className="preset" disabled={busy} onClick={() => onAnalyzeTarget(t)}>{t.name}</button>)}</div>
        <WhyNotPaired tol={0.5} refused={null} />
      </section>
    );
  }

  const meas = pts.filter((p) => p.measured);
  const val = (p: SpecPoint) => (unit === "native" ? p.flux : p.flux_mjy) ?? NaN;
  const errv = (p: SpecPoint) => (unit === "native" ? p.flux_err : p.flux_err_mjy) ?? 0;
  const lamAll = pts.flatMap((p) => [p.wavelength_um - p.bandwidth_um / 2, p.wavelength_um + p.bandwidth_um / 2]);
  const lr = pts.length ? pad(Math.min(...lamAll, ...(lc ? [lc] : [])), Math.max(...lamAll, ...(lc ? [lc] : []))) : [0, 1] as [number, number];
  const fr = meas.length ? pad(Math.min(...meas.map((p) => val(p) - errv(p))), Math.max(...meas.map((p) => val(p) + errv(p)))) : [0, 1] as [number, number];
  const X1 = (m: number) => FR.L + t01(m) * (FR.W - FR.L - FR.R);
  const Y1 = (l: number) => FR.H - FR.B - ((l - lr[0]) / (lr[1] - lr[0])) * (FR.H - FR.T - FR.B);
  const X2 = (l: number) => FR.L + ((l - lr[0]) / (lr[1] - lr[0])) * (FR.W - FR.L - FR.R);
  const Y2 = (f: number) => FR.H - FR.B - ((f - fr[0]) / (fr[1] - fr[0])) * (FR.H - FR.T - FR.B);
  const medBw = pts.length ? [...pts.map((p) => p.bandwidth_um)].sort((a, b) => a - b)[Math.floor(pts.length / 2)] : 0;
  const nIn = pts.filter((p) => p.usable && inChan(p)).length;
  const unitLabel = unit === "native" ? "MJy/sr summed over aperture pixels" : "mJy in aperture (not total flux)";
  const dateTicks = ticks(tr[0], tr[1], 4);

  return (
    <section className="card" aria-labelledby="spec-h">
      <h2 id="spec-h">Spectral Explorer · {spec?.detector ?? res.detector} at RA {res.ra}, Dec {res.dec}</h2>
      {err && <p className="err-inline" role="alert">Could not load the per-epoch measurements: {err}</p>}
      {!spec && !err && <p role="status">Measuring each epoch…</p>}
      {spec && (
        <>
          {res.archive_status !== "live" && (
            <p className="err-inline">Archive answer: <b>{res.archive_status}</b>. {res.archive_status === "partial"
              ? "One SPHEREx release could not be queried (IRSA returned an error), so exposures from it are missing here."
              : "IRSA was unreachable; these exposures come from a listing saved earlier."}</p>
          )}
          <p className="notice"><b>Single exposures only.</b> Each point is one SPHEREx exposure of {spec.detector}, measured on its own pixels
            (aperture {spec.aperture_radius_px} px, sky annulus {spec.sky_annulus_px.join("–")} px). Nothing is co-added, so the time axis is real.
            {" "}{pts.length - meas.length} of {pts.length} epochs were rejected by the quality checks and have no flux.</p>

          <div className="row spec-controls">
            <label>Channel ({spec.detector}, centres from {channels?.source ?? "IRSA HiPS"})
              <select value={chan ?? ""} onChange={(e) => setChan(e.target.value === "" ? null : Number(e.target.value))} disabled={!bandCh.length}>
                <option value="">none</option>
                {bandCh.map((um, k) => <option key={k} value={k}>ch {k + 1} — {um.toFixed(3)} µm</option>)}
              </select>
            </label>
            <fieldset className="units"><legend>Flux unit</legend>
              <label className="check"><input type="radio" name="unit" checked={unit === "native"} onChange={() => setUnit("native")} /> MJy/sr summed over pixels (as measured)</label>
              <label className="check"><input type="radio" name="unit" checked={unit === "mjy"} onChange={() => setUnit("mjy")} /> mJy (converted)</label>
            </fieldset>
            {chan != null && <button onClick={() => onOpenChannel((band - 1) * 17 + chan)}>Show this channel on the sky →</button>}
          </div>
          <p className="hint">{unit === "native" ? spec.units.native : spec.units.converted}</p>

          <figure className="plot">
            <svg viewBox={`0 0 ${FR.W} ${FR.H}`} role="img" aria-label={`Wavelength at the star versus observation date for ${pts.length} exposures.`}>
              <Axes xr={tr} yr={lr} xt={dateTicks} yt={ticks(lr[0], lr[1])} xlab="Observation date (UTC)" ylab="Wavelength at star (µm)" xfmt={mjdToDate} />
              {lc != null && (
                <g className="chan">
                  <rect x={FR.L} width={FR.W - FR.L - FR.R} y={Y1(lc + tol * medBw)} height={Y1(lc - tol * medBw) - Y1(lc + tol * medBw)} />
                  <text x={FR.L + 6} y={Y1(lc + tol * medBw) - 4}>ch {chan! + 1}: {lc.toFixed(3)} µm ± half a channel</text>
                </g>
              )}
              {pts.map((p) => (
                <g key={p.obs_id} className={`pt ${sel === p.obs_id ? "sel" : ""}`} onClick={() => setSel(p.obs_id)}>
                  <title>{`${p.obs_id}\n${p.date_obs}\nλ = ${p.wavelength_um.toFixed(4)} µm, channel width ${p.bandwidth_um.toFixed(4)} µm\n${p.usable ? "usable" : "rejected: " + p.reasons.join(", ")}`}</title>
                  <line x1={X1(p.mjd)} x2={X1(p.mjd)} y1={Y1(p.wavelength_um - p.bandwidth_um / 2)} y2={Y1(p.wavelength_um + p.bandwidth_um / 2)} className="bw" />
                  {p.usable
                    ? <circle cx={X1(p.mjd)} cy={Y1(p.wavelength_um)} r={inChan(p) ? 5.5 : 4} className={inChan(p) ? "ok in" : "ok"} />
                    : <path d={`M${X1(p.mjd) - 4},${Y1(p.wavelength_um) - 4}l8,8m0,-8l-8,8`} className="rej" />}
                </g>
              ))}
            </svg>
            <figcaption>Where in wavelength each exposure caught the star. Vertical bar: the channel width at the star (the bandpass, not an error).
              ● usable, ✕ rejected; larger dots fall within half a channel of the selected channel ({nIn} usable exposures).</figcaption>
          </figure>

          <figure className="plot">
            <svg viewBox={`0 0 ${FR.W} ${FR.H}`} role="img" aria-label={`Flux versus wavelength for ${meas.length} measured exposures, in ${unitLabel}.`}>
              <Axes xr={lr} yr={fr} xt={ticks(lr[0], lr[1])} yt={ticks(fr[0], fr[1])} xlab="Wavelength at star (µm)" ylab={unit === "native" ? "Flux (MJy/sr × pixels)" : "Flux in aperture (mJy)"} xfmt={(v) => String(v)} />
              {lc != null && <rect className="chanv" x={X2(lc - tol * medBw)} width={X2(lc + tol * medBw) - X2(lc - tol * medBw)} y={FR.T} height={FR.H - FR.T - FR.B} />}
              {meas.map((p) => {
                const x = X2(p.wavelength_um), y = Y2(val(p)), c = civ(t01(p.mjd));
                return (
                  <g key={p.obs_id} className={`pt ${sel === p.obs_id ? "sel" : ""}`} onClick={() => setSel(p.obs_id)}>
                    <title>{`${p.obs_id}  ${p.date_obs}\nλ = ${p.wavelength_um.toFixed(4)} µm\nflux = ${val(p).toPrecision(5)} ± ${errv(p).toPrecision(2)} ${unitLabel}`}</title>
                    <line x1={X2(p.wavelength_um - p.bandwidth_um / 2)} x2={X2(p.wavelength_um + p.bandwidth_um / 2)} y1={y} y2={y} className="bw" />
                    <line x1={x} x2={x} y1={Y2(val(p) - errv(p))} y2={Y2(val(p) + errv(p))} className="eb" />
                    <circle cx={x} cy={y} r={inChan(p) ? 5.5 : 4} fill={c} className="fp" />
                  </g>
                );
              })}
            </svg>
            <div className="datebar" aria-hidden="true">
              <span>{mjdToDate(tr[0])}</span>
              <i style={{ background: `linear-gradient(90deg, ${[0, 0.25, 0.5, 0.75, 1].map(civ).join(", ")})` }} />
              <span>{mjdToDate(tr[1])}</span>
            </div>
            <figcaption>Each measured exposure at the wavelength where it saw the star. Vertical bars: 1σ formal error. Horizontal dashed bars:
              channel width (bandpass). Colour: date, from early (dark) to late (yellow). A spread here mixes the star's spectrum with any change in time.</figcaption>
          </figure>

          <WhyNotPaired tol={tol} refused={spec.refused_pairs} nPairs={spec.comparisons.length} />

          <details className="epochs">
            <summary>All {pts.length} exposures (table)</summary>
            <div className="scroll">
              <table className="pairs">
                <thead><tr><th>Exposure</th><th>Detector</th><th>Date (UTC)</th><th>λ at star (µm)</th><th>Channel width (µm)</th><th>Flux ({unitLabel})</th><th>Status</th></tr></thead>
                <tbody>
                  {pts.map((p) => (
                    <tr key={p.obs_id} className={sel === p.obs_id ? "sel" : ""} onClick={() => setSel(p.obs_id)}>
                      <td className="mono">{p.obs_id}</td><td>{p.detector}</td><td>{p.date_obs.replace("T", " ").slice(0, 19)}</td>
                      <td>{p.wavelength_um.toFixed(4)}</td><td>{p.bandwidth_um.toFixed(4)}</td>
                      <td>{p.measured ? `${val(p).toPrecision(5)} ± ${errv(p).toPrecision(2)}` : "—"}</td>
                      <td className={p.usable ? "okt" : "badt"}>{p.usable ? "usable" : `rejected: ${p.reasons.join(", ").replace(/_/g, " ")}`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </section>
  );
}

function WhyNotPaired({ tol, refused, nPairs }: { tol: number; refused: Record<string, number> | null; nPairs?: number }) {
  return (
    <aside className="why" aria-labelledby="why-h">
      <h3 id="why-h">Why two exposures cannot always be paired</h3>
      <ul>
        <li><b>The filter changes across the detector.</b> SPHEREx uses linear variable filters: each column of a detector sees a different
          wavelength. Every visit points slightly differently, so the same star lands on a different column and is measured at a different wavelength.</li>
        <li><b>A star's brightness depends on wavelength.</b> Two exposures at different wavelengths can differ even if the star did not change at all.
          So we only compare two exposures from the <b>same detector</b> whose wavelengths at the star differ by at most <b>{tol} of a channel width</b>{" "}
          (in the top plot: both inside the same shaded band).</li>
        <li><b>Different detectors cover different wavelength ranges</b> (D1 0.75–1.1 µm … D6 4.4–5.0 µm), so a D1 and a D6 exposure are never paired.</li>
        <li><b>Flagged pixels</b> (saturation, cosmic rays, persistence…) on the star make an exposure unusable, whatever its wavelength.</li>
        <li>Two dichroic channels of the all-sky cube are blank, and the edges of each band overlap the next; we never mix bands.</li>
      </ul>
      {refused && (
        <p>For this target: {nPairs ?? 0} pairs passed. Refused: {Object.entries(refused).map(([k, n]) => `${n} for ${k.replace(/_/g, " ")}`).join("; ") || "none"}
          {" "}(a pair can be refused for more than one reason).</p>
      )}
    </aside>
  );
}
