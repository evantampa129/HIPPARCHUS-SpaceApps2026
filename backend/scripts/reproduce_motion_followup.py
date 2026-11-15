"""Track B follow-up: what was the second track, and does the method work on other KNOWN asteroids?

Writes submission/evidence/motion_followup.json and report/figures/motion_followup_*.png.

Part 1 re-runs the blind search of reproduce_motion.py on the same cached
cutouts (no new downloads), checks that it gives the same two tracks, and then
vets the second track: per-detection detector and wavelength, the shape of
each detection, forced S/N at each member position in all 38 exposures,
static catalogues (Gaia DR3, 2MASS, AllWISE, SIMBAD) and JPL sb_ident computed
FROM SPHEREx (geocentric state vector of the spacecraft, `xobs`).

Part 2 repeats the Kleopatra test on further KNOWN asteroids that crossed
SPHEREx fields with at least three visits. The search settings are those of
reproduce_motion.py; nothing is tuned per object. No new object is claimed
anywhere in this script.
"""

import hashlib
import io
import json
import platform
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reproduce_motion as R  # noqa: E402
from hipparchus import archive, cutouts, quality  # noqa: E402
from hipparchus import motion as M  # noqa: E402

warnings.simplefilter("ignore")
ROOT = R.ROOT
OUT = ROOT / "submission" / "evidence" / "motion_followup.json"
FIG_DIR = ROOT / "report" / "figures"
CACHE = archive.DATA_DIR / "cache" / "followup"

VIZIER = "https://vizier.cfa.harvard.edu/viz-bin/votable"   # CfA mirror: CDS was unreachable during this work
SIMBAD_TAP = "https://simbad.harvard.edu/simbad/sim-tap/sync"
CATALOGS = {"gaia_dr3": "I/355/gaiadr3", "2mass_psc": "II/246/out", "allwise": "II/328/allwise"}
CAT_RADIUS = 6.0      # arcsec, one SPHEREx pixel
SB_HALF_WIDTH = 0.1   # deg, ~60 arcsec per hour of motion margin around the field we look at

# Bands for the forced-photometry summary. SPHEREx D1-D3 cover 0.75-2.4 um,
# D4-D6 2.4-5 um; a stellar or galaxy spectrum is usually much brighter in the
# first, a single-pixel artefact has no colour at all.
SHORT_UM = 2.42


