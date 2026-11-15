"""Track B validation: follow a KNOWN asteroid across real SPHEREx exposures.

Writes submission/evidence/motion_check.json and report/figures/motion_check.png.

Object: (216) Kleopatra, a main-belt asteroid (V ~ 12.8 in June 2025). We chose
it because Horizons puts it at 114-121 deg solar elongation in mid-June 2025,
inside the band SPHEREx surveys, at a brightness that should be well detected
but not saturated, and at high galactic latitude (b ~ +53 deg, few stars).
This is a test of the pipeline against a body whose orbit is known to far
better than our pixels. It is not a search, and no new object is claimed.

Steps
 1. JPL Horizons ephemeris of the asteroid as seen FROM SPHEREx (observer
    500@-163182) and from the geocentre (500@399), at every exposure time.
 2. IRSA SIA v2: SPHEREx exposures covering the middle of the track, kept
    when they fall in the time window. One fixed-sky cutout per exposure.
 3. Blind search: detect every source in every cutout, drop sources that stay
    put, link the rest into tracks. Only afterwards is any track compared
    with Horizons.
 4. Field-star astrometric floor from the same cutouts.
 5. SIMULATED movers injected into the real cutouts (recovery) and linking
    on time-shuffled real data and on pure-noise fields (false positives).
"""

import hashlib
import json
import platform
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hipparchus import archive, cutouts, quality  # noqa: E402
from hipparchus import motion as M  # noqa: E402

warnings.simplefilter("ignore")
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "submission" / "evidence" / "motion_check.json"
FIG = ROOT / "report" / "figures" / "motion_check.png"

HORIZONS_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
OBJECT = {"name": "(216) Kleopatra", "horizons_command": "216;"}
SPHEREX_CENTER = "500@-163182"   # Horizons ID of the SPHEREx spacecraft
GEO_CENTER = "500@399"
# A 3.3-day stretch with seven visits across all six detectors (found from the
# exposure list of a track point; see "search_log" in the JSON).
WINDOW_MJD = (60843.40, 60846.70)

# Search settings, fixed before looking at any track.
NSIGMA = 5.0
STATIC_RADIUS = 6.0       # arcsec, about one pixel
V_MIN, V_MAX = 1.5, 120.0  # arcsec/hour
MIN_DT_STATIC = STATIC_RADIUS / V_MIN  # hours; slower movers would look static
LINK_TOL = 12.0           # arcsec, two pixels
MIN_VISITS = 3
ORDER = 2                 # position vs time: quadratic over a few days
MATCH_RADIUS = 12.0       # arcsec: a detection "is" the asteroid within 2 px of Horizons
# The SPHEREx pipeline sets OUTLIER on pixels that disagree with the other
# exposures of the same sky. A moving body disagrees by definition: in this
# window 8-14 pixels on Kleopatra carry it in nearly every exposure. Masking
# them (as quality.BAD_PLANES does for static targets) erases the asteroid,
# so for Track B we keep OUTLIER pixels and mask every other bad plane.
MOTION_KEEP_PLANES = {"OUTLIER"}
SB_IDENT_URL = "https://ssd-api.jpl.nasa.gov/sb_ident.api"
SIA_CACHE = archive.DATA_DIR / "cache" / "sia"


def _get(url, params, timeout=300, tries=6, wait=20):
    last = None
    for k in range(tries):
        try:
            r = httpx.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            last = str(e)
        time.sleep(wait * (k + 1))
    raise RuntimeError(f"{url}: {last}")


def horizons(command, center, mjds):
    """Astrometric RA/Dec (ICRF), rates, V, distance at each MJD (UTC)."""
    rows, urls = [], []
    for k in range(0, len(mjds), 40):
        chunk = mjds[k:k + 40]
        p = {"format": "json", "COMMAND": f"'{command}'", "EPHEM_TYPE": "OBSERVER",
             "CENTER": f"'{center}'", "TLIST": " ".join(f"{m:.8f}" for m in chunk),
             "TLIST_TYPE": "MJD", "TIME_TYPE": "UT", "QUANTITIES": "'1,3,9,20,23'",
             "ANG_FORMAT": "DEG", "CSV_FORMAT": "YES", "EXTRA_PREC": "YES", "OBJ_DATA": "NO"}
        r = _get(HORIZONS_URL, p, timeout=120)
        urls.append(str(r.request.url))
        res = r.json()["result"]
        if "$$SOE" not in res:
            raise RuntimeError("Horizons returned no ephemeris: " + res[:300])
        body = res.split("$$SOE")[1].split("$$EOE")[0].strip().splitlines()
        for m, line in zip(chunk, body):
            c = [x.strip() for x in line.split(",")]
            rows.append({"mjd": m, "ra": float(c[3]), "dec": float(c[4]),
                         "rate_ra_cosdec_arcsec_h": float(c[5]), "rate_dec_arcsec_h": float(c[6]),
                         "V": float(c[7]), "delta_au": float(c[9]), "elong_deg": float(c[11])})
        if len(body) != len(chunk):
            raise RuntimeError("Horizons returned a different number of rows than requested")
    return rows, urls


def horizons_range(command, center, start, stop, step):
    p = {"format": "json", "COMMAND": f"'{command}'", "EPHEM_TYPE": "OBSERVER", "CENTER": f"'{center}'",
         "START_TIME": f"'JD {start + 2400000.5}'", "STOP_TIME": f"'JD {stop + 2400000.5}'", "STEP_SIZE": f"'{step}'",
         "QUANTITIES": "'1'", "ANG_FORMAT": "DEG", "CSV_FORMAT": "YES", "OBJ_DATA": "NO"}
    r = _get(HORIZONS_URL, p, timeout=120)
    body = r.json()["result"].split("$$SOE")[1].split("$$EOE")[0].strip().splitlines()
    out = np.array([[float(x) for x in line.split(",")[3:5]] for line in body])
    return out[:, 0], out[:, 1], str(r.request.url)


