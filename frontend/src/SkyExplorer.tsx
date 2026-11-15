import { useEffect, useRef, useState } from "react";
import { ExploreMeta, HipsLayer, HipsStatus, Resolved, get } from "./api";
import { ALADIN_VERSION, AladinNS, loadAladin } from "./aladin";

// All-Sky Explorer: pan and zoom the official SPHEREx HiPS from IRSA, with
// clearly labelled context surveys, find a position by name or coordinates,
// and hand that position to the real archive search of the main view.

const JUDGE_FALLBACK = "https://evantampa129.github.io/HIPPARCHUS-SpaceApps2026/";
// Frames 50 and 51 of the SPHEREx cube are the blank dichroic channels (see its properties file).
const BLANK_FRAMES = new Set([50, 51]);

// Accepts "76.956 30.401", "76.956, +30.401", "05:07:49.56 +30:24:05.1",
// "05 07 49.56 +30 24 05.1" or "5h07m49.6s +30d24m05s". Returns degrees, or null.
export function parseCoords(text: string): { ra: number; dec: number } | null {
  const t = text.trim().replace(/,/g, " ");
  const dec2 = /^([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)$/.exec(t);
  if (dec2) {
    const ra = Number(dec2[1]), dec = Number(dec2[2]);
    return ra >= 0 && ra < 360 && dec >= -90 && dec <= 90 ? { ra, dec } : null;
  }
  const sex = /^(\d{1,2})[h:\s]\s*(\d{1,2})[m:\s]\s*(\d{1,2}(?:\.\d+)?)s?\s+([+-]?)(\d{1,2})[d°:\s]\s*(\d{1,2})['m:\s]\s*(\d{1,2}(?:\.\d+)?)(?:"|s|″)?$/i.exec(t);
  if (!sex) return null;
  const [h, m, s, sg, d, dm, ds] = [Number(sex[1]), Number(sex[2]), Number(sex[3]), sex[4], Number(sex[5]), Number(sex[6]), Number(sex[7])];
  if (h > 23 || m > 59 || s >= 60 || d > 90 || dm > 59 || ds >= 60) return null;
  const ra = 15 * (h + m / 60 + s / 3600);
  const dec = (sg === "-" ? -1 : 1) * (d + dm / 60 + ds / 3600);
  return Math.abs(dec) <= 90 ? { ra, dec } : null;
}

const hms = (ra: number) => {
  const h = ra / 15, hh = Math.floor(h), mm = Math.floor((h - hh) * 60), ss = ((h - hh) * 60 - mm) * 60;
  return `${String(hh).padStart(2, "0")}h${String(mm).padStart(2, "0")}m${ss.toFixed(2).padStart(5, "0")}s`;
};
const dms = (dec: number) => {
  const s = dec < 0 ? "−" : "+", a = Math.abs(dec), d = Math.floor(a), m = Math.floor((a - d) * 60), x = ((a - d) * 60 - m) * 60;
  return `${s}${String(d).padStart(2, "0")}°${String(m).padStart(2, "0")}′${x.toFixed(1).padStart(4, "0")}″`;
};

interface Props {
  meta: ExploreMeta | null;
  frame: number;
  onFrame: (f: number) => void;
  onExplore: (ra: number, dec: number) => void;
}

export default function SkyExplorer({ meta, frame, onFrame, onExplore }: Props) {
  const div = useRef<HTMLDivElement>(null);
  const al = useRef<AladinNS>(null);
  const A = useRef<AladinNS>(null);
  const sxLayer = useRef<AladinNS>(null);
  const [hips, setHips] = useState<HipsStatus | null>(null);
  const [hipsErr, setHipsErr] = useState<string | null>(null);
  const [layerId, setLayerId] = useState<string>("spherex");
  const [viewer, setViewer] = useState<"loading" | "ready" | "error">("loading");
  const [viewerErr, setViewerErr] = useState("");
  const [centre, setCentre] = useState({ ra: 76.956, dec: 30.401 });
  const [cursor, setCursor] = useState<{ ra: number; dec: number } | null>(null);
  const [fov, setFov] = useState(1.5);
  const [query, setQuery] = useState("");
  const [lookup, setLookup] = useState<{ busy: boolean; msg: string; bad: boolean; res?: Resolved }>({ busy: false, msg: "", bad: false });

  const judge = meta?.judge_mode_url ?? hips?.judge_mode_url ?? JUDGE_FALLBACK;
  const layers: HipsLayer[] = hips?.layers ?? [];
  const layer = layers.find((l) => l.id === layerId);
  const sx = layers.find((l) => l.id === "spherex");
  const channels = hips?.channels_um ?? [];

  // 1. Ask our backend which HiPS trees IRSA is serving right now.
  useEffect(() => {
    get<HipsStatus>("/explore/hips", {})
      .then((h) => { setHips(h); if (!h.spherex_available) setLayerId(h.layers.find((l) => l.status.ok)?.id ?? "spherex"); })
      .catch((e) => setHipsErr(String((e as Error).message)));
  }, []);

  // 2. Load Aladin Lite and create the viewer once.
  useEffect(() => {
    let dead = false;
    loadAladin().then((Ans) => {
      if (dead || !div.current) return;
      A.current = Ans;
      const a = Ans.aladin(div.current, {
        // No usage logging to CDS, and an IRSA-hosted start layer instead of the CDS default,
        // so the page talks only to IRSA (and jsDelivr once).
        log: false, survey: "https://irsa.ipac.caltech.edu/data/hips/CDS/2MASS/Color",
        fov: 1.5, target: "76.956 30.401", cooFrame: "ICRSd", projection: "SIN",
        showReticle: true, showZoomControl: false, showFullscreenControl: false, showLayersControl: false,
        showGotoControl: false, showSimbadPointerControl: false, showCooGridControl: false, showSettingsControl: false,
        showShareControl: false, showProjectionControl: false, showFrame: false, showCooLocation: false,
        showContextMenu: false, showStatusBar: false,
      });
      al.current = a;
      a.on("positionChanged", (p: { ra: number; dec: number }) => setCentre({ ra: p.ra, dec: p.dec }));
      a.on("mouseMove", (p: { ra: number; dec: number }) => p && isFinite(p.ra) && setCursor({ ra: p.ra, dec: p.dec }));
      a.on("zoomChanged", (f: number) => setFov(f));
      setViewer("ready");
    }).catch((e) => { if (!dead) { setViewer("error"); setViewerErr(String((e as Error).message ?? e)); } });
    return () => { dead = true; };
  }, []);

  // 3. Footprints of the three demonstration targets: the 0.05° cutout we analyse,
  // and the photometry aperture (2 px = 12.3″).
  useEffect(() => {
    const a = al.current, Ans = A.current;
    if (viewer !== "ready" || !a || !meta) return;
    const ov = Ans.graphicOverlay({ name: "Analysed cutouts", color: "#ffc857", lineWidth: 2 });
    a.addOverlay(ov);
    const cat = Ans.catalog({ name: "Demo targets", shape: "circle", sourceSize: 16, color: "#7fd4ff", displayLabel: true, labelColumn: "name", labelColor: "#7fd4ff", labelFont: "13px sans-serif" });
    a.addCatalog(cat);
    const half = meta.cutout_size_deg / 2;
    for (const t of meta.targets) {
      const c = Math.cos((t.dec * Math.PI) / 180);
      ov.add(Ans.polygon([[t.ra - half / c, t.dec - half], [t.ra + half / c, t.dec - half], [t.ra + half / c, t.dec + half], [t.ra - half / c, t.dec + half]]));
      ov.add(Ans.circle(t.ra, t.dec, (meta.aperture_radius_px * meta.native_pixel_arcsec) / 3600, { color: "#7fd4ff" }));
      cat.addSources([Ans.source(t.ra, t.dec, { name: t.name })]);
    }
  }, [viewer, meta]);

  // 4. Base layer: the SPHEREx cube (one channel at a time) or a context survey.
  useEffect(() => {
    const a = al.current, Ans = A.current;
    if (viewer !== "ready" || !a || !layer) return;
    const isSx = layer.kind === "spherex";
    const hl = Ans.imageHiPS(layer.url, {
      name: layer.label, imgFormat: isSx ? "png" : "jpeg",
      successCallback: (h: AladinNS) => { if (isSx) { sxLayer.current = h; showFrame(h, frame); } },
    });
    a.setBaseImageLayer(hl);
    // Zooming in far past the HiPS pixel only enlarges it; we stop at ~1.5′ wide.
    try { a.setFoVRange(isSx ? 0.025 : 0.005, 180); } catch { /* older API */ }
    if (!isSx) sxLayer.current = null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewer, layerId, hips]);

  // Aladin picks a cube frame from a frequency; like IRSA's own page, we pass the
  // middle of the frame's slot between em_max and em_min.
  const showFrame = (h: AladinNS, f: number) => {
    const p = sx?.properties ?? {};
    const c = 299792458, depth = Number(p.hips_cube_depth ?? 102);
    const fLo = c / Number(p.em_max ?? 5.009e-6), fHi = c / Number(p.em_min ?? 7.43e-7);
    try { h.setFrequency({ value: fLo + ((f + 0.5) / depth) * (fHi - fLo), unit: "Hz" }); } catch { /* not a cube */ }
  };
  useEffect(() => { if (sxLayer.current) showFrame(sxLayer.current, frame); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [frame]);

  const goto = (ra: number, dec: number) => {
    setCentre({ ra, dec });
    al.current?.gotoRaDec(ra, dec);
  };
  const pan = (dRa: number, dDec: number) => {
    const step = fov / 4;
    const dec = Math.max(-90, Math.min(90, centre.dec + dDec * step));
    const ra = (((centre.ra + (dRa * step) / Math.max(Math.cos((dec * Math.PI) / 180), 0.05)) % 360) + 360) % 360;
    goto(ra, dec);
  };
  const zoom = (f: number) => { const n = Math.min(180, Math.max(0.025, fov * f)); setFov(n); al.current?.setFov(n); };

  const find = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    const c = parseCoords(q);
    if (c) { goto(c.ra, c.dec); setLookup({ busy: false, bad: false, msg: `Coordinates read as RA ${c.ra.toFixed(5)}°, Dec ${c.dec.toFixed(5)}° (ICRS).` }); return; }
    if (/^[\d\s.:+-]+$/.test(q)) { setLookup({ busy: false, bad: true, msg: "Those look like coordinates but are out of range or malformed. Use RA 0–360° and Dec −90…+90°, or hh:mm:ss ±dd:mm:ss." }); return; }
    setLookup({ busy: true, bad: false, msg: `Asking CDS Sesame for “${q}”…` });
    try {
      const r = await get<Resolved>("/explore/resolve", { name: q });
      goto(r.ra, r.dec);
      setLookup({ busy: false, bad: false, res: r, msg: `${r.oname ?? r.query} (${r.otype ?? "object"}): RA ${r.ra.toFixed(5)}°, Dec ${r.dec.toFixed(5)}°. ${r.note}` });
    } catch (err) {
      setLookup({ busy: false, bad: true, msg: String((err as Error).message) });
    }
  };

  const band = Math.floor(frame / 17) + 1, ch = (frame % 17) + 1;
  const sxDown = hips && !hips.spherex_available;

  return (
    <section className="card skyx" aria-labelledby="sky-h">
      <h2 id="sky-h">All-Sky Explorer</h2>

      {hipsErr && (
        <p className="err-inline" role="alert">Could not ask the backend which sky layers are available ({hipsErr}).
          The static <a href={judge} target="_blank" rel="noreferrer">Judge Mode</a> page shows every result without the live services.</p>
      )}
      {sxDown && sx && (
        <p className="err-inline" role="alert">
          <b>The SPHEREx sky layer is unavailable right now.</b> {sx.status.message} We are not showing a substitute for it.
          {layer && layer.kind === "context" ? <> The view below is a <b>context layer, not SPHEREx</b>.</> : null}{" "}
          The static <a href={judge} target="_blank" rel="noreferrer">Judge Mode</a> page has all results and images without needing IRSA.
        </p>
      )}

      <div className="sky-layout">
        <div className="sky-view">
          <div ref={div} className="aladin" role="application" aria-label="Interactive sky map. Use the buttons below to pan and zoom with the keyboard." />
          {viewer === "loading" && <div className="sky-overlay" role="status">Loading the sky viewer (Aladin Lite {ALADIN_VERSION})…</div>}
          {viewer === "error" && (
            <div className="sky-overlay err-inline" role="alert">
              The sky viewer could not be loaded ({viewerErr}). The coordinate and name tools on the right still work.
              Results without any live service: <a href={judge} target="_blank" rel="noreferrer">Judge Mode</a>.
            </div>
          )}
          <div className="sky-nav" role="group" aria-label="Pan and zoom">
            <button onClick={() => pan(0, 1)} aria-label="Pan north">N</button>
            <button onClick={() => pan(1, 0)} aria-label="Pan east">E</button>
            <button onClick={() => pan(-1, 0)} aria-label="Pan west">W</button>
            <button onClick={() => pan(0, -1)} aria-label="Pan south">S</button>
            <button onClick={() => zoom(0.5)} aria-label="Zoom in">+</button>
            <button onClick={() => zoom(2)} aria-label="Zoom out">−</button>
            {meta?.targets.map((t) => <button key={t.id} className="preset" onClick={() => { goto(t.ra, t.dec); zoom(0.25 / fov); }}>{t.name}</button>)}
          </div>
        </div>

        <div className="sky-side">
          <div className="readout" aria-live="polite">
            <div><span>Centre</span><b className="mono">{centre.ra.toFixed(5)}°, {centre.dec >= 0 ? "+" : ""}{centre.dec.toFixed(5)}°</b>
              <small className="mono">{hms(centre.ra)} {dms(centre.dec)}</small></div>
            <div aria-live="off"><span>Cursor</span><b className="mono">{cursor ? `${cursor.ra.toFixed(5)}°, ${cursor.dec >= 0 ? "+" : ""}${cursor.dec.toFixed(5)}°` : "—"}</b></div>
            <div><span>Field</span><b className="mono">{fov >= 1 ? `${fov.toFixed(2)}°` : `${(fov * 60).toFixed(1)}′`}</b></div>
          </div>

          <form onSubmit={find} className="find">
            <label htmlFor="sky-q">Name or coordinates (ICRS)</label>
            <div className="row">
              <input id="sky-q" value={query} onChange={(e) => setQuery(e.target.value)} maxLength={64}
                placeholder="RW Aur  ·  76.956 30.401  ·  05:07:49.6 +30:24:05" autoComplete="off" />
              <button type="submit" disabled={lookup.busy}>Go</button>
            </div>
            {lookup.msg && <p className={lookup.bad ? "err-inline" : "hint"} role={lookup.bad ? "alert" : "status"}>{lookup.msg}</p>}
            <p className="hint">Names go through our backend to CDS Sesame (SIMBAD first), with a 6 s timeout and a cache.</p>
          </form>

          <button className="primary wide" onClick={() => onExplore(Number(centre.ra.toFixed(6)), Number(centre.dec.toFixed(6)))}>
            Explore this position →
          </button>
          <p className="hint">Runs the real IRSA SPHEREx search for the map centre in the Analysis view. Nothing is simulated.</p>

          <fieldset className="layers">
            <legend>Sky layer</legend>
            {(layers.length ? layers : []).map((l) => (
              <label key={l.id} className={`check ${l.kind}`}>
                <input type="radio" name="layer" value={l.id} checked={layerId === l.id} disabled={!l.status.ok}
                  onChange={() => setLayerId(l.id)} />
                <span>{l.label}{!l.status.ok ? ` — unavailable${l.status.http_status ? ` (HTTP ${l.status.http_status})` : ""}` : ""}</span>
              </label>
            ))}
            {!hips && !hipsErr && <p className="hint" role="status">Checking which layers IRSA is serving…</p>}
          </fieldset>

          {layer?.kind === "spherex" && channels.length > 0 && (
            <div className="frame">
              <label htmlFor="sx-frame">SPHEREx channel (cube frame)</label>
              <select id="sx-frame" value={frame} onChange={(e) => onFrame(Number(e.target.value))}>
                {[1, 2, 3, 4, 5, 6].map((b) => (
                  <optgroup key={b} label={`Band ${b} (detector D${b})`}>
                    {channels.slice((b - 1) * 17, b * 17).map((um, k) => {
                      const f = (b - 1) * 17 + k;
                      return <option key={f} value={f} disabled={BLANK_FRAMES.has(f)}>D{b} ch {k + 1} — {um.toFixed(3)} µm{BLANK_FRAMES.has(f) ? " (blank dichroic channel)" : ""}</option>;
                    })}
                  </optgroup>
                ))}
              </select>
              <p className="hint">Showing D{band} channel {ch}, {channels[frame]?.toFixed(3)} µm. Channel centres from {hips?.channels_source}.</p>
            </div>
          )}
        </div>
      </div>

      <div className="legend">
        <h3>Legend: what you are looking at</h3>
        <ul>
          <li><span className="sw sx" aria-hidden="true" /> <b>SPHEREx (NASA/IPAC IRSA)</b>: the official DR1 all-sky HiPS cube{sx?.properties?.hips_release_date ? ` (released ${sx.properties.hips_release_date.slice(0, 10)})` : ""}.
            It is a <b>visual mosaic</b> of many exposures, one frame per channel: <b>not a time series</b>, and HIPPARCHUS never measures anything on it.
            Its pixels are {sx?.hips_pixel_arcsec ? `${sx.hips_pixel_arcsec.toFixed(1)}″` : "12.9″"}; SPHEREx's own pixels are {hips?.native_pixel_arcsec ?? 6.15}″.
            Zooming in further only enlarges the pixels; there is no finer detail in the data.</li>
          <li><span className="sw ctx" aria-hidden="true" /> <b>Context layers (2MASS, AllWISE, DSS2) are not SPHEREx.</b> Their pixels are 0.8–1.6″, much sharper than SPHEREx:
            two stars that are separate here (for example RW Aur A and B, 1.6″ apart) fall in the same 6.15″ SPHEREx pixel.</li>
          <li><span className="sw tgt" aria-hidden="true" /> Cyan circle: a demonstration target and our photometry aperture (2 px = 12.3″ radius).
            <span className="sw cut" aria-hidden="true" /> Yellow square: the 0.05° (3′) cutout we download for each epoch.</li>
          <li>Positions are ICRS degrees. Preset positions are approximate (epoch ~2025.9) and only centre the cutout.</li>
        </ul>
        <p className="hint credit">
          {layer ? `Layer credit: ${layer.credit}.` : ""} Viewer: Aladin Lite {ALADIN_VERSION} © CDS, Université de Strasbourg (GPL-3.0), loaded from jsDelivr and checked against a pinned hash.
          Name resolver: CDS Sesame / SIMBAD.
        </p>
      </div>
    </section>
  );
}
