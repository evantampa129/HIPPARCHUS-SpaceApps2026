import { useEffect, useMemo, useState } from "react";
import { API, Analysis, Epoch, Observations, Pair, Robustness, Target, get } from "./api";

// Plain-language meaning of every refusal code the backend can return. Shown
// next to the counts, so a refusal is an explanation and not just a number.
const REFUSAL_TEXT: Record<string, string> = {
  wavelength_mismatch:
    "The star fell at a different wavelength in each visit. SPHEREx's filters change wavelength across the detector, so a brightness difference could just be the star's spectrum.",
  flagged_pixels:
    "Pixels on the star are flagged by the SPHEREx pipeline (saturation, persistence, cosmic rays...). Their values cannot be trusted.",
  off_edge: "The star sits too close to the edge of the image to measure it.",
  nan_pixels: "Some pixels on the star have no data.",
  bad_variance: "The noise estimate on the star is missing, so no significance can be computed.",
  bad_wavelength: "The wavelength lookup at the star returned a non-physical value.",
  different_detector: "The two images come from different detectors, which cover different wavelengths.",
};

const DETECTORS = ["SPHEREx-D1", "SPHEREx-D2", "SPHEREx-D3", "SPHEREx-D4", "SPHEREx-D5", "SPHEREx-D6"];

const fmt = (x: number | null | undefined, d = 2) => (x == null || !isFinite(x) ? "n/a" : x.toFixed(d));
const doiUrl = (doi: string) => `https://doi.org/${doi}`;

export default function App() {
  const [targets, setTargets] = useState<Target[]>([]);
  const [ra, setRa] = useState("76.956");
  const [dec, setDec] = useState("30.401");
  const [detector, setDetector] = useState("SPHEREx-D1");
  const [obs, setObs] = useState<Observations | null>(null);
  const [res, setRes] = useState<Analysis | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [epochSel, setEpochSel] = useState<string | null>(null);
  const [pairSel, setPairSel] = useState<Pair | null>(null);

  // Presets come from the backend, so the list and its explanations live in one place.
  useEffect(() => { get<Target[]>("/targets", {}).then(setTargets).catch(() => setTargets([])); }, []);

  // The stability report exists only for the presets (it is precomputed).
  const preset = targets.find((t) => String(t.ra) === ra && String(t.dec) === dec && t.detector === detector);

  const pick = (t: Target) => {
    setRa(String(t.ra)); setDec(String(t.dec)); setDetector(t.detector);
    setObs(null); setRes(null); setPairSel(null); setEpochSel(null); setError(null);
  };

  const search = async () => {
    setBusy("Asking the IRSA archive which SPHEREx exposures cover this position..."); setError(null);
    setObs(null); setRes(null); setPairSel(null); setEpochSel(null);
    try { setObs(await get<Observations>("/observations", { ra, dec })); }
    catch (e) { setError(String((e as Error).message)); }
    finally { setBusy(null); }
  };

  const analyze = async () => {
    setBusy("Downloading cutouts, checking quality and comparing epochs. The first run of a target can take a few minutes.");
    setError(null); setPairSel(null); setEpochSel(null);
    try {
      const r = await get<Analysis>("/analyze", { ra, dec, detector });
      setRes(r);
      // Open the strongest comparison first, if there is any.
      const best = [...r.comparisons].sort((a, b) => Math.abs(b.significance ?? 0) - Math.abs(a.significance ?? 0))[0];
      setPairSel(best ?? null);
    } catch (e) { setError(String((e as Error).message)); }
    finally { setBusy(null); }
  };

  return (
    <div className="page">
      <header>
        {/* Text-only header on purpose: the HIPPARCHUS logo is AI-generated, and at
            header size its required "AI-generated" watermark would be unreadable. */}
        <div>
          <h1>HIPPARCHUS</h1>
          <p className="sub">Compare real SPHEREx observations of the same star across time, and refuse when the comparison is not valid.</p>
          <p className="team">Team AETHENOVA · The universe is never still.</p>
        </div>
      </header>

      <section className="card controls">
        <div className="presets">
          {targets.map((t) => (
            <button key={t.id} className="preset" onClick={() => pick(t)} title={t.why}>{t.name}</button>
          ))}
        </div>
        <div className="row">
          <label>RA (deg)<input value={ra} onChange={(e) => setRa(e.target.value)} inputMode="decimal" /></label>
          <label>Dec (deg)<input value={dec} onChange={(e) => setDec(e.target.value)} inputMode="decimal" /></label>
          <label>Detector
            <select value={detector} onChange={(e) => setDetector(e.target.value)}>
              {DETECTORS.map((d) => <option key={d}>{d}</option>)}
            </select>
          </label>
          <button onClick={search} disabled={!!busy}>1. Search archive</button>
          <button onClick={analyze} disabled={!!busy} className="primary">2. Analyze epochs</button>
        </div>
        <p className="hint">Preset positions are approximate and only centre the cutout; the star is measured in the images.</p>
      </section>

      {busy && <div className="card busy">{busy}</div>}
      {error && <div className="card err">{error}</div>}

      {obs && <ObsPanel obs={obs} />}
      {res && (
        <>
          <Summary r={res} />
          <Timeline r={res} selected={epochSel} onSelect={setEpochSel} />
          <Playback r={res} selected={epochSel} onSelect={setEpochSel} />
          <Pairs r={res} selected={pairSel} onSelect={setPairSel} />
          {pairSel && <PairView r={res} p={pairSel} />}
          {preset && <Stability id={preset.id} />}
        </>
      )}

      <footer>
        Team AETHENOVA. Data: NASA SPHEREx via NASA/IPAC Infrared Science Archive (IRSA). Independent student project for the NASA Space Apps
        Challenge 2026; not an official NASA product. Images are shown as measured; flagged pixels are drawn in dark red (grey on difference maps).
      </footer>
    </div>
  );
}