def spacecraft_check(mjds, headers):
    """Compare SPHEREx position in the FITS headers with the Horizons trajectory (km)."""
    p = {"format": "json", "COMMAND": "'-163182'", "EPHEM_TYPE": "VECTORS", "CENTER": "'500@399'",
         "TLIST": " ".join(f"{m:.8f}" for m in mjds), "TLIST_TYPE": "MJD", "TIME_TYPE": "UT",
         "REF_PLANE": "FRAME", "REF_SYSTEM": "ICRF", "VEC_TABLE": "1", "CSV_FORMAT": "YES",
         "OUT_UNITS": "KM-S", "OBJ_DATA": "NO", "VEC_LABELS": "NO"}
    r = _get(HORIZONS_URL, p, timeout=120)
    body = r.json()["result"].split("$$SOE")[1].split("$$EOE")[0].strip().splitlines()
    d = []
    for line, h in zip(body, headers):
        c = [x.strip() for x in line.split(",")]
        hv = np.array([float(c[2]), float(c[3]), float(c[4])])
        d.append(float(np.linalg.norm(hv - np.array(h))))
    return d, str(r.request.url)


def sia(ra, dec):
    """SPHEREx exposures covering (ra, dec). The raw VOTable is kept, so a rerun
    while IRSA answers 502 (frequent during this work) reuses the same listing."""
    obs, src = [], []
    SIA_CACHE.mkdir(parents=True, exist_ok=True)
    for coll in archive.COLLECTIONS:
        params = {"COLLECTION": coll, "POS": f"CIRCLE {ra} {dec} 0.001", "RESPONSEFORMAT": "VOTABLE"}
        url = str(httpx.Request("GET", archive.SIA_URL, params=params).url)
        path = SIA_CACHE / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".xml")
        status = "cached"
        if path.exists():
            content = path.read_bytes()
        else:
            content = _get(archive.SIA_URL, params).content
            path.write_bytes(content)
            status = "live"
        obs += archive._parse(content, coll)
        src.append({"release": coll, "url": url, "sha256": hashlib.sha256(content).hexdigest(), "status": status})
    seen = {}
    for o in obs:
        seen.setdefault((o.obs_id, o.detector), o)
    return sorted(seen.values(), key=lambda o: (o.mjd_start, o.detector)), src


def sb_ident(mjd, ra, dec, half_width_deg=0.03):
    """Known small bodies within a box at (ra, dec), from JPL's identification API.

    Geocentric (MPC code 500): the API does not take SPHEREx as observer. The
    few-arcsec parallax is small next to the box we search.
    """
    from astropy.coordinates import Angle
    from astropy.time import Time
    ts = Time(mjd, format="mjd", scale="utc").strftime("%Y-%m-%d_%H:%M:%S")
    rah = Angle(ra, "deg").to_string(unit="hourangle", sep="-", precision=2, pad=True)
    dd = Angle(abs(dec), "deg").to_string(unit="deg", sep="-", precision=1, pad=True)
    p = {"obs-time": ts, "mpc-code": "500", "fov-ra-center": rah,
         "fov-dec-center": ("M" if dec < 0 else "") + dd, "fov-ra-hwidth": str(half_width_deg),
         "fov-dec-hwidth": str(half_width_deg), "two-pass": "true", "suppress-first-pass": "true"}
    try:
        r = _get(SB_IDENT_URL, p, timeout=120, tries=3, wait=10)
        js = r.json()
        rows = [dict(zip(js.get("fields_second", []), d)) for d in js.get("data_second_pass", [])]
        return {"url": str(r.request.url), "n_objects": len(rows), "objects": rows}
    except Exception as e:  # report the failure instead of hiding it
        return {"error": str(e)}


def motion_mask(path, ep):
    """Bad-pixel mask for Track B, and the flag names on the predicted asteroid pixels."""
    from astropy.io import fits
    with fits.open(path) as h:
        flags = h["FLAGS"].data.astype(np.int64)
        planes = quality._plane_masks(h["FLAGS"].header)
    bits = sum(b for n, b in planes.items() if n in quality.BAD_PLANES - MOTION_KEEP_PLANES)
    ny, nx = flags.shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    ap = (xx - ep.x) ** 2 + (yy - ep.y) ** 2 <= quality.APERTURE_PX ** 2
    on = {n: int(np.count_nonzero(ap & ((flags & b) != 0))) for n, b in planes.items()}
    return (flags & bits) != 0, {k: v for k, v in on.items() if v}


def sc_vector(path):
    from astropy.io import fits
    h = fits.getheader(path, "IMAGE")
    return [h["X_SC"], h["Y_SC"], h["Z_SC"]], h.get("XYZ_SC_SYSTEM")


def detect_all(epochs):
    dets = []
    for k, ep in enumerate(epochs):
        fwhm = ep.psf_fwhm_arcsec if np.isfinite(ep.psf_fwhm_arcsec) else 9.0
        dets += M.detect(ep.image, ep.variance, ep.bad, ep.wcs, ep.mjd, epoch=k, fwhm_arcsec=fwhm, nsigma=NSIGMA)
    return dets


def arrays(dets, ra0, dec0):
    t = np.array([d.mjd for d in dets])
    xi, eta = M.to_plane([d.ra for d in dets], [d.dec for d in dets], ra0, dec0)
    err = np.array([d.err_arcsec for d in dets])
    ep = np.array([d.epoch for d in dets])
    snr = np.array([d.snr for d in dets])
    return t, xi, eta, err, ep, snr