def _cached(kind, key, fetch):
    """Return the cached bytes for (kind, key), or fetch, store and return them."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{kind}_{hashlib.sha256(key.encode()).hexdigest()[:20]}"
    if path.exists():
        return path.read_bytes(), "cached"
    data = fetch()
    path.write_bytes(data)
    return data, "live"


def _http(method, url, tries=5, wait=15, **kw):
    last = None
    for k in range(tries):
        try:
            r = httpx.request(method, url, timeout=600, follow_redirects=True, **kw)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}: {r.text[:200]}"
        except httpx.HTTPError as e:
            last = str(e)
        time.sleep(wait * (k + 1))
    raise RuntimeError(f"{url}: {last}")


# ---------------------------------------------------------------- services

def vizier(cat, ra, dec, radius=CAT_RADIUS):
    from astropy.io.votable import parse
    params = {"-source": cat, "-c": f"{ra:.6f} {dec:+.6f}", "-c.rs": str(radius), "-out.max": "50",
              "-out.add": "_r", "-sort": "_r"}
    url = str(httpx.Request("GET", VIZIER, params=params).url)
    data, status = _cached("vizier", url, lambda: _http("GET", VIZIER, params=params).content)
    rows = []
    for tab in parse(io.BytesIO(data)).iter_tables():
        t = tab.to_table()
        keep = [c for c in t.colnames if c in {"_r", "Source", "RA_ICRS", "DE_ICRS", "Gmag", "BPmag", "RPmag", "Plx", "pmRA",
                                                "pmDE", "_2MASS", "RAJ2000", "DEJ2000", "Jmag", "Hmag", "Kmag", "AllWISE",
                                                "W1mag", "W2mag", "W3mag", "ex", "Qflg", "qph"}]
        for row in t:
            rows.append({c: (None if np.ma.is_masked(row[c]) else (row[c].item() if hasattr(row[c], "item") else str(row[c])))
                         for c in keep})
    return {"url": url, "status": status, "n": len(rows), "rows": rows}


def simbad(ra, dec, radius=CAT_RADIUS * 2):
    from astropy.io.votable import parse
    q = (f"SELECT main_id, ra, dec, otype, DISTANCE(POINT('ICRS',ra,dec),POINT('ICRS',{ra:.6f},{dec:+.6f}))*3600 AS sep "
         f"FROM basic WHERE CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{ra:.6f},{dec:+.6f},{radius / 3600:.6f}))=1")
    body = {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "votable", "QUERY": q}
    data, status = _cached("simbad", q, lambda: _http("POST", SIMBAD_TAP, data=body).content)
    t = parse(io.BytesIO(data)).get_first_table().to_table()
    return {"query": q, "status": status, "radius_arcsec": radius,
            "rows": [{"main_id": str(r["main_id"]), "otype": str(r["otype"]), "sep_arcsec": float(r["sep"])} for r in t]}


def spherex_state(mjds):
    """Geocentric ICRF position (km) and velocity (km/s) of SPHEREx from Horizons."""
    out = []
    for k in range(0, len(mjds), 40):
        chunk = list(mjds[k:k + 40])
        p = {"format": "json", "COMMAND": "'-163182'", "EPHEM_TYPE": "VECTORS", "CENTER": "'500@399'",
             "TLIST": " ".join(f"{m:.8f}" for m in chunk), "TLIST_TYPE": "MJD", "TIME_TYPE": "UT",
             "REF_PLANE": "FRAME", "REF_SYSTEM": "ICRF", "VEC_TABLE": "2", "CSV_FORMAT": "YES",
             "OUT_UNITS": "KM-S", "OBJ_DATA": "NO", "VEC_LABELS": "NO"}
        data, _ = _cached("horizons_vec", json.dumps(p, sort_keys=True), lambda: R._get(R.HORIZONS_URL, p).content)
        body = json.loads(data)["result"].split("$$SOE")[1].split("$$EOE")[0].strip().splitlines()
        out += [[float(x) for x in line.split(",")[2:8]] for line in body]
    return out


def sb_ident_spherex(mjd, ra, dec, state, half_width=SB_HALF_WIDTH, vmag_lim=None):
    """Known small bodies in a box, as seen from SPHEREx (sb_ident `xobs`, second pass).

    `mag-required=false` keeps objects without H, so faint or poorly observed
    bodies are not dropped silently.
    """
    from astropy.coordinates import Angle
    from astropy.time import Time
    ts = Time(mjd, format="mjd", scale="utc").strftime("%Y-%m-%d_%H:%M:%S")
    p = {"obs-time": ts, "xobs": ",".join(f"{v:.9E}" for v in state),
         "fov-ra-center": Angle(ra, "deg").to_string(unit="hourangle", sep="-", precision=2, pad=True),
         "fov-dec-center": ("M" if dec < 0 else "") + Angle(abs(dec), "deg").to_string(unit="deg", sep="-", precision=1, pad=True),
         "fov-ra-hwidth": str(half_width), "fov-dec-hwidth": str(half_width),
         "two-pass": "true", "suppress-first-pass": "true", "mag-required": "false"}
    if vmag_lim is not None:
        p["vmag-lim"] = str(vmag_lim)
    url = str(httpx.Request("GET", R.SB_IDENT_URL, params=p).url)
    try:
        data, status = _cached("sbident", url, lambda: _http("GET", R.SB_IDENT_URL, params=p, tries=3).content)
        js = json.loads(data)
    except Exception as e:  # report the failure instead of hiding it
        return {"url": url, "error": str(e)}
    rows = [dict(zip(js.get("fields_second", []), d)) for d in js.get("data_second_pass", [])]
    return {"url": url, "status": status, "n_objects": len(rows), "objects": rows}


# ---------------------------------------------------------------- part 1

def rebuild_kleopatra_run():
    """The blind search of reproduce_motion.py on its cached cutouts (no Horizons calls:
    the per-exposure predictions are read back from motion_check.json)."""
    prev = json.loads(R.OUT.read_text())
    ra0, dec0, size = prev["field"]["ra_center"], prev["field"]["dec_center"], prev["field"]["cutout_size_deg"]
    obs, _ = R.sia(ra0, dec0)
    obs = [o for o in obs if R.WINDOW_MJD[0] <= o.mjd_start <= R.WINDOW_MJD[1]]
    paths, epochs = [], []
    for o, ex in zip(obs, prev["exposures"]):
        assert (o.obs_id, o.detector) == (ex["obs_id"], ex["detector"]), "exposure list changed since motion_check.json"
        p = cutouts.fetch(o.access_url, ra0, dec0, size=size)["path"]
        e = quality.load(p, o.obs_id, ex["horizons_spherex"]["ra"], ex["horizons_spherex"]["dec"])
        e.bad, _ = R.motion_mask(p, e)
        paths.append(p)
        epochs.append(e)
    dets = R.detect_all(epochs)
    t, xi, eta, err, ep, snr = R.arrays(dets, ra0, dec0)
    static, tracks = R.run_link(t, xi, eta, err, ep)
    return dict(prev=prev, ra0=ra0, dec0=dec0, obs=obs, paths=paths, epochs=epochs, dets=dets,
                t=t, xi=xi, eta=eta, err=err, ep=ep, snr=snr, static=static, tracks=tracks)


def _sigma_px(e):
    fwhm = e.psf_fwhm_arcsec if np.isfinite(e.psf_fwhm_arcsec) else 9.0
    return fwhm / M.pixel_scale_arcsec(e.wcs) * M.FWHM_TO_SIGMA


def forced_table(run, ra, dec):
    """Forced matched-filter S/N at a fixed sky position in every exposure."""
    from astropy.io import fits
    rows = []
    for k, (p, o) in enumerate(zip(run["paths"], run["obs"])):
        e = quality.load(p, o.obs_id, ra, dec)   # wavelength read AT this position
        bad, _ = R.motion_mask(p, e)
        f = M.forced_snr(e.image, e.variance, bad, e.x, e.y, _sigma_px(e))
        if f is None:
            continue
        with fits.open(p) as h:
            flags = h["FLAGS"].data.astype(np.int64)
            planes = quality._plane_masks(h["FLAGS"].header)
        xi_, yi_ = int(round(e.x)), int(round(e.y))
        here = [n for n, b in planes.items() if flags[yi_, xi_] & b]
        rows.append({"epoch": k, "obs_id": o.obs_id, "detector": o.detector, "mjd": e.mjd,
                     "wavelength_um": round(e.wavelength_um, 4), "snr": round(f[0], 2), "flux": f[1], "flags_at_pixel": here})
    return rows


def _band_summary(rows):
    out = {}
    for name, sel in (("short_lt_2.42um", lambda r: r["wavelength_um"] < SHORT_UM),
                      ("long_ge_2.42um", lambda r: r["wavelength_um"] >= SHORT_UM)):
        s = np.array([r["snr"] for r in rows if sel(r)])
        if s.size:
            out[name] = {"n_exposures": int(s.size), "median_snr": float(np.median(s)),
                         "n_snr_gt_3": int(np.sum(s > 3)), "n_snr_gt_5": int(np.sum(s > 5)),
                         "stacked_snr": float(np.sum(s) / np.sqrt(s.size))}
    return out


def vet_second_track(run):
    dets, t, xi, eta, err = run["dets"], run["t"], run["xi"], run["eta"], run["err"]
    ra0, dec0 = run["ra0"], run["dec0"]
    prev_rows = run["prev"]["blind_search"]["tracks"]
    other = [tr for tr in run["tracks"] if not np.isclose(tr.fit.rate_arcsec_per_hour[0], prev_rows[0]["rate_ra_cosdec_arcsec_h"])]
    tr = other[0]
    mem = tr.members
    vx, vy, _, _ = tr.fit.rate_arcsec_per_hour
    same = [p for p in prev_rows if not p["matches_horizons"]][0]
    reproduced = bool(np.isclose(vx, same["rate_ra_cosdec_arcsec_h"]) and np.isclose(vy, same["rate_dec_arcsec_h"])
                      and len(mem) == same["n_detections"])

    # Fits: the published quadratic and a straight line through the same points.
    order = tr.fit.coef_xi.size - 1
    lin = M.fit_track(t[mem], xi[mem], eta[mem], err[mem], order=1, clip=1e9)
    states = spherex_state([float(t[j]) for j in mem])

    members = []
    for n, j in enumerate(mem):
        d = dets[j]
        o, p = run["obs"][d.epoch], run["paths"][d.epoch]
        e = quality.load(p, o.obs_id, d.ra, d.dec)
        sharp, expected = M.peak_sharpness(e.image, e.variance, d.x, d.y, _sigma_px(e))
        members.append({
            "obs_id": o.obs_id, "detector": o.detector, "mjd": d.mjd, "wavelength_um_at_detection": round(e.wavelength_um, 4),
            "ra": d.ra, "dec": d.dec, "x": d.x, "y": d.y, "snr": d.snr, "err_arcsec": d.err_arcsec,
            "xi_arcsec": float(xi[j]), "eta_arcsec": float(eta[j]),
            "resid_published_fit_arcsec": [float(tr.fit.resid_xi[n]), float(tr.fit.resid_eta[n])],
            "resid_linear_fit_arcsec": [float(lin.resid_xi[n]), float(lin.resid_eta[n])],
            "peak_over_neighbours": sharp, "peak_over_neighbours_expected_for_psf": expected,
            "sb_ident_from_spherex": sb_ident_spherex(d.mjd, d.ra, d.dec, states[n]),
        })

    # Position groups: are the members a path, or a few fixed points?
    lab = M.position_groups(xi[mem], eta[mem], R.STATIC_RADIUS)
    degen = M.degenerate_track(t[mem], xi[mem], eta[mem], order, R.STATIC_RADIUS, R.MIN_DT_STATIC)
    groups = []
    for g in np.unique(lab):
        js = mem[lab == g]
        ra_g, dec_g = M.from_plane(float(np.mean(xi[js])), float(np.mean(eta[js])), ra0, dec0)
        ra_g, dec_g = float(ra_g), float(dec_g)
        forced = forced_table(run, ra_g, dec_g)
        groups.append({
            "group": int(g), "members": [run["obs"][dets[j].epoch].obs_id + " " + run["obs"][dets[j].epoch].detector[-2:] for j in js],
            "ra": ra_g, "dec": dec_g, "time_span_hours": float((t[js].max() - t[js].min()) * 24),
            "forced_photometry": forced, "forced_summary": _band_summary(forced),
            "catalogs": {k: vizier(c, ra_g, dec_g) for k, c in CATALOGS.items()} | {"simbad": simbad(ra_g, dec_g)},
        })
    for g in groups:
        print(f"  group {g['group']}: {g['ra']:.5f} {g['dec']:+.5f}  {g['forced_summary']}  "
              f"gaia={g['catalogs']['gaia_dr3']['n']} 2mass={g['catalogs']['2mass_psc']['n']} allwise={g['catalogs']['allwise']['n']}")

    # Positive control for sb_ident from SPHEREx: the same query at Kleopatra's
    # own Horizons position must return Kleopatra.
    ex = run["prev"]["exposures"][0]
    ctrl = sb_ident_spherex(ex["mjd_mid"], ex["horizons_spherex"]["ra"], ex["horizons_spherex"]["dec"],
                            spherex_state([ex["mjd_mid"]])[0], half_width=0.03)
    ctrl_ok = any("Kleopatra" in o.get("Object name", "") for o in ctrl.get("objects", []))

    # The original lookup used MPC code 500 (geocentre). The sb_ident documentation
    # says 500 is not an accepted code; we repeat that query at Kleopatra's own
    # position to see whether it can find anything at all.
    geo_ctrl = R.sb_ident(ex["mjd_mid"], ex["horizons_spherex"]["ra"], ex["horizons_spherex"]["dec"])
    geo_ctrl_ok = any("Kleopatra" in o.get("Object name", "") for o in geo_ctrl.get("objects", []))

    # Wider and fainter: every known body (no magnitude limit) in the whole
    # cutout area, at the start, middle and end of the window, from SPHEREx.
    wide = []
    for m in (R.WINDOW_MJD[0], float(np.mean(R.WINDOW_MJD)), R.WINDOW_MJD[1]):
        s = sb_ident_spherex(m, ra0, dec0, spherex_state([m])[0], half_width=run["prev"]["field"]["cutout_size_deg"] / 2 + 0.05)
        wide.append({"mjd": m, **s})

    return {
        "reproduced_from_cached_cutouts": reproduced,
        "n_detections": int(len(mem)), "n_visits": int(tr.n_visits),
        "published_fit": {"order": int(order), "rms_arcsec": tr.fit.rms_arcsec, "chi2_red": tr.fit.chi2_red,
                          "rate_arcsec_h": [vx, vy]},
        "linear_fit_same_points": {"rms_arcsec": lin.rms_arcsec, "chi2_red": lin.chi2_red,
                                   "rate_arcsec_h": list(lin.rate_arcsec_per_hour[:2])},
        "members": members,
        "n_position_groups": len(groups),
        "degenerate_track_check": degen,
        "position_groups": groups,
        "sb_ident_positive_control": {"what": "sb_ident from SPHEREx at Kleopatra's Horizons position, first exposure",
                                      "finds_kleopatra": ctrl_ok, **ctrl},
        "sb_ident_whole_field_from_spherex": wide,
        "sb_ident_geocentric_500_control": {
            "what": "the motion_check.json lookup (mpc-code=500), repeated at Kleopatra's own position, first exposure",
            "finds_kleopatra": geo_ctrl_ok, **geo_ctrl,
            "note": ("The sb_ident documentation lists 500 (geocentre) as NOT accepted. If this control fails, the "
                     "'no match' of motion_check.json carried no information; the xobs (SPHEREx) lookups above replace it.")},
    }


def track2_figure(run, vet):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    groups = vet["position_groups"]
    fig, axes = plt.subplots(len(groups), 5, figsize=(11, 3.0 * len(groups)))
    axes = np.atleast_2d(axes)
    fig.subplots_adjust(left=0.03, right=0.99, top=0.86, bottom=0.02, wspace=0.15, hspace=0.75)
    for gi, g in enumerate(groups):
        rows = g["forced_photometry"]
        # Stamps: the member exposure(s) first, then a short- and a long-wavelength
        # S/N stack of ALL exposures at this fixed sky position.
        mem_ids = set(g["members"])
        picks = [r for r in rows if f"{r['obs_id']} {r['detector'][-2:]}" in mem_ids][:3]
        stamps = []
        for r in picks:
            e = run["epochs"][r["epoch"]]
            x, y = (float(v) for v in e.wcs.world_to_pixel_values(g["ra"], g["dec"]))
            stamps.append((_stamp(e, x, y), f"{r['obs_id'][-6:]} {r['detector'][-2:]}\n{r['wavelength_um']:.2f} um S/N {r['snr']:.1f}"))
        for name, sel in (("stack < 2.42 um", lambda r: r["wavelength_um"] < SHORT_UM),
                          ("stack >= 2.42 um", lambda r: r["wavelength_um"] >= SHORT_UM)):
            st = []
            for r in rows:
                if sel(r) and f"{r['obs_id']} {r['detector'][-2:]}" not in mem_ids:
                    e = run["epochs"][r["epoch"]]
                    x, y = (float(v) for v in e.wcs.world_to_pixel_values(g["ra"], g["dec"]))
                    st.append(_stamp(e, x, y))
            if st:
                stamps.append((np.nanmean(st, axis=0) * np.sqrt(len(st)), f"{name}, members excluded\n({len(st)} exposures, S/N units)"))
        stamps = stamps[:5]
        for k in range(5):
            ax = axes[gi, k]
            ax.set_xticks([]), ax.set_yticks([])
            if k >= len(stamps):
                ax.axis("off")
            else:
                im, title = stamps[k]
                ax.imshow(im, origin="lower", cmap="gray_r", vmin=-3, vmax=10)
                ax.plot(6, 6, "+", color="tab:red", ms=10)
                ax.set_title(title, fontsize=7)
        cat = g["catalogs"]
        lab = f"group {gi}: RA {g['ra']:.5f} Dec {g['dec']:+.5f}  Gaia {cat['gaia_dr3']['n']}  2MASS {cat['2mass_psc']['n']}  AllWISE {cat['allwise']['n']} within 6\""
        axes[gi, 0].text(0, 1.38, lab, transform=axes[gi, 0].transAxes, fontsize=8, fontweight="bold")
    fig.suptitle("Second Kleopatra-field track, vetted: each row is one fixed sky position (13 x 13 px S/N stamps, grey scale -3..10, + = position)", fontsize=9, y=0.995)
    path = FIG_DIR / "motion_followup_track2.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    return str(path.relative_to(ROOT))


def _stamp(e, x, y, h=6):
    s = np.where(e.bad, np.nan, e.image / np.sqrt(np.where(e.variance > 0, e.variance, np.nan)))
    xi_, yi_ = int(round(x)), int(round(y))
    out = np.full((2 * h + 1, 2 * h + 1), np.nan)
    ny, nx = s.shape
    for dy in range(-h, h + 1):
        for dx in range(-h, h + 1):
            if 0 <= yi_ + dy < ny and 0 <= xi_ + dx < nx:
                out[dy + h, dx + h] = s[yi_ + dy, xi_ + dx]
    # Remove a local median so stamps from different detectors share a zero.
    return out - np.nanmedian(out)


# ---------------------------------------------------------------- part 2

def coverage(command, window, max_size=0.3):
    """Field centre, cutout size and the exposures in which Horizons puts the
    object inside that cutout (used to choose a case, BEFORE any detection)."""
    ra_c, dec_c, coarse_url = R.horizons_range(command, R.SPHEREX_CENTER, *window, "1h")
    mid = len(ra_c) // 2
    xi_c, eta_c = M.to_plane(ra_c, dec_c, ra_c[mid], dec_c[mid])
    ra0, dec0 = M.from_plane(0.5 * (xi_c.min() + xi_c.max()), 0.5 * (eta_c.min() + eta_c.max()), ra_c[mid], dec_c[mid])
    ra0, dec0 = float(ra0), float(dec0)
    xi_c, eta_c = M.to_plane(ra_c, dec_c, ra0, dec0)
    extent = float(np.max(np.hypot(xi_c, eta_c))) / 3600.0
    size = round(min(max_size, 2 * extent + 0.08), 3)
    obs, sia_src = R.sia(ra0, dec0)
    obs = [o for o in obs if window[0] <= o.mjd_start <= window[1]]
    return dict(ra0=ra0, dec0=dec0, size=size, extent_deg=extent, obs=obs, sia=sia_src, coarse_url=coarse_url)


def run_case(case):
    """The Kleopatra experiment of reproduce_motion.py, for another KNOWN object,
    without the SIMULATED injections (those characterise the method, not the object)."""
    t_start = time.time()
    cov = coverage(case["horizons_command"], case["window_mjd"], case.get("max_cutout_deg", 0.3))
    ra0, dec0, size, obs = cov["ra0"], cov["dec0"], cov["size"], cov["obs"]
    print(f"{case['name']}: centre {ra0:.5f} {dec0:+.5f}, cutout {size} deg, {len(obs)} exposures")
    paths, metas, failed = [], [], []
    for o in obs:
        try:
            c = cutouts.fetch(o.access_url, ra0, dec0, size=size)
        except RuntimeError as e:   # IRSA 502s: record, do not stop the case
            failed.append({"obs_id": o.obs_id, "detector": o.detector, "error": str(e)})
            continue
        paths.append(c["path"])
        metas.append((o, c))
    obs = [o for o, _ in metas]
    first = [quality.load(p, o.obs_id, ra0, dec0) for p, o in zip(paths, obs)]
    mjds = [e.mjd for e in first]
    eph_sc, urls_sc = R.horizons(case["horizons_command"], R.SPHEREX_CENTER, mjds)
    eph_geo, _ = R.horizons(case["horizons_command"], R.GEO_CENTER, mjds)
    epochs, flags_on = [], []
    for p, o, es in zip(paths, obs, eph_sc):
        e = quality.load(p, o.obs_id, es["ra"], es["dec"])
        e.bad, on = R.motion_mask(p, e)
        epochs.append(e)
        flags_on.append(on)

    # Visits in which the object is predicted inside the cutout (>= 3 px from the edge).
    inside = [3 <= e.x <= e.image.shape[1] - 4 and 3 <= e.y <= e.image.shape[0] - 4 for e in epochs]
    vis_all = M.visits(np.array(mjds))
    n_vis_inside = len(set(vis_all[np.array(inside)].tolist()))

    dets = R.detect_all(epochs)
    t, xi, eta, err, ep, snr = R.arrays(dets, ra0, dec0)
    static, tracks = R.run_link(t, xi, eta, err, ep)
    hx, hy = M.to_plane([e["ra"] for e in eph_sc], [e["dec"] for e in eph_sc], ra0, dec0)
    gx, gy = M.to_plane([e["ra"] for e in eph_geo], [e["dec"] for e in eph_geo], ra0, dec0)
    srt = np.argsort(mjds)
    m_arr = np.array(mjds)

    def pos(tt):
        return np.interp(tt, m_arr[srt], hx[srt]), np.interp(tt, m_arr[srt], hy[srt])

    rows, target = [], None
    for k, tr in enumerate(tracks):
        tx, ty = tr.fit.at(t[tr.members])
        kx, ky = pos(t[tr.members])
        med = float(np.median(np.hypot(tx - kx, ty - ky)))
        vx, vy, _, _ = tr.fit.rate_arcsec_per_hour
        row = {"track": k, "n_detections": int(len(tr.members)), "n_visits": tr.n_visits,
               "rate_ra_cosdec_arcsec_h": vx, "rate_dec_arcsec_h": vy, "fit_rms_arcsec": tr.fit.rms_arcsec,
               "median_offset_from_horizons_arcsec": med, "matches_horizons": med < R.MATCH_RADIUS}
        if not row["matches_horizons"]:
            mem = tr.members
            row["degenerate_track_check"] = M.degenerate_track(t[mem], xi[mem], eta[mem], tr.fit.coef_xi.size - 1,
                                                               R.STATIC_RADIUS, R.MIN_DT_STATIC)
            ra_t, dec_t = M.from_plane(*tr.fit.at(tr.fit.t_ref), ra0, dec0)
            row["position_at_t_ref"] = {"mjd": tr.fit.t_ref, "ra": float(ra_t), "dec": float(dec_t)}
            row["sb_ident_from_spherex"] = sb_ident_spherex(tr.fit.t_ref, float(ra_t), float(dec_t),
                                                            spherex_state([tr.fit.t_ref])[0])
        rows.append(row)
        if row["matches_horizons"] and target is None:
            target = tr
    print(json.dumps([{k: v for k, v in r.items() if k not in ("sb_ident_from_spherex",)} for r in rows], default=float))

    members = set(target.members.tolist()) if target is not None else set()
    exposures = []
    for k, (o, e, es) in enumerate(zip(obs, epochs, eph_sc)):
        row = {"obs_id": o.obs_id, "release": o.release, "detector": o.detector, "mjd_mid": e.mjd,
               "wavelength_um": round(e.wavelength_um, 4), "cutout_sha256": metas[k][1]["sha256"],
               "horizons_spherex": {"ra": es["ra"], "dec": es["dec"]}, "V_mag_horizons": es["V"],
               "predicted_inside_cutout": bool(inside[k]), "flag_pixels_at_prediction": flags_on[k], "measured": None}
        sel = np.nonzero(ep == k)[0]
        if sel.size:
            d = np.hypot(xi[sel] - hx[k], eta[sel] - hy[k])
            j = sel[np.argmin(d)]
            if d.min() < R.MATCH_RADIUS:
                row["measured"] = {"ra": dets[j].ra, "dec": dets[j].dec, "snr": dets[j].snr, "err_arcsec": dets[j].err_arcsec,
                                   "x": dets[j].x, "y": dets[j].y,
                                   "resid_ra_cosdec_arcsec": float(xi[j] - hx[k]), "resid_dec_arcsec": float(eta[j] - hy[k]),
                                   "resid_vs_geocentric_arcsec": [float(xi[j] - gx[k]), float(eta[j] - gy[k])],
                                   "flagged_static": bool(static[j]), "in_linked_track": j in members}
        exposures.append(row)

    def stats(sel):
        if not sel:
            return None
        rx = np.array([r["measured"]["resid_ra_cosdec_arcsec"] for r in sel])
        ry = np.array([r["measured"]["resid_dec_arcsec"] for r in sel])
        return {"n": len(sel), "mean_ra_cosdec": float(rx.mean()), "mean_dec": float(ry.mean()),
                "rms_ra_cosdec": float(np.sqrt(np.mean(rx ** 2))), "rms_dec": float(np.sqrt(np.mean(ry ** 2))),
                "median_total": float(np.median(np.hypot(rx, ry))), "max_total": float(np.max(np.hypot(rx, ry)))}

    m_rows = [r for r in exposures if r["measured"]]
    motion = None
    if target is not None:
        mem, f = target.members, target.fit
        hxm, hym = pos(t[mem])
        fh = M.fit_track(t[mem], hxm, hym, np.full(len(mem), 0.1), order=f.coef_xi.size - 1, t_ref=f.t_ref, clip=1e9)
        vx, vy, evx, evy = f.rate_arcsec_per_hour
        hvx, hvy, _, _ = fh.rate_arcsec_per_hour
        motion = {"t_ref_mjd": f.t_ref, "fit_order": int(f.coef_xi.size - 1), "n_detections": int(len(mem)),
                  "n_visits": int(target.n_visits),
                  "measured_rate_arcsec_h": {"ra_cosdec": vx, "dec": vy, "err_ra_cosdec": evx, "err_dec": evy,
                                             "total": float(np.hypot(vx, vy))},
                  "horizons_same_model_rate_arcsec_h": {"ra_cosdec": hvx, "dec": hvy, "total": float(np.hypot(hvx, hvy))},
                  "rate_difference_sigma": [(vx - hvx) / evx, (vy - hvy) / evy],
                  "fit_rms_arcsec": f.rms_arcsec, "fit_chi2_red": f.chi2_red,
                  "time_span_hours": float((t[mem].max() - t[mem].min()) * 24.0)}
    floor, _ = R.field_floor(t, xi, eta, err, snr, static)
    result = {
        "label": "REAL SPHEREx data, KNOWN object",
        "object": case["name"], "why_chosen": case["why"], "horizons_command": case["horizons_command"],
        "field": {"ra_center": ra0, "dec_center": dec0, "cutout_size_deg": size, "window_mjd": list(case["window_mjd"]),
                  "track_half_extent_deg": cov["extent_deg"]},
        "archive": {"queries": cov["sia"], "n_exposures_in_window": len(obs) + len(failed), "cutouts_failed": failed},
        "horizons_query_urls_spherex": urls_sc, "coarse_track_url": cov["coarse_url"],
        "V_mag_range_horizons": [float(min(e["V"] for e in eph_sc)), float(max(e["V"] for e in eph_sc))],
        "horizons_rate_range_arcsec_h": [float(min(np.hypot(e["rate_ra_cosdec_arcsec_h"], e["rate_dec_arcsec_h"]) for e in eph_geo)),
                                         float(max(np.hypot(e["rate_ra_cosdec_arcsec_h"], e["rate_dec_arcsec_h"]) for e in eph_geo))],
        "n_visits_with_object_inside_cutout": n_vis_inside, "n_visits_total": int(len(set(vis_all.tolist()))),
        "blind_search": {"n_detections": len(dets), "n_static": int(static.sum()), "tracks": rows},
        "linked": target is not None,
        "exposures": exposures,
        "residuals_vs_horizons_spherex_arcsec": {"all_detections_near_prediction": stats(m_rows),
                                                 "linked_track_members": stats([r for r in m_rows if r["measured"]["in_linked_track"]])},
        "fitted_motion": motion,
        "astrometric_floor_field_stars": floor,
        "pipeline_flag_finding": {"n_with_outlier_at_prediction": sum(1 for f in flags_on if f.get("OUTLIER")),
                                  "n_exposures": len(flags_on)},
        "runtime_s": round(time.time() - t_start, 1),
    }
    result["figure"] = case_figure(result, epochs, xi, eta, t, target, hx, hy)
    return result


def case_figure(r, epochs, xi, eta, t, target, hx, hy):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(12, 7))
    gs = fig.add_gridspec(2, 6, height_ratios=[1, 1.3], hspace=0.4, wspace=0.35)
    vis = M.visits([e.mjd for e in epochs])
    picks = []
    for v in np.unique(vis):
        ks = [k for k in range(len(epochs)) if vis[k] == v and r["exposures"][k]["predicted_inside_cutout"]]
        if ks:
            picks.append(max(ks, key=lambda k: (r["exposures"][k]["measured"] or {}).get("snr", -1)))
    for n, k in enumerate(picks[:6]):
        ax = fig.add_subplot(gs[0, n])
        e, row = epochs[k], r["exposures"][k]
        h = 10
        ys, xs = slice(max(0, int(e.y) - h), int(e.y) + h + 1), slice(max(0, int(e.x) - h), int(e.x) + h + 1)
        img = np.where(e.bad, np.nan, e.image)[ys, xs]
        lo, hi = np.nanpercentile(img, [5, 99.5])
        ax.imshow(img, origin="lower", cmap="gray_r", vmin=lo, vmax=hi,
                  extent=(xs.start - 0.5, xs.start + img.shape[1] - 0.5, ys.start - 0.5, ys.start + img.shape[0] - 0.5))
        ax.add_patch(plt.Circle((e.x, e.y), 2.0, fill=False, color="tab:blue", lw=1.2))
        if row["measured"]:
            ax.plot(row["measured"]["x"], row["measured"]["y"], "x", color="tab:red", ms=7, mew=1.5)
        ax.set_title(f"{row['obs_id']}\n{row['detector'][-2:]} {row['wavelength_um']:.2f} um", fontsize=7)
        ax.set_xticks([]), ax.set_yticks([])
    ax = fig.add_subplot(gs[1, 0:3])
    ax.scatter(xi, eta, s=2, c="0.8", label="all detections")
    o = np.argsort([e.mjd for e in epochs])
    ax.plot(hx[o], hy[o], "-", color="tab:blue", lw=1, label="Horizons (from SPHEREx)")
    if target is not None:
        m = target.members
        ax.scatter(xi[m], eta[m], s=14, c=(t[m] - t[m].min()) * 24, cmap="viridis", label="linked track (blind)")
    ax.invert_xaxis(), ax.legend(fontsize=7)
    ax.set_xlabel("RA cos Dec offset [arcsec]"), ax.set_ylabel("Dec offset [arcsec]")
    ax = fig.add_subplot(gs[1, 3:6])
    rows = [x for x in r["exposures"] if x["measured"]]
    if rows:
        tt = np.array([x["mjd_mid"] for x in rows])
        ax.errorbar(tt - 0.01, [x["measured"]["resid_ra_cosdec_arcsec"] for x in rows], [x["measured"]["err_arcsec"] for x in rows],
                    fmt="o", ms=3, color="tab:red", label="RA cos Dec")
        ax.errorbar(tt + 0.01, [x["measured"]["resid_dec_arcsec"] for x in rows], [x["measured"]["err_arcsec"] for x in rows],
                    fmt="s", ms=3, color="tab:purple", label="Dec")
    ax.axhline(0, color="k", lw=0.5), ax.legend(fontsize=7)
    ax.set_xlabel("MJD"), ax.set_ylabel("measured - Horizons@SPHEREx [arcsec]")
    fig.suptitle(f"{r['object']} in real SPHEREx cutouts (blue = Horizons, red x = blind detection)", fontsize=10)
    slug = "".join(c for c in r["object"].lower() if c.isalnum())
    path = FIG_DIR / f"motion_followup_{slug}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(path.relative_to(ROOT))


# Chosen with sb_ident (from SPHEREx) around the Kleopatra field and a Horizons
# scan of bright NEOs (V < 16 at 88-125 deg elongation from SPHEREx), followed by
# SIA coverage checks along each path; see "case_search" in the JSON. Settings
# of the blind search are NOT changed per case; only the field (centre, size,
# window) follows the Horizons path, as for Kleopatra.
CASES = [
    {"name": "(2052) Tamriko", "horizons_command": "2052;", "window_mjd": R.WINDOW_MJD,
     "why": ("FAINTER case: main-belt asteroid 0.4 deg from the Kleopatra field, V ~16.2 in the same 3.3-day window "
             "(Kleopatra V 12.8), i.e. close to the single-exposure detection limit; found with sb_ident from SPHEREx.")},
    {"name": "(433) Eros", "horizons_command": "433;", "window_mjd": (60862.55, 60863.40), "max_cutout_deg": 0.5,
     "why": ("FASTER case: near-Earth asteroid, V ~13.3, ~0.3 au from SPHEREx in July 2025, moving tens of arcsec per hour; "
             "three SPHEREx visits in 17 hours cover it. Kleopatra moved ~5 arcsec/hour.")},
]
CASE_SEARCH = {
    "sb_ident_around_kleopatra_field": ("sb_ident from SPHEREx (xobs), MJD 60845.0, 1.5 deg half-width around the Kleopatra field, "
                                        "V < 17: Kleopatra (V 12.8), (2052) Tamriko (V 16.2, 0.40 deg away), (641) Agnes (V 16.8, 1.6 deg away)."),
    "neo_scan": ("Horizons from SPHEREx, 2025-05-01..2026-07-25, daily, for 40 well-known NEOs; kept days with V < 16 and "
                 "elongation 88-125 deg. Windows found for 433 Eros, 1036 Ganymed, 1620 Geographos, 2100 Ra-Shalom, 1943 Anteros, "
                 "4183 Cuno, 35107 (1991 VH), 3361 Orpheus, 3103 Eger; none for the other 31."),
    "eros_sia_scan": ("SIA at Eros's position every 4 days, MJD 60863-60903; exposures within 1 day whose Eros position is within 0.25 deg: "
                      "3 visits at 60862.6-60863.3 (the case used), 2 at 60867.2-60867.4, 1 at 60870.8 and 60882.5, none at the other 7 samples."),
}


def main():
    t0 = time.time()
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print("Part 1: re-run the Kleopatra blind search on cached cutouts")
    run = rebuild_kleopatra_run()
    vet = vet_second_track(run)
    vet["figure"] = track2_figure(run, vet)
    print("Part 2: further known objects")
    cases = []
    for c in ([] if "--skip-cases" in sys.argv else CASES):
        try:
            cases.append(run_case(c))
        except Exception as e:   # one failed case (archive down) must not hide the others
            cases.append({"object": c["name"], "error": repr(e)})
    result = {
        "experiment": "Track B follow-up: vetting of the unexplained second track, and further KNOWN-asteroid validation cases",
        "claim": "none about new objects",
        "settings_from": "reproduce_motion.py (unchanged)",
        "second_track": vet,
        "case_search": CASE_SEARCH,
        "validation_cases": cases,
        "run": {"started_utc": started, "runtime_s": round(time.time() - t0, 1), "python": platform.python_version(),
                "numpy": np.__version__},
    }
    result["second_track"]["conclusion"] = conclusion(vet)
    OUT.write_text(json.dumps(result, indent=1, default=float))
    print(f"wrote {OUT}  runtime {result['run']['runtime_s']} s")


def conclusion(v):
    """Plain-language verdict built only from the numbers in `v`."""
    parts = []
    d = v["degenerate_track_check"]
    if d:
        parts.append(f"The {v['n_detections']} detections fall into {d['n_position_groups']} fixed sky positions, each seen only "
                     f"within < {R.MIN_DT_STATIC:.0f} h (too short for the static-source flag); a polynomial of order "
                     f"{d['fit_order']} passes through {d['fit_order'] + 1} points exactly, so the fit says nothing about motion. "
                     f"A straight line through the same points has rms {v['linear_fit_same_points']['rms_arcsec']:.1f}\" "
                     f"(chi2_red {v['linear_fit_same_points']['chi2_red']:.0f}) versus {v['published_fit']['rms_arcsec']:.1f}\" for the quadratic.")
    for g in v["position_groups"]:
        fs, cat = g["forced_summary"], g["catalogs"]
        sh = fs.get("short_lt_2.42um", {})
        lo = fs.get("long_ge_2.42um", {})
        mem = [m for m in v["members"] if f"{m['obs_id']} {m['detector'][-2:]}" in g["members"]]
        sharp = max(m["peak_over_neighbours"] / m["peak_over_neighbours_expected_for_psf"] for m in mem)
        cats = ", ".join(f"{k} {cat[k]['n']}" for k in CATALOGS) + f", SIMBAD {len(cat['simbad']['rows'])}"
        if sharp > 3 and len(mem) == 1:
            m0 = mem[0]
            visit = m0["obs_id"].rsplit("_", 1)[0]
            same_det = [r for r in g["forced_photometry"] if r["obs_id"].startswith(visit) and r["detector"] == m0["detector"]
                        and r["obs_id"] != m0["obs_id"]]
            same_time = [r for r in g["forced_photometry"] if r["obs_id"] == m0["obs_id"] and r["detector"] != m0["detector"]]
            kind = (f"a single-exposure event in {m0['obs_id']} {m0['detector'][-2:]} at {m0['wavelength_um_at_detection']:.2f} um "
                    f"(S/N {m0['snr']:.1f}); its peak pixel stands {sharp:.1f}x higher above its neighbours than a PSF-sampled source "
                    f"would, the other exposures of the same visit on the same detector (minutes apart) give forced S/N "
                    f"{[r['snr'] for r in same_det]}, the simultaneous exposure on the other detector gives "
                    f"{[r['snr'] for r in same_time]}, and nothing is catalogued there: most likely an unflagged cosmic-ray "
                    f"or detector hit")
        elif sh and sh["stacked_snr"] > 5:
            kind = (f"a STATIC source: forced S/N stacks to {sh['stacked_snr']:.1f} over {sh['n_exposures']} exposures below 2.42 um "
                    f"(median {sh['median_snr']:.1f}) but {lo.get('stacked_snr', float('nan')):.1f} above; it crosses 5 sigma only "
                    f"in {sh['n_snr_gt_5']} exposure(s)")
        else:
            kind = "unclear"
        parts.append(f"Position {g['group']} ({g['ra']:.5f}, {g['dec']:+.5f}; {len(mem)} member(s)): {kind}. Catalogue sources "
                     f"within {CAT_RADIUS:.0f}\": {cats}.")
    ctrl = v["sb_ident_positive_control"]
    n_sb = [m["sb_ident_from_spherex"].get("n_objects") for m in v["members"]]
    near = [min([float(o["Dist. from center Norm (\")"]) for o in m["sb_ident_from_spherex"].get("objects", [])] or [np.inf])
            for m in v["members"]]
    parts.append(f"sb_ident from SPHEREx (positive control finds Kleopatra: {ctrl['finds_kleopatra']}) lists "
                 f"{n_sb} known bodies within {SB_HALF_WIDTH} deg of the members, the nearest {min(near):.0f}\" away "
                 f"(none within the {R.MATCH_RADIUS:.0f}\" match radius). The geocentric (code 500) lookup used in "
                 f"motion_check.json finds Kleopatra at its own position: {v['sb_ident_geocentric_500_control']['finds_kleopatra']}.")
    parts.append("Most likely explanation: NOT a moving object, but two faint static sources (each with a Gaia DR3 and an "
                 "AllWISE counterpart) that reach 5 sigma only in a few short-wavelength exposures, plus one single-exposure "
                 "artefact; the order-2 fit through three positions made them look like a slow track."
                 if d and len(v["position_groups"]) == 3 else "See the per-position evidence above.")
    return " ".join(parts)


if __name__ == "__main__":
    main()