function Badge({ status }: { status: string }) {
  // The badge is how the user knows whether they are looking at a live archive
  // answer or at a listing saved earlier while IRSA was unreachable.
  return <span className={`badge ${status}`}>{status === "live" ? "LIVE archive" : status === "cached" ? "CACHED listing (archive offline)" : status.toUpperCase()}</span>;
}

function ObsPanel({ obs }: { obs: Observations }) {
  return (
    <section className="card">
      <h2>Archive search <Badge status={obs.archive_status} /></h2>
      <p>{obs.observations.length} SPHEREx science exposures cover this position{obs.queried_at ? ` (queried ${obs.queried_at})` : ""}.</p>
      <div className="dets">
        {Object.entries(obs.per_detector).sort().map(([d, n]) => <span key={d} className="det">{d}: {n}</span>)}
      </div>
      <ul className="src">
        {obs.sources.map((s) => (
          <li key={s.release}>
            <a href={s.url} target="_blank" rel="noreferrer">{s.release} query</a>{" "}
            <span className="mono">sha256 {s.sha256.slice(0, 12)}…</span>
          </li>
        ))}
      </ul>
      {obs.errors.length > 0 && <p className="warn">Archive errors: {obs.errors.join("; ")}</p>}
    </section>
  );
}

function Summary({ r }: { r: Analysis }) {
  const changed = r.comparisons.filter((c) => c.changed).length;
  return (
    <section className="card">
      <h2>{r.detector} at RA {r.ra}, Dec {r.dec} <Badge status={r.archive_status} /></h2>
      <div className="stats">
        <div><b>{r.n_epochs}</b><span>epochs downloaded</span></div>
        <div><b>{r.n_usable}</b><span>passed quality checks</span></div>
        <div><b>{r.comparisons.length}</b><span>valid comparisons</span></div>
        <div><b>{changed}</b><span>changes ≥ 5σ</span></div>
        <div><b>{r.null_tests.length}</b><span>same-visit null tests</span></div>
      </div>
      {r.comparisons.length === 0 && (
        <p className="refuse">
          <b>No valid comparison.</b> HIPPARCHUS will not compare these observations, for the reasons below. That is a result, not a failure.
        </p>
      )}
      <ul className="refusals">
        {Object.entries(r.refused_pairs).map(([code, n]) => (
          <li key={code}><b>{n} pairs refused: {code.replace(/_/g, " ")}.</b> {REFUSAL_TEXT[code] ?? ""}</li>
        ))}
      </ul>
      <a className="btn" href={`${API}/analysis/${r.analysis_id}/evidence.json`}>Download evidence (JSON)</a>
      <span className="hint"> Every identifier, checksum, setting and number behind this page.</span>
    </section>
  );
}