def run_link(t, xi, eta, err, ep):
    static = M.flag_static(t, xi, eta, STATIC_RADIUS, MIN_DT_STATIC)
    tracks = M.link(t, xi, eta, err, epoch=ep, v_min=V_MIN, v_max=V_MAX, tol_arcsec=LINK_TOL,
                    min_visits=MIN_VISITS, order=ORDER, exclude=static)
    return static, tracks


def field_floor(t, xi, eta, err, snr, static):
    """Per-axis scatter of static sources measured at >= 3 different visits."""
    from scipy.spatial import cKDTree
    idx = np.nonzero(static)[0]
    tree = cKDTree(np.column_stack([xi[idx], eta[idx]]))
    vis = M.visits(t)
    used = np.zeros(len(idx), bool)
    rows = []
    for a in np.argsort(-snr[idx]):
        if used[a]:
            continue
        nb = [b for b in tree.query_ball_point([xi[idx[a]], eta[idx[a]]], r=STATIC_RADIUS) if not used[b]]
        used[nb] = True
        m = idx[nb]
        if len(np.unique(vis[m])) < 3:
            continue
        rx, ry = xi[m] - np.average(xi[m], weights=1 / err[m] ** 2), eta[m] - np.average(eta[m], weights=1 / err[m] ** 2)
        n = len(m)
        rows.append({"n": n, "median_snr": float(np.median(snr[m])),
                     "rms_axis_arcsec": float(np.sqrt(np.sum(rx ** 2 + ry ** 2) / (2 * (n - 1)))),
                     "median_formal_err_arcsec": float(np.median(err[m]))})
    out = {"n_stars": len(rows)}
    for lo, hi in [(5, 10), (10, 20), (20, 50), (50, 1e9)]:
        sel = [r for r in rows if lo <= r["median_snr"] < hi]
        if sel:
            out[f"snr_{lo}_{int(hi) if hi < 1e8 else 'up'}"] = {
                "n_stars": len(sel),
                "median_rms_axis_arcsec": float(np.median([r["rms_axis_arcsec"] for r in sel])),
                "median_formal_err_arcsec": float(np.median([r["median_formal_err_arcsec"] for r in sel]))}
    bright = [r["rms_axis_arcsec"] for r in rows if r["median_snr"] >= 20]
    out["floor_arcsec_bright_snr_ge_20"] = float(np.median(bright)) if bright else None
    return out, rows


def simulated(epochs, base_dets, ra0, dec0, known, rng, snrs=(5, 7, 10, 20), speeds=(2, 5, 15, 30), trials=8):
    """SIMULATED movers in the real cutouts. Only the patch around each injected
    position is re-detected; the rest reuses the detections of the real image."""
    mjds = np.array([e.mjd for e in epochs])
    vis_all = M.visits(mjds)
    table = []
    for snr in snrs:
        for v in speeds:
            ok = n_in = fp = 0
            rate_err = []
            for _ in range(trials):
                # We anchor each mover on a real exposure time, so fast movers
                # cross the field while SPHEREx is looking, not during a gap.
                t0 = float(rng.choice(mjds))
                pa = rng.uniform(0, 2 * np.pi)
                vx, vy = v * np.cos(pa), v * np.sin(pa)
                x0, y0 = rng.uniform(-150, 150, 2)
                dets = list(base_dets)
                touched = set()
                n_frame = set()
                for k, ep in enumerate(epochs):
                    h = (ep.mjd - t0) * 24.0
                    ra, dec = M.from_plane(x0 + vx * h, y0 + vy * h, ra0, dec0)
                    px, py = (float(q) for q in ep.wcs.world_to_pixel_values(ra, dec))
                    ny, nx = ep.image.shape
                    if not (4 <= px <= nx - 5 and 4 <= py <= ny - 5):
                        continue
                    n_frame.add(vis_all[k])
                    fwhm = ep.psf_fwhm_arcsec if np.isfinite(ep.psf_fwhm_arcsec) else 9.0
                    amp = M.amplitude_for_snr(ep.variance, ep.bad, ep.wcs, px, py, snr, fwhm)
                    img = M.inject_point_source(ep.image, ep.wcs, float(ra), float(dec), amp, fwhm)
                    ys = slice(max(0, int(py) - 12), min(ny, int(py) + 13))
                    xs = slice(max(0, int(px) - 12), min(nx, int(px) + 13))
                    sub = M.detect(img[ys, xs], ep.variance[ys, xs], ep.bad[ys, xs], ep.wcs[ys, xs], ep.mjd,
                                   epoch=k, fwhm_arcsec=fwhm, nsigma=NSIGMA)
                    # Replace the real detections inside the inner part of the patch.
                    keep = [d for d in dets if not (d.epoch == k and abs(d.x - px) < 8 and abs(d.y - py) < 8)]
                    sub = [M.Detection(d.epoch, d.mjd, d.x + xs.start, d.y + ys.start, d.ra, d.dec, d.err_arcsec, d.snr, d.flux)
                           for d in sub if abs(d.x + xs.start - px) < 8 and abs(d.y + ys.start - py) < 8]
                    dets = keep + sub
                    touched.add(k)
                t, xi, eta, err, ep_, _ = arrays(dets, ra0, dec0)
                _, tracks = run_link(t, xi, eta, err, ep_)
                in_frame = len(n_frame) >= MIN_VISITS
                n_in += in_frame
                found = False
                for tr in tracks:
                    tx, ty = tr.fit.at(t[tr.members])
                    hh = (t[tr.members] - t0) * 24.0
                    sep = np.hypot(tx - (x0 + vx * hh), ty - (y0 + vy * hh))
                    if np.median(sep) < MATCH_RADIUS and not found:
                        found = True
                        r = tr.fit.rate_arcsec_per_hour
                        rate_err.append(float(np.hypot(r[0] - vx, r[1] - vy)))
                    elif not any(_near(tr, t, f) for f in known):
                        fp += 1
                ok += found and in_frame
            table.append({"label": "SIMULATED", "snr": snr, "speed_arcsec_h": v, "trials": trials,
                          "trials_with_ge_3_visits_in_frame": n_in, "recovered": ok,
                          "recovery_rate": ok / n_in if n_in else None,
                          "median_rate_error_arcsec_h": float(np.median(rate_err)) if rate_err else None,
                          "extra_tracks_not_injected_not_in_real_run": fp})
            print(f"  SIMULATED snr={snr} v={v}: {ok}/{n_in} recovered, other tracks {fp}")
    return table


def _near(tr, t, pos):
    """True if track `tr` follows the path `pos(mjd) -> (xi, eta)` within MATCH_RADIUS."""
    tx, ty = tr.fit.at(t[tr.members])
    kx, ky = pos(t[tr.members])
    return np.median(np.hypot(tx - kx, ty - ky)) < MATCH_RADIUS


def _shuffled(epochs, t, xi, eta, err, ep, rng, n):
    uniq = np.unique(ep)
    out = []
    for _ in range(n):
        perm = dict(zip(uniq, rng.permutation(uniq)))
        ts = np.array([epochs[perm[e]].mjd for e in ep])
        _, tracks = run_link(ts, xi, eta, err, ep)
        out.append(sorted(tr.n_visits for tr in tracks))
    return out


def _summary(runs, what):
    # We summarise by track length: chance alignments are almost all at the
    # 3-visit minimum, so the rate that matters depends on how long a track is.
    return {"what": what, "runs": len(runs), "visits_of_each_track_per_run": runs,
            "runs_with_any_track": sum(1 for r in runs if r),
            "runs_with_track_ge_4_visits": sum(1 for r in runs if any(v >= 4 for v in r)),
            "runs_with_track_ge_5_visits": sum(1 for r in runs if any(v >= 5 for v in r))}


def false_positive_tests(epochs, dets, ra0, dec0, rng, kleo_members, n_shuffle=20, n_noise=10):
    """Linking on data that contain no coherent mover."""
    t, xi, eta, err, ep, _ = arrays(dets, ra0, dec0)
    shuffled = _shuffled(epochs, t, xi, eta, err, ep, rng, n_shuffle)
    # We repeat the shuffle without Kleopatra's detections: its 31 points lie on
    # a short, nearly straight path, and a shuffled subset of them can still line
    # up. Without them, only chance alignments among the other transients remain.
    keep = ~np.isin(np.arange(len(t)), kleo_members)
    shuffled_wo = _shuffled(epochs, t[keep], xi[keep], eta[keep], err[keep], ep[keep], rng, n_shuffle)
    noise = []
    for _ in range(n_noise):
        nd = []
        for k, e in enumerate(epochs):
            sd = np.sqrt(np.where(np.isfinite(e.variance) & (e.variance > 0), e.variance, np.nan))
            img = np.where(np.isfinite(sd), rng.normal(0, 1, e.image.shape) * np.nan_to_num(sd), 0.0)
            fwhm = e.psf_fwhm_arcsec if np.isfinite(e.psf_fwhm_arcsec) else 9.0
            nd += M.detect(img, e.variance, e.bad, e.wcs, e.mjd, epoch=k, fwhm_arcsec=fwhm, nsigma=NSIGMA)
        tn, xn, en, rn, pn, _ = arrays(nd, ra0, dec0) if nd else ([], [], [], [], [], [])
        _, tracks = run_link(tn, xn, en, rn, pn) if len(nd) else (None, [])
        noise.append({"detections": len(nd), "tracks": len(tracks)})
    return {
        "label": "SIMULATED / permuted",
        "time_shuffled_real_data": _summary(
            shuffled, "real detections, epoch times randomly permuted; Kleopatra's own detections lose their order too"),
        "time_shuffled_real_data_without_kleopatra": _summary(
            shuffled_wo, "as above, with the detections linked to Kleopatra removed first"),
        "noise_only_fields": {
            "what": "SIMULATED Gaussian noise drawn from each real VARIANCE plane, real flag mask and WCS, no sources",
            "runs": n_noise, "per_run": noise,
            "runs_with_any_track": int(sum(1 for r in noise if r["tracks"]))},
    }