function Timeline({ r, selected, onSelect }: { r: Analysis; selected: string | null; onSelect: (id: string) => void }) {
  // Epochs placed on a real time axis (MJD), so gaps between visits are visible.
  const W = 900, H = 70, pad = 20;
  const t0 = Math.min(...r.epochs.map((e) => e.mjd)), t1 = Math.max(...r.epochs.map((e) => e.mjd));
  const x = (m: number) => pad + ((m - t0) / Math.max(t1 - t0, 1)) * (W - 2 * pad);
  const byDate = (m: number) => new Date((m - 40587) * 86400000).toISOString().slice(0, 10);
  return (
    <section className="card">
      <h2>Timeline</h2>
      <svg viewBox={`0 0 ${W} ${H}`} className="timeline" role="img" aria-label="Epochs over time">
        <line x1={pad} x2={W - pad} y1={35} y2={35} className="axis" />
        {r.epochs.map((e, i) => (
          <circle key={e.obs_id} cx={x(e.mjd)} cy={35 + ((i % 3) - 1) * 8} r={selected === e.obs_id ? 7 : 5}
            className={e.usable ? "ok" : "bad"} onClick={() => onSelect(e.obs_id)}>
            <title>{`${e.obs_id}  ${e.date_obs}  λ=${fmt(e.wavelength_um, 3)} µm  ${e.usable ? "usable" : "rejected"}`}</title>
          </circle>
        ))}
        <text x={pad} y={H - 4} className="tick">{byDate(t0)}</text>
        <text x={W - pad} y={H - 4} className="tick" textAnchor="end">{byDate(t1)}</text>
      </svg>
      <p className="hint"><span className="dot ok" /> usable <span className="dot bad" /> rejected by the quality checks. Click an epoch to inspect it.</p>
    </section>
  );
}

function Playback({ r, selected, onSelect }: { r: Analysis; selected: string | null; onSelect: (id: string) => void }) {
  const usable = useMemo(() => r.epochs.filter((e) => e.usable), [r]);
  const [playing, setPlaying] = useState(false);
  const ep: Epoch | undefined = r.epochs.find((e) => e.obs_id === selected) ?? usable[0] ?? r.epochs[0];

  // Chronological playback steps through usable epochs only: a rejected frame
  // would flash a saturated or flagged image and look like a real change.
  useEffect(() => {
    if (!playing || usable.length === 0) return;
    const id = setInterval(() => {
      const i = usable.findIndex((e) => e.obs_id === ep?.obs_id);
      onSelect(usable[(i + 1) % usable.length].obs_id);
    }, 700);
    return () => clearInterval(id);
  }, [playing, usable, ep, onSelect]);

  if (!ep) return null;
  return (
    <section className="card epoch">
      <h2>Epoch {ep.obs_id}</h2>
      <div className="split">
        <img src={`${API}/analysis/${r.analysis_id}/epoch/${ep.obs_id}.png`} alt={`SPHEREx cutout ${ep.obs_id}`} className="sky" />
        <div>
          <button onClick={() => setPlaying(!playing)} disabled={usable.length < 2}>{playing ? "Pause" : "Play usable epochs in time order"}</button>
          <table className="kv"><tbody>
            <tr><td>Observed (UTC)</td><td>{ep.date_obs}</td></tr>
            <tr><td>MJD</td><td>{fmt(ep.mjd, 5)}</td></tr>
            <tr><td>Wavelength at star</td><td>{fmt(ep.wavelength_um, 4)} µm (channel width {fmt(ep.bandwidth_um, 4)} µm)</td></tr>
            <tr><td>Status</td><td className={ep.usable ? "okt" : "badt"}>{ep.usable ? "usable" : "rejected"}</td></tr>
            <tr><td>Release</td><td><a href={doiUrl(ep.provenance.obs.doi)} target="_blank" rel="noreferrer">{ep.provenance.obs.release} (doi:{ep.provenance.obs.doi})</a></td></tr>
            <tr><td>Source file</td><td><a href={ep.provenance.cutout.url} target="_blank" rel="noreferrer">IRSA cutout</a> <span className="mono">sha256 {ep.provenance.cutout.sha256.slice(0, 12)}…</span></td></tr>
          </tbody></table>
          {ep.issues.length > 0 && (
            <ul className="issues">{ep.issues.map((i, k) => <li key={k} className={i.severity}>{i.severity === "reject" ? "✗" : "!"} {i.message}</li>)}</ul>
          )}
        </div>
      </div>
    </section>
  );
}

function Pairs({ r, selected, onSelect }: { r: Analysis; selected: Pair | null; onSelect: (p: Pair) => void }) {
  const rows = [...r.comparisons].sort((a, b) => Math.abs(b.significance ?? 0) - Math.abs(a.significance ?? 0));
  if (rows.length === 0 && r.null_tests.length === 0) return null;
  return (
    <section className="card">
      <h2>Valid comparisons</h2>
      <table className="pairs">
        <thead><tr><th>Earlier</th><th>Later</th><th>Δt (days)</th><th>λ (µm)</th><th>Flux change</th><th>Significance</th><th>Centroid shift</th><th>Control star</th></tr></thead>
        <tbody>
          {[...rows, ...r.null_tests].map((p) => (
            <tr key={p.pair_id} onClick={() => onSelect(p)} className={selected?.pair_id === p.pair_id ? "sel" : ""}>
              <td className="mono">{p.a}</td><td className="mono">{p.b}</td>
              <td>{fmt(p.dt_days, 1)}{p.dt_days < 0.5 ? " (null test)" : ""}</td>
              <td>{fmt(p.lambda_a_um, 3)} / {fmt(p.lambda_b_um, 3)}</td>
              <td>{fmt(p.delta_flux, 1)} ± {fmt(p.delta_flux_err, 1)}</td>
              <td className={p.changed ? "badt" : ""}>{fmt(p.significance, 1)}σ</td>
              <td>{fmt(p.centroid_shift_arcsec.total, 2)}″</td>
              <td>{p.control_star ? `${fmt(p.control_star.significance, 1)}σ` : "none"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="hint">Flux is the aperture sum above the local sky, in MJy/sr summed over pixels, after removing the pipeline's zodiacal-light model.</p>
    </section>
  );
}

function PairView({ r, p }: { r: Analysis; p: Pair }) {
  const [showB, setShowB] = useState(false);
  const [blink, setBlink] = useState(true);
  // Blink: alternate the two epochs at the same place on screen. The eye picks
  // up a change in brightness or position far better than in a side-by-side view.
  useEffect(() => {
    if (!blink) return;
    const id = setInterval(() => setShowB((s) => !s), 600);
    return () => clearInterval(id);
  }, [blink]);
  const base = `${API}/analysis/${r.analysis_id}/pair/${p.pair_id}`;
  return (
    <section className="card">
      <h2>Comparison {p.a} → {p.b}</h2>
      <div className="grid4">
        <figure>
          <img src={`${base}/${showB ? "b" : "a"}.png`} alt="blink" className="sky" />
          <figcaption>
            Blink: <b>{showB ? p.b : p.a}</b>{" "}
            <button onClick={() => setBlink(!blink)}>{blink ? "Stop" : "Blink"}</button>
          </figcaption>
        </figure>
        <figure><img src={`${base}/diff.png`} alt="difference" className="sky" /><figcaption>Difference (later − earlier), red = brighter</figcaption></figure>
        <figure><img src={`${base}/z.png`} alt="significance" className="sky" /><figcaption>Significance map, scale ±5σ</figcaption></figure>
        <div className="verdict">
          <p className={p.changed ? "badt big" : "okt big"}>{p.changed ? `Brightness changed at ${fmt(p.significance, 1)}σ` : `No significant change (${fmt(p.significance, 1)}σ)`}</p>
          <p>Flux {fmt(p.flux_a.flux, 1)} ± {fmt(p.flux_a.flux_err, 1)} → {fmt(p.flux_b.flux, 1)} ± {fmt(p.flux_b.flux_err, 1)}</p>
          <p>Ratio later / earlier: ×{fmt(p.flux_ratio, 2)}</p>
          <p>Time between epochs: {fmt(p.dt_days, 1)} days</p>
          {p.control_star ? (
            <p className={Math.abs(p.control_star.significance ?? 99) < 5 ? "okt" : "badt"}>
              Control star at pixel ({p.control_star.x}, {p.control_star.y}): ×{fmt(p.control_star.ratio, 2)}, {fmt(p.control_star.significance, 1)}σ
              {Math.abs(p.control_star.significance ?? 99) < 5 ? " — stable, so the calibration of the two epochs agrees." : " — it changed too: treat the target's change with caution."}
            </p>
          ) : <p className="warn">No control star in the cutout: this result rests on the formal errors only.</p>}
          <p>Centroid shift: ΔRA {fmt(p.centroid_shift_arcsec.dra, 2)}″, ΔDec {fmt(p.centroid_shift_arcsec.ddec, 2)}″ (pixel = 6.15″)</p>
          <p className="hint">A measured change is not a discovery. It needs independent confirmation, e.g. from other surveys or follow-up observations.</p>
        </div>
      </div>
    </section>
  );
}

// Heatmap of the result under other reasonable analysis settings (mask as
// flagged, no extra calibration). Green: the claim still holds; red: it does
// not; grey: some pairs could not be measured with that setting.
function Stability({ id }: { id: string }) {
  const [d, setD] = useState<Robustness | null>(null);
  useEffect(() => { setD(null); get<Robustness>(`/robustness/${id}`, {}).then(setD).catch(() => setD(null)); }, [id]);
  if (!d) return null;
  const first = d.claims[0]?.claim;
  const cells = d.stability.filter((c) => c.mask === "as_flagged" && c.calibration === "none");
  const cell = (r: number, an: [number, number]) =>
    cells.find((c) => c.r_ap === r && c.annulus[0] === an[0] && c.annulus[1] === an[1]);
  return (
    <section className="card">
      <h2>How stable is the conclusion?</h2>
      <p className="hint">{d.source}. Rule: {d.settings.rule}</p>
      <ul>
        {d.claims.map((c) => (
          <li key={c.claim}><b>{c.verdict}</b>: {c.claim} (holds in {c.n_holding} of {c.n_checks} checks)</li>
        ))}
        {d.claims.length === 0 && <li>{d.verdict}</li>}
      </ul>
      {cells.length > 0 && first && (
        <table className="heat">
          <thead>
            <tr><th>aperture radius (px) \ sky annulus (px)</th>
              {d.settings.annuli_px.map((an) => <th key={an.join("-")}>{an[0]}–{an[1]}</th>)}</tr>
          </thead>
          <tbody>
            {d.settings.apertures_px.map((r) => (
              <tr key={r}><th>{r}{r === 2 ? " (used)" : ""}</th>
                {d.settings.annuli_px.map((an) => {
                  const c = cell(r, an);
                  const ok = c?.claim_holds ? c.claim_holds[first] : null;
                  return (
                    <td key={an.join("-")} className={ok === null || ok === undefined ? "na" : ok ? "ok" : "no"}
                        title={c ? `${c.n_pairs} pairs; strongest ratio ${c.strongest_ratio?.toFixed(2)}; max |sigma| ${c.max_abs_sig?.toFixed(1)}` : ""}>
                      {c?.strongest_ratio != null ? `×${c.strongest_ratio.toFixed(2)}` : "–"}
                      <br /><small>{c?.max_abs_sig != null ? `${c.max_abs_sig.toFixed(1)}σ` : ""}</small>
                    </td>);
                })}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {first && <p className="hint">Cells test: “{first}”. Value: strongest flux ratio and largest |significance| over the pairs.</p>}
      {d.systematic_floor != null && (
        <p className="hint">Field stars scatter by {(100 * d.systematic_floor).toFixed(1)}% between epochs; this is added as a
          calibration error in the stability checks. These labels follow a fixed rule and are not probabilities.</p>
      )}
    </section>
  );
}