def main():
    t_start = time.time()
    rng = np.random.default_rng(216)
    log = {"started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    # 1. Coarse track over the window -> fixed field centre and cutout size.
    ra_c, dec_c, coarse_url = horizons_range(OBJECT["horizons_command"], SPHEREX_CENTER, *WINDOW_MJD, "1h")
    ra0, dec0 = M.from_plane(*[np.mean([v.min(), v.max()]) for v in M.to_plane(ra_c, dec_c, ra_c[len(ra_c) // 2], dec_c[len(dec_c) // 2])],
                             ra_c[len(ra_c) // 2], dec_c[len(dec_c) // 2])
    ra0, dec0 = float(ra0), float(dec0)
    xi_c, eta_c = M.to_plane(ra_c, dec_c, ra0, dec0)
    extent = float(np.max(np.hypot(xi_c, eta_c))) / 3600.0
    size = round(min(0.3, 2 * extent + 0.08), 3)
    print(f"field centre {ra0:.5f} {dec0:+.5f}, track half-extent {extent * 3600:.0f} arcsec, cutout {size} deg")

    # 2. Exposures covering the field centre, inside the window.
    obs, sia_sources = sia(ra0, dec0)
    obs = [o for o in obs if WINDOW_MJD[0] <= o.mjd_start <= WINDOW_MJD[1]]
    print(f"{len(obs)} exposures in the window")

    paths, metas = [], []
    for o in obs:
        c = cutouts.fetch(o.access_url, ra0, dec0, size=size)
        paths.append(c["path"])
        metas.append(c)
    first = [quality.load(p, o.obs_id, ra0, dec0) for p, o in zip(paths, obs)]
    mjds = [e.mjd for e in first]

    # 3. Ephemerides at every exposure mid-time (header MJD-AVG).
    eph_sc, urls_sc = horizons(OBJECT["horizons_command"], SPHEREX_CENTER, mjds)
    eph_geo, urls_geo = horizons(OBJECT["horizons_command"], GEO_CENTER, mjds)
    sc = [sc_vector(p) for p in paths]
    sc_diff_km, sc_url = spacecraft_check(mjds, [v for v, _ in sc])

    epochs = [quality.load(p, o.obs_id, e["ra"], e["dec"]) for p, o, e in zip(paths, obs, eph_sc)]
    flags_on_target = []
    for p, e in zip(paths, epochs):
        e.bad, on = motion_mask(p, e)
        flags_on_target.append(on)

    # 4. Blind detection and linking.
    dets = detect_all(epochs)
    t, xi, eta, err, ep, snr = arrays(dets, ra0, dec0)
    static, tracks = run_link(t, xi, eta, err, ep)
    print(f"{len(dets)} detections, {int(static.sum())} static, {len(tracks)} tracks")

    # Horizons positions on the same tangent plane.
    hx_all, hy_all = M.to_plane([e["ra"] for e in eph_sc], [e["dec"] for e in eph_sc], ra0, dec0)
    gx_all, gy_all = M.to_plane([e["ra"] for e in eph_geo], [e["dec"] for e in eph_geo], ra0, dec0)
    ep_mjd = np.array(mjds)

    def kleo_pos(tt):
        return np.interp(tt, ep_mjd[np.argsort(ep_mjd)], hx_all[np.argsort(ep_mjd)]), \
               np.interp(tt, ep_mjd[np.argsort(ep_mjd)], hy_all[np.argsort(ep_mjd)])

    track_rows, kleo = [], None
    for k, tr in enumerate(tracks):
        tx, ty = tr.fit.at(t[tr.members])
        kx, ky = kleo_pos(t[tr.members])
        med = float(np.median(np.hypot(tx - kx, ty - ky)))
        vx, vy, evx, evy = tr.fit.rate_arcsec_per_hour
        row = {"track": k, "n_detections": int(len(tr.members)), "n_visits": tr.n_visits,
               "rate_ra_cosdec_arcsec_h": vx, "rate_dec_arcsec_h": vy, "fit_rms_arcsec": tr.fit.rms_arcsec,
               "median_offset_from_horizons_arcsec": med,
               "matches_horizons": med < MATCH_RADIUS}
        if not row["matches_horizons"]:
            ra_t, dec_t = M.from_plane(*tr.fit.at(tr.fit.t_ref), ra0, dec0)
            row["position_at_t_ref"] = {"mjd": tr.fit.t_ref, "ra": float(ra_t), "dec": float(dec_t)}
            row["jpl_sb_ident_geocentric"] = sb_ident(tr.fit.t_ref, float(ra_t), float(dec_t))
        track_rows.append(row)
        if row["matches_horizons"] and kleo is None:
            kleo = tr
    print(json.dumps(track_rows, indent=1))

    # Per-exposure table: for every exposure, the detection nearest to the
    # Horizons prediction (linked or not) and why an exposure gave nothing.
    member_set = set(kleo.members.tolist()) if kleo is not None else set()
    exposures = []
    for k, (o, e, es, eg, meta) in enumerate(zip(obs, epochs, eph_sc, eph_geo, metas)):
        row = {"obs_id": o.obs_id, "release": o.release, "doi": o.doi, "detector": o.detector,
               "mjd_mid": e.mjd, "date_obs": e.date_obs, "wavelength_um": round(e.wavelength_um, 4),
               "cutout_url": meta["url"], "cutout_sha256": meta["sha256"],
               "spacecraft_xyz_km": sc[k][0], "spacecraft_frame": sc[k][1],
               "horizons_spherex": {"ra": es["ra"], "dec": es["dec"]},
               "horizons_geocentric": {"ra": eg["ra"], "dec": eg["dec"]},
               "parallax_spherex_minus_geo_arcsec": float(np.hypot(hx_all[k] - gx_all[k], hy_all[k] - gy_all[k])),
               "V_mag_horizons": es["V"], "delta_au": es["delta_au"],
               "quality_issues_at_prediction": [i.code for i in e.issues],
               "flag_pixels_at_prediction": flags_on_target[k]}
        sel = np.nonzero(ep == k)[0]
        if sel.size:
            hx, hy = hx_all[k], hy_all[k]
            d = np.hypot(xi[sel] - hx, eta[sel] - hy)
            j = sel[np.argmin(d)]
            if d.min() < MATCH_RADIUS:
                row["measured"] = {"ra": dets[j].ra, "dec": dets[j].dec, "err_arcsec": dets[j].err_arcsec,
                                   "snr": dets[j].snr, "x": dets[j].x, "y": dets[j].y,
                                   "resid_ra_cosdec_arcsec": float(xi[j] - hx), "resid_dec_arcsec": float(eta[j] - hy),
                                   "resid_vs_geocentric_arcsec": [float(xi[j] - gx_all[k]), float(eta[j] - gy_all[k])],
                                   "flagged_static": bool(static[j]), "in_linked_track": j in member_set}
        if "measured" not in row:
            row["measured"] = None
        exposures.append(row)

    m_rows = [r for r in exposures if r["measured"]]
    lk_rows = [r for r in m_rows if r["measured"]["in_linked_track"]]

    def stats(rows, key="resid"):
        if not rows:
            return None
        rx = np.array([r["measured"]["resid_ra_cosdec_arcsec"] for r in rows])
        ry = np.array([r["measured"]["resid_dec_arcsec"] for r in rows])
        return {"n": len(rows), "mean_ra_cosdec": float(rx.mean()), "mean_dec": float(ry.mean()),
                "rms_ra_cosdec": float(np.sqrt(np.mean(rx ** 2))), "rms_dec": float(np.sqrt(np.mean(ry ** 2))),
                "median_total": float(np.median(np.hypot(rx, ry))), "max_total": float(np.max(np.hypot(rx, ry)))}

    def stats_geo(rows):
        if not rows:
            return None
        g = np.array([r["measured"]["resid_vs_geocentric_arcsec"] for r in rows])
        return {"n": len(rows), "rms_ra_cosdec": float(np.sqrt(np.mean(g[:, 0] ** 2))),
                "rms_dec": float(np.sqrt(np.mean(g[:, 1] ** 2))), "median_total": float(np.median(np.hypot(g[:, 0], g[:, 1])))}

    motion = None
    if kleo is not None:
        mem = kleo.members
        f = kleo.fit
        # Same model, same epochs, Horizons positions: compares like with like.
        hx_m, hy_m = kleo_pos(t[mem])
        fh = M.fit_track(t[mem], hx_m, hy_m, np.full(len(mem), 0.1), order=f.coef_xi.size - 1, t_ref=f.t_ref, clip=1e9)
        geo_rate = horizons(OBJECT["horizons_command"], GEO_CENTER, [f.t_ref])[0][0]
        vx, vy, evx, evy = f.rate_arcsec_per_hour
        hvx, hvy, _, _ = fh.rate_arcsec_per_hour
        motion = {
            "model": f"polynomial of order {f.coef_xi.size - 1} in (RA cos Dec, Dec) vs time, tangent plane at the field centre",
            "t_ref_mjd": f.t_ref,
            "measured_rate_arcsec_h": {"ra_cosdec": vx, "dec": vy, "err_ra_cosdec": evx, "err_dec": evy,
                                       "total": float(np.hypot(vx, vy))},
            "horizons_same_model_rate_arcsec_h": {"ra_cosdec": hvx, "dec": hvy, "total": float(np.hypot(hvx, hvy))},
            "rate_difference_arcsec_h": {"ra_cosdec": vx - hvx, "dec": vy - hvy,
                                         "sigma_ra_cosdec": (vx - hvx) / evx if evx else None,
                                         "sigma_dec": (vy - hvy) / evy if evy else None},
            "horizons_geocentric_instantaneous_rate_at_t_ref_arcsec_h": {
                "ra_cosdec": geo_rate["rate_ra_cosdec_arcsec_h"], "dec": geo_rate["rate_dec_arcsec_h"]},
            "fit_rms_arcsec": f.rms_arcsec, "fit_chi2_red": f.chi2_red,
            "quadratic_coef_arcsec_h2": [float(f.coef_xi[0]), float(f.coef_eta[0])] if f.coef_xi.size == 3 else None,
            "time_span_hours": float((t[mem].max() - t[mem].min()) * 24.0),
            "note": ("fit_rms and chi2_red measure the scatter about a smooth polynomial. The asteroid's path seen from "
                     "SPHEREx also carries the orbital parallax (a few arcsec, 98-min period), which no low-order "
                     "polynomial follows; the per-exposure residuals against Horizons evaluated AT SPHEREx are the "
                     "astrometric test, the polynomial is only the motion summary."),
        }

    # 5. Field-star floor.
    floor, star_rows = field_floor(t, xi, eta, err, snr, static)
    print("floor:", json.dumps(floor))

    # 6. SIMULATED checks.
    print("SIMULATED injection-recovery ...")
    # Tracks of the real run (Kleopatra and any unexplained one) are not counted
    # again as extra tracks in every SIMULATED trial.
    known = [kleo_pos] + [tr.fit.at for tr in tracks]
    sim = simulated(epochs, dets, ra0, dec0, known, rng)
    print("SIMULATED / permuted false-positive tests ...")
    fp = false_positive_tests(epochs, dets, ra0, dec0, rng, kleo.members if kleo is not None else [])

    other = [r for r in track_rows if not r["matches_horizons"]]
    result = {
        "experiment": "Track B validation: motion of a KNOWN asteroid in real SPHEREx exposures, checked against JPL Horizons",
        "claim": "none about new objects; this checks our detection, linking and astrometry on a body with a well-known orbit",
        "object": OBJECT["name"],
        "horizons": {
            "api": HORIZONS_URL, "command": OBJECT["horizons_command"],
            "observer_spherex": SPHEREX_CENTER, "observer_geocentric": GEO_CENTER,
            "quantities": "1 (astrometric RA/Dec ICRF), 3 (rates), 9 (V), 20 (delta), 23 (elongation)",
            "time_scale": "UT, at FITS MJD-AVG (mid-exposure)",
            "query_urls_spherex": urls_sc, "query_urls_geocentric": urls_geo, "coarse_track_url": coarse_url,
            "spacecraft_check": {
                "what": "|SPHEREx position in FITS header (X_SC,Y_SC,Z_SC, geocentric) - Horizons -163182 vector|",
                "url": sc_url, "median_km": float(np.median(sc_diff_km)), "max_km": float(np.max(sc_diff_km)),
                "equivalent_arcsec_at_object": float(np.max(sc_diff_km) / (np.median([e["delta_au"] for e in eph_sc]) * 1.495978707e8) * 206264.806)},
        },
        "parallax_note": (
            "SPHEREx orbits ~650 km up (|r| ~ 7000 km from the geocentre). At the asteroid's distance this shifts it by up to "
            f"{7000 / (np.median([e['delta_au'] for e in eph_sc]) * 1.495978707e8) * 206264.806:.1f} arcsec versus a geocentric ephemeris, "
            "with a 98-minute period. We therefore compare with Horizons evaluated AT SPHEREx (500@-163182); "
            "the geocentric residuals are listed only to show the size of the effect."),
        "field": {"ra_center": ra0, "dec_center": dec0, "cutout_size_deg": size, "window_mjd": list(WINDOW_MJD)},
        "archive": {"sia_url": archive.SIA_URL, "queries": sia_sources, "n_exposures_in_window": len(obs)},
        "settings": {"nsigma": NSIGMA, "static_radius_arcsec": STATIC_RADIUS, "v_min_arcsec_h": V_MIN,
                     "v_max_arcsec_h": V_MAX, "min_dt_static_hours": MIN_DT_STATIC, "link_tol_arcsec": LINK_TOL,
                     "min_visits": MIN_VISITS, "fit_order": ORDER, "match_radius_arcsec": MATCH_RADIUS},
        "blind_search": {"n_detections": len(dets), "n_static": int(static.sum()), "tracks": track_rows,
                         "n_tracks_not_matching_kleopatra": len(other)},
        "pipeline_flag_finding": {
            "what": "exposures whose 2-px aperture at the Horizons position contains pixels flagged OUTLIER by the SPHEREx pipeline",
            "n_with_outlier": sum(1 for f in flags_on_target if f.get("OUTLIER")),
            "n_exposures": len(flags_on_target),
            "consequence": "with the static-target mask (quality.BAD_PLANES) the asteroid is masked out; Track B keeps OUTLIER pixels"},
        "exposures": exposures,
        "residuals_vs_horizons_spherex_arcsec": {"all_detections_near_prediction": stats(m_rows),
                                                 "linked_track_members": stats(lk_rows)},
        "residuals_vs_horizons_geocentric_arcsec": {"all_detections_near_prediction": stats_geo(m_rows)},
        "fitted_motion": motion,
        "astrometric_floor_field_stars": floor,
        "simulated_injection_recovery": sim,
        "simulated_false_positive_tests": fp,
        "limitations": [],
        "run": {"started_utc": log["started_utc"], "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "runtime_s": round(time.time() - t_start, 1), "python": platform.python_version(),
                "numpy": np.__version__},
    }
    result["limitations"] = limitations(result)
    OUT.write_text(json.dumps(result, indent=1, default=float))
    print(f"wrote {OUT}")
    figure(result, epochs, dets, t, xi, eta, ep, kleo, hx_all, hy_all, ra0, dec0, sim)
    print(f"wrote {FIG}  runtime {result['run']['runtime_s']} s")


def limitations(r):
    out = [
        "One asteroid, one 3.3-day window, one field. This shows the method works on a real case; it is not a survey-level completeness measurement.",
        "Kleopatra was near its stationary point (rates of a few arcsec/hour), so the real test covers slow motion only; faster motion is covered by SIMULATED injections alone.",
        "Centroids come from a fixed-width circular Gaussian, not the SPHEREx ePSF; SPHEREx pixels (6.15 arcsec) undersample the PSF, so sub-arcsec astrometry is not expected.",
        "We keep pixels flagged OUTLIER (the pipeline marks the moving asteroid with it); other bad planes stay masked. Cosmic rays or artefacts flagged only as OUTLIER can therefore become detections; the false-positive tests include this.",
        "Position errors are the formal fit errors scaled by sqrt(chi2_red); the field-star scatter is the better guide to the real floor.",
        "SIMULATED sources are Gaussians without their own photon noise, injected into real cutouts; recovery is measured on this one field and cadence.",
        "The time-shuffled test reuses this field's detections; it measures chance alignments among real transients, not every kind of false link. Such alignments are common at the 3-visit minimum, so a 3-visit track on its own is not evidence of a real mover in this field.",
        "Linking assumes a polynomial path over the window; the SPHEREx orbital parallax (a few arcsec, 98-min period) is absorbed by the link tolerance, not modelled.",
    ]
    if r["fitted_motion"] is None:
        out.insert(0, "The blind search did NOT produce a track matching Horizons; see blind_search and exposures.")
    if r["blind_search"]["n_tracks_not_matching_kleopatra"]:
        out.append("Tracks not matching Kleopatra were found. Each is listed with a JPL sb_ident lookup at its position; they are reported without interpretation (a slow 'track' can also come from a blended source whose centroid shifts with wavelength across detectors) and no new object is claimed.")
    return out


def figure(r, epochs, dets, t, xi, eta, ep, kleo, hx_all, hy_all, ra0, dec0, sim):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(13, 9.5))
    gs = fig.add_gridspec(3, 6, height_ratios=[1, 1, 1.05], hspace=0.45, wspace=0.35)
    vis = M.visits([e.mjd for e in epochs])
    # One real cutout per visit (the one with the strongest asteroid detection).
    picks = []
    for v in np.unique(vis):
        ks = [k for k in range(len(epochs)) if vis[k] == v]
        best = max(ks, key=lambda k: (r["exposures"][k]["measured"] or {}).get("snr", -1))
        picks.append(best)
    picks = picks[:6]
    for n, k in enumerate(picks):
        ax = fig.add_subplot(gs[0, n])
        e = epochs[k]
        row = r["exposures"][k]
        cx, cy = e.x, e.y
        h = 12
        ys, xs = slice(max(0, int(cy) - h), int(cy) + h + 1), slice(max(0, int(cx) - h), int(cx) + h + 1)
        img = np.where(e.bad, np.nan, e.image)[ys, xs]
        lo, hi = np.nanpercentile(img, [5, 99.5])
        ax.imshow(img, origin="lower", cmap="gray_r", vmin=lo, vmax=hi,
                  extent=(xs.start - 0.5, xs.start + img.shape[1] - 0.5, ys.start - 0.5, ys.start + img.shape[0] - 0.5))
        ax.add_patch(plt.Circle((cx, cy), 2.0, fill=False, color="tab:blue", lw=1.2))
        if row["measured"]:
            ax.plot(row["measured"]["x"], row["measured"]["y"], "x", color="tab:red", ms=7, mew=1.5)
        ax.set_title(f"{row['obs_id']}\n{row['detector'][-2:]} {row['wavelength_um']:.2f} um  MJD {e.mjd:.2f}", fontsize=7)
        ax.set_xticks([]), ax.set_yticks([])
    fig.text(0.5, 0.965, f"{r['object']} in real SPHEREx cutouts: blue circle = Horizons (from SPHEREx), red x = our detection",
             ha="center", fontsize=10)

    ax = fig.add_subplot(gs[1, 0:3])
    ax.scatter(xi, eta, s=2, c="0.8", label="all detections")
    order = np.argsort([e.mjd for e in epochs])
    ax.plot(hx_all[order], hy_all[order], "-", color="tab:blue", lw=1, label="Horizons track (from SPHEREx)")
    if kleo is not None:
        m = kleo.members
        ax.scatter(xi[m], eta[m], s=14, c=(t[m] - t[m].min()) * 24, cmap="viridis", label="linked track (blind)")
    ax.set_xlabel("RA cos Dec offset [arcsec]"), ax.set_ylabel("Dec offset [arcsec]")
    ax.invert_xaxis()
    ax.legend(fontsize=7, loc="best")
    ax.set_title("Blind linking result on the fixed field", fontsize=9)

    ax = fig.add_subplot(gs[1, 3:6])
    rows = [x for x in r["exposures"] if x["measured"]]
    if rows:
        tt = np.array([x["mjd_mid"] for x in rows])
        rx = np.array([x["measured"]["resid_ra_cosdec_arcsec"] for x in rows])
        ry = np.array([x["measured"]["resid_dec_arcsec"] for x in rows])
        er = np.array([x["measured"]["err_arcsec"] for x in rows])
        gx = np.array([x["measured"]["resid_vs_geocentric_arcsec"][0] for x in rows])
        gy = np.array([x["measured"]["resid_vs_geocentric_arcsec"][1] for x in rows])
        ax.errorbar(tt - 0.01, rx, er, fmt="o", ms=3, color="tab:red", label="RA cos Dec vs Horizons@SPHEREx")
        ax.errorbar(tt + 0.01, ry, er, fmt="s", ms=3, color="tab:purple", label="Dec vs Horizons@SPHEREx")
        ax.plot(tt, np.hypot(gx, gy), ".", color="0.6", label="|offset| vs geocentric Horizons")
    fl = r["astrometric_floor_field_stars"].get("floor_arcsec_bright_snr_ge_20")
    if fl:
        ax.axhspan(-fl, fl, color="tab:green", alpha=0.15, label=f"field-star floor +/-{fl:.2f}\"")
    ax.axhline(0, color="k", lw=0.5)
    ax.set_xlabel("MJD"), ax.set_ylabel("measured - predicted [arcsec]")
    ax.legend(fontsize=6.5, loc="best")
    ax.set_title("Astrometric residuals of the real detections", fontsize=9)

    ax = fig.add_subplot(gs[2, 0:3])
    speeds = sorted({x["speed_arcsec_h"] for x in sim})
    for s in sorted({x["snr"] for x in sim}):
        y = [next(x["recovery_rate"] for x in sim if x["snr"] == s and x["speed_arcsec_h"] == v) for v in speeds]
        ax.plot(speeds, [np.nan if v is None else v for v in y], "o-", label=f"S/N {s}")
    ax.set_xscale("log"), ax.set_ylim(-0.05, 1.05)
    ax.set_xlabel("SIMULATED speed [arcsec/hour]"), ax.set_ylabel("recovery fraction")
    ax.set_title("SIMULATED movers injected into the real cutouts", fontsize=9, color="tab:orange")
    ax.legend(fontsize=7)
    ax.text(0.02, 0.04, "SIMULATED", transform=ax.transAxes, color="tab:orange", fontsize=14, alpha=0.6, weight="bold")

    ax = fig.add_subplot(gs[2, 3:6])
    fp = r["simulated_false_positive_tests"]
    labels = ["time-shuffled\nreal data", "time-shuffled,\nKleopatra removed", "noise-only\nfields (SIMULATED)"]
    keys = ["time_shuffled_real_data", "time_shuffled_real_data_without_kleopatra", "noise_only_fields"]
    vals = [fp[k]["runs_with_any_track"] / fp[k]["runs"] for k in keys]
    vals5 = [fp[k].get("runs_with_track_ge_5_visits", 0) / fp[k]["runs"] for k in keys]
    xs = np.arange(len(keys))
    ax.bar(xs - 0.2, vals, 0.4, color="0.6", label=">= 3 visits (search threshold)")
    ax.bar(xs + 0.2, vals5, 0.4, color="tab:orange", label=">= 5 visits")
    for i, (v, w) in enumerate(zip(vals, vals5)):
        ax.text(i - 0.2, v + 0.02, f"{v:.2f}", ha="center", fontsize=7)
        ax.text(i + 0.2, w + 0.02, f"{w:.2f}", ha="center", fontsize=7)
    ax.set_xticks(xs, labels, fontsize=7)
    ax.legend(fontsize=7)
    ax.set_ylim(0, 1.05), ax.set_ylabel("fraction of runs with >= 1 track")
    ax.set_title("False-positive linking (SIMULATED / permuted)", fontsize=9, color="tab:orange")
    FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG, dpi=150, bbox_inches="tight")


if __name__ == "__main__":
    main()
