"""EXPERIMENTAL: check the published aperture ratios with an independent ePSF fit.

Writes submission/evidence/epsf_check.json, report/figures/epsf_residuals.png and
report/figures/epsf_diagnostics.png (the "diagnostics" section: why reduced chi2 is
high on RW Aur; real pixels only, none of it changes a published number).
Uses only cached real SPHEREx cutouts and the pairs already in robustness.json
(run reproduce_robustness.py first). Barnard's Star has no usable epoch, so we
don't fit it: its pixels are saturated, and no fit can fix that.

Agreement rule (fixed before looking at the result):
  z = (ln R_epsf - ln R_aperture) / sqrt(s_epsf^2 + s_ap^2), s = fractional errors
  compatible |z| < 3, discrepant |z| >= 5, inconclusive otherwise or if a fit failed.
Both methods read the same photons, so their errors are positively correlated
and this denominator is too large: "discrepant" is conservative, "compatible"
is lenient. We state that with the result rather than hide it.
"""

import json
import math
import re
import resource
import sys
import time
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from astropy.io import fits  # noqa: E402
from hipparchus import api, archive, cutouts, psf_photometry as P, quality  # noqa: E402

warnings.simplefilter("ignore")
ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "submission" / "evidence"
OUT = EVID / "epsf_check.json"
FIG = ROOT / "report" / "figures" / "epsf_residuals.png"
FIG_DIAG = ROOT / "report" / "figures" / "epsf_diagnostics.png"
FREE_POSITION_SNR = 20  # bright stars: let the position move (<1 px); faint ones stay at the WCS position


def epoch_paths(t):
    m = json.loads(archive._manifest_path(t["ra"], t["dec"]).read_text())
    out = {}
    for o in m["observations"]:
        if o["detector"] == t["detector"]:
            p = cutouts.CACHE_DIR / f'{cutouts._key(o["access_url"], t["ra"], t["dec"], cutouts.DEFAULT_SIZE_DEG)}.fits'
            if p.exists():
                out[o["obs_id"]] = p
    # The RW Aur manifest was later re-queried with only spherex_dr1 listed, which
    # dropped the 2026W37 (qr3) epochs that robustness.json still uses. Their
    # cutouts are in the cache; the sidecar .json keeps each one's access URL,
    # so we find them from there (same target centre, same detector).
    centre = f'center={t["ra"]}%2C{t["dec"]}'
    for side in sorted(cutouts.CACHE_DIR.glob("*.json")):
        try:
            url = json.loads(side.read_text()).get("url", "")
        except (ValueError, OSError):
            continue
        hit = re.search(r"level2_(.+?)D(\d)_spx", url)
        fits_path = side.with_suffix(".fits")
        if centre in url and hit and f"D{hit.group(2)}" == t["detector"][-2:] and fits_path.exists():
            out.setdefault(hit.group(1), fits_path)
    return out


_EPOCHS = {}


def load_epoch(path, obs_id, t):
    """quality.load, once per file: the WCS set-up is most of the run time."""
    key = (str(path), obs_id, t["ra"], t["dec"])
    if key not in _EPOCHS:
        _EPOCHS[key] = quality.load(*key)
    return _EPOCHS[key]


def fit_epoch(path, obs_id, t):
    ep = load_epoch(path, obs_id, t)
    e = P.load_epsf(str(path), ep.x, ep.y)
    if e is None:
        return ep, None, {"ok": False, "reason": "no usable EPSF extension"}
    f = P.fit(ep.image, ep.variance, ep.bad, ep.x, ep.y, e)
    if f["ok"] and f["amp"] / f["amp_err"] >= FREE_POSITION_SNR:
        f = P.fit(ep.image, ep.variance, ep.bad, ep.x, ep.y, e, fit_position=True)
    if f["ok"]:
        # Standard practice: when chi2_red > 1 the model is imperfect, so we
        # scale the amplitude error up by sqrt(chi2_red) (never down).
        f["amp_err_scaled"] = f["amp_err"] * math.sqrt(max(1.0, f["chi2_red"]))
    return ep, e, f


def simulated_checks(t, n_pos=4, seed=7):
    """SIMULATED stars injected into the real WISE 0855 cutouts (real sky, real noise).

    Positions are blank spots away from the target. For each: a fit with no star
    (noise only: false positives), then the same spot with an ePSF star of known
    flux added (bias and error calibration), and a 0.3 px position error
    (astrometric sensitivity). We also run aperture photometry on the same
    native pixels, for comparison.
    """
    from hipparchus.compare import photometry
    rng = np.random.default_rng(seed)
    out = {"label": "SIMULATED", "noise_only_pulls": [], "injected": [], "astrometry_0p3px_ratio": []}
    for oid, path in sorted(epoch_paths(t).items()):
        ep = load_epoch(path, oid, t)
        if not ep.usable:
            continue
        ny, nx = ep.image.shape
        yy, xx = np.mgrid[0:ny, 0:nx].astype(float)
        for _ in range(n_pos):
            for _try in range(20):
                x0, y0 = rng.uniform(6, nx - 7), rng.uniform(6, ny - 7)
                if math.hypot(x0 - ep.x, y0 - ep.y) > 8 and not ep.bad[int(y0) - 3:int(y0) + 4, int(x0) - 3:int(x0) + 4].any():
                    break
            else:
                continue
            e = P.load_epsf(str(path), x0, y0)
            if e is None:
                continue
            f0 = P.fit(ep.image, ep.variance, ep.bad, x0, y0, e)
            if not f0["ok"]:
                continue
            out["noise_only_pulls"].append(f0["amp"] / f0["amp_err"])
            flux = 10 * f0["amp_err"]  # an S/N ~ 10 star
            img = ep.image + flux * P.render(e["psf"], e["ovs"], x0, y0, xx, yy)
            f1 = P.fit(img, ep.variance, ep.bad, x0, y0, e)
            ap = photometry(img, ep.variance, ep.bad, x0, y0)
            ap0 = photometry(ep.image, ep.variance, ep.bad, x0, y0)
            f2 = P.fit(img, ep.variance, ep.bad, x0 + 0.3, y0, e)
            for snr in (10, 50, 200):
                F = snr * f0["amp_err"]
                im2 = ep.image + F * P.render(e["psf"], e["ovs"], x0, y0, xx, yy)
                g = P.fit(im2, ep.variance, ep.bad, x0, y0, e)
                a2 = photometry(im2, ep.variance, ep.bad, x0, y0)
                if g["ok"] and g["amp"] > 0 and a2["flux"] > 0:
                    out.setdefault("pair_noise", []).append({
                        "snr": snr, "d": math.log(a2["flux"]) - math.log(g["amp"]),
                        "quad": math.hypot(a2["flux_err"] / a2["flux"], g["amp_err"] / g["amp"])})
            if f1["ok"]:
                out["injected"].append({"flux": flux, "amp": f1["amp"], "amp_err": f1["amp_err"],
                                        "pull": (f1["amp"] - f0["amp"] - flux) / flux,
                                        "aperture_minus_blank": ap["flux"] - ap0["flux"]})
            if f1["ok"] and f2["ok"]:
                out["astrometry_0p3px_ratio"].append(f2["amp"] / f1["amp"])
    pulls = np.array(out["noise_only_pulls"])
    inj = out["injected"]
    rec = np.array([(r["amp"] - r["flux"]) / r["flux"] for r in inj])
    ipull = np.array([r["pull"] for r in inj])  # fractional, should be ~1e-15
    apfrac = np.array([r["aperture_minus_blank"] / r["flux"] for r in inj])
    corr = {}
    for snr in (10, 50, 200):
        rr = [r for r in out.get("pair_noise", []) if r["snr"] == snr]
        if len(rr) > 10:
            d = np.array([r["d"] for r in rr])
            # < 1 means the two methods' errors are positively correlated: the true
            # scatter of their difference is smaller than the quadrature sum.
            corr[str(snr)] = float(np.std(d) / np.median([r["quad"] for r in rr]))
    out["difference_scatter_over_quadrature"] = corr
    out.pop("pair_noise", None)
    out["summary"] = {
        "n_noise_only": len(pulls), "noise_only_pull_std": float(np.std(pulls)),
        "noise_only_false_ge5": int(np.sum(np.abs(pulls) >= 5)), "noise_only_false_ge3": int(np.sum(np.abs(pulls) >= 3)),
        "n_injected": len(inj), "median_fractional_bias": float(np.median(rec)),
        # The model is linear in the amplitude, so an injected star must add exactly
        # its flux to the blank-sky fit; this checks the code, not the noise.
        "max_linearity_error": float(np.max(np.abs(ipull)) if len(ipull) else 0),
        "aperture_fraction_of_injected_flux": float(np.median(apfrac)),
        "astrometry_0p3px_median_ratio": float(np.median(out["astrometry_0p3px_ratio"]))}
    return out


def label(z):
    if z is None or not math.isfinite(z):
        return "inconclusive"
    return "compatible" if abs(z) < 3 else "discrepant" if abs(z) >= 5 else "inconclusive"


def pair_rows(pairs, fits_):
    """Each aperture pair re-measured with the ePSF fits, and the agreement z."""
    rows = []
    for p in pairs:
        fa, fb = fits_[p["a"]], fits_[p["b"]]
        row = {"a": p["a"], "b": p["b"], "ratio_aperture": p["ratio"], "sig_aperture": p["sig"]}
        if fa["ok"] and fb["ok"]:
            row["sig_epsf"] = (fb["amp"] - fa["amp"]) / math.hypot(fa["amp_err_scaled"], fb["amp_err_scaled"])
            row["snr_epsf"] = [fa["amp"] / fa["amp_err_scaled"], fb["amp"] / fb["amp_err_scaled"]]
        snr_ok = (fa["ok"] and fb["ok"] and min(row.get("snr_epsf", [0])) >= 5
                  and min(p["fa"], p["fb"]) / p["err"] * math.sqrt(2) >= 5)
        if snr_ok:
            ra_ = fb["amp"] / fa["amp"]
            s_psf = math.hypot(fa["amp_err_scaled"] / fa["amp"], fb["amp_err_scaled"] / fb["amp"])
            s_ap = math.hypot(p["err"] / p["fa"], p["err"] / p["fb"]) / math.sqrt(2)
            z = (math.log(ra_) - math.log(p["ratio"])) / math.hypot(s_psf, s_ap)
            row |= {"ratio_epsf": ra_, "chi2_red": [fa["chi2_red"], fb["chi2_red"]], "shift_px": [fa["shift_px"], fb["shift_px"]],
                    "aperture_over_epsf_flux": [p["fa"] / fa["amp"], p["fb"] / fb["amp"]],
                    "z_agreement": z, "agreement": label(z),
                    "warnings": fa["warnings"] + fb["warnings"]}
        else:
            # A flux ratio means nothing below S/N 5; there we check the claim on significances.
            row |= {"agreement": "inconclusive",
                    "reason": "; ".join(f["reason"] for f in (fa, fb) if not f["ok"]) or "S/N < 5 in an epoch"}
        rows.append(row)
    return rows

# Gaia DR3 sources within 45" of RW Aur (VizieR I/355/gaiadr3, queried 2026-11-16;
# CDS itself was offline, see catalog_match.json). source_id, RA, Dec (epoch 2016.0),
# pmRA*cos(Dec), pmDec (mas/yr), G. The first two, 1.65" apart (0.27 SPHEREx pixel),
# are the RW Aur pair itself; every other one is a field star. We store them here
# so the check runs offline.
RW_AUR_GAIA = [
    ("156430822114424576", 76.95608119553, 30.40120458910, 2.641, -27.398, 12.184),
    ("156430817820015232", 76.95654431103, 30.40131614989, 4.906, -24.578, 13.035),
    ("156430856476049024", 76.96525901564, 30.41003829119, 0.558, -1.233, 15.263),
    ("156430096265962240", 76.96861322420, 30.39879930778, 0.196, -1.013, 16.830),
    ("156430100561810560", 76.96590480470, 30.39288036050, 0.075, -1.474, 17.200),
    ("156430817820464384", 76.94610026045, 30.39713697220, 2.066, -2.959, 17.461),
    ("156430822116318592", 76.94471060571, 30.40044281297, 1.874, -7.516, 17.467),
    ("156430061906216320", 76.95979380136, 30.39437083489, 1.436, -3.960, 17.529),
    ("156430096265956864", 76.96715506891, 30.39553790230, 1.144, -0.667, 18.488),
    ("156430096265969280", 76.97013211543, 30.40318551756, 0.537, -0.767, 18.529),
    ("156430856474162688", 76.95576839814, 30.40300437168, 1.075, -1.194, 18.826),
    ("156430817820482432", 76.94959260120, 30.40705278157, 2.928, -5.091, 19.144),
    ("156430852184331008", 76.95436974611, 30.40520556447, 0.180, -1.856, 19.312),
]
NEIGHBOUR_REACH_PX = 7.5  # box half-width 4 + the ePSF table half-width 3.3, rounded up


def gaia_pixels(ep):
    """Gaia positions moved to the epoch of the exposure, in cutout pixels."""
    from astropy.time import Time
    from hipparchus import catalogs
    yr = Time(ep.mjd, format="mjd").decimalyear
    out = []
    for sid, ra, dec, pmra, pmdec, g in RW_AUR_GAIA:
        r2, d2 = catalogs.propagate(ra, dec, pmra, pmdec, 2016.0, yr)
        x, y = ep.wcs.world_to_pixel_values(r2, d2)
        out.append({"source_id": sid, "g": g, "x": float(x), "y": float(y)})
    return out


def field_neighbours(ep, tid):
    """Catalogue stars other than the target that can put light in the fit box."""
    if tid != "rw_aur":
        return []  # no catalogue list stored for the other targets
    return [(s["x"], s["y"]) for s in gaia_pixels(ep)[2:]
            if abs(s["x"] - ep.x) <= NEIGHBOUR_REACH_PX and abs(s["y"] - ep.y) <= NEIGHBOUR_REACH_PX]


def fit_variant(ep, e, tid, **opts):
    """fit_epoch with options: same free-position rule (S/N >= 20), same error scaling."""
    f = P.fit(ep.image, ep.variance, ep.bad, ep.x, ep.y, e, **opts)
    if f["ok"] and f["amp"] / f["amp_err"] >= FREE_POSITION_SNR:
        f = P.fit(ep.image, ep.variance, ep.bad, ep.x, ep.y, e, fit_position=True, **opts)
    if f["ok"]:
        f["amp_err_scaled"] = f["amp_err"] * math.sqrt(max(1.0, f["chi2_red"]))
    return f


def _orient(psf, k):
    q = psf.T if k & 1 else psf
    q = q[:, ::-1] if k & 2 else q
    return q[::-1, :] if k & 4 else q


def _zones(path, xo, yo):
    """All zone ePSFs, the zone-grid axes, and the bilinear mix of the 4 zones around (xo, yo)."""
    with fits.open(path) as h:
        t = h["EPSF"].data
        X, Y = np.asarray(t["XCENTER"], float), np.asarray(t["YCENTER"], float)
        ps = np.asarray(t["EPSF"], float).reshape(len(t), 33, 33)
    xs, ys = np.unique(X), np.unique(Y)
    ix = int(np.clip(np.searchsorted(xs, xo) - 1, 0, len(xs) - 2))
    iy = int(np.clip(np.searchsorted(ys, yo) - 1, 0, len(ys) - 2))
    fx = float(np.clip((xo - xs[ix]) / (xs[ix + 1] - xs[ix]), 0, 1))
    fy = float(np.clip((yo - ys[iy]) / (ys[iy + 1] - ys[iy]), 0, 1))
    get = lambda a, b: ps[np.where((X == xs[a]) & (Y == ys[b]))[0][0]]  # noqa: E731
    bil = ((1 - fx) * (1 - fy) * get(ix, iy) + fx * (1 - fy) * get(ix + 1, iy)
           + (1 - fx) * fy * get(ix, iy + 1) + fx * fy * get(ix + 1, iy + 1))
    return X, Y, xs, ys, bil / bil.sum()


def _pixel_noise(ep, r_min=6.0):
    """Blank-sky scatter / sqrt(VARIANCE) and the correlation of adjacent pixels."""
    from scipy.ndimage import median_filter
    z = (ep.image - median_filter(ep.image, size=7, mode="nearest")) / np.sqrt(ep.variance)
    ny, nx = z.shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    m = ~ep.bad & np.isfinite(z) & (ep.variance > 0) & (np.hypot(xx - ep.x, yy - ep.y) > r_min)
    m[:2] = m[-2:] = False
    m[:, :2] = m[:, -2:] = False
    zc = np.where(m & (np.abs(z) < 5), z, np.nan)

    def corr(a, b):
        k = np.isfinite(a) & np.isfinite(b)
        return float(np.corrcoef(a[k], b[k])[0, 1])
    return {"mad_sigma": P.blank_sky_scale(ep.image, ep.variance, ep.bad, ep.x, ep.y, r_min),
            "corr_x": corr(zc[:, 1:], zc[:, :-1]), "corr_y": corr(zc[1:], zc[:-1]),
            "frac_abs_z_gt5": float(np.mean(np.abs(z[m]) > 5))}


def _stats(v):
    v = np.asarray([x for x in v if x is not None and math.isfinite(x)], float)
    return {"median": float(np.median(v)), "min": float(v.min()), "max": float(v.max()), "n": int(v.size)} if v.size else None


def diagnostics(rob, fits_by_target):
    """Why is reduced chi2 4-18 on RW Aur? Each candidate cause measured on the real pixels.

    Everything here is on real cached SPHEREx cutouts; nothing is SIMULATED.
    """
    out = {}
    tw = {t["id"]: t for t in api.TARGETS}
    clock = time.perf_counter()
    E = {}
    for tid in ("rw_aur", "wise0855"):
        t = tw[tid]
        paths = epoch_paths(t)
        for oid in sorted({p["a"] for p in rob["targets"][tid]["pairs"]} | {p["b"] for p in rob["targets"][tid]["pairs"]}):
            ep = load_epoch(paths[oid], oid, t)
            E[(tid, oid)] = (ep, P.load_epsf(str(paths[oid]), ep.x, ep.y), paths[oid])
    rw = [(oid, *v) for (tid, oid), v in E.items() if tid == "rw_aur"]

    # 1. Normalisation: the table sums to 1 on the fine grid; ovs**2 * table sampled every
    #    ovs-th point sums to ~1 on native pixels, but only to +-0.8% depending on phase.
    ph = np.linspace(-0.5, 0.5, 11)
    ns = [P.native_sum(e["psf"], e["ovs"], 14 + a, 14 + b) for _, _, e, _ in rw for a in ph for b in ph]
    out["normalisation"] = {
        "fine_grid_sum": _stats([float(e["psf"].sum()) for _, _, e, _ in rw]),
        "most_negative_table_value": float(min(e["psf"].min() for _, _, e, _ in rw)),
        "native_sum_over_subpixel_phase": _stats(ns),
        "table_half_width_native_px": 33 / 2 / 5,
        "note": "Amplitude is free, so a normalisation error cannot raise chi2; it only scales the flux. "
                "The phase dependence (0.983-1.018) moves single-epoch fluxes and so ratios; see variant normalise_native."}

    # 2. Orientation: all 8 transposes/flips, free position, summed chi2 over the RW Aur epochs.
    tot = np.zeros(8)
    for oid, ep, e, _ in rw:
        for k in range(8):
            f = P.fit(ep.image, ep.variance, ep.bad, ep.x, ep.y, dict(e, psf=_orient(e["psf"], k)), fit_position=True)
            tot[k] += f["chi2_red"] * f["dof"]
    names = ["as read", "T", "flip x", "T+flip x", "flip y", "T+flip y", "flip x+y", "T+flip x+y"]
    out["orientation"] = {"total_chi2": dict(zip(names, map(float, tot))), "best": names[int(np.argmin(tot))],
                          "next_best_over_best": float(np.sort(tot)[1] / tot.min())}

    # 3. Zones: nearest (as used) vs bilinear between the 4 surrounding zones; distance to the zone centre.
    zr = []
    for oid, ep, e, path in rw:
        X, Y, xs, ys, bil = _zones(path, *e["parent_xy"])
        a = P.fit(ep.image, ep.variance, ep.bad, ep.x, ep.y, e, fit_position=True)
        b = P.fit(ep.image, ep.variance, ep.bad, ep.x, ep.y, dict(e, psf=bil), fit_position=True)
        zr.append({"epoch": oid, "zone": e["zone"], "dist_px": e["dist_px"], "chi2_nearest": a["chi2_red"],
                   "chi2_bilinear": b["chi2_red"], "amp_bilinear_over_nearest": b["amp"] / a["amp"]})
    d3 = None
    for side in sorted(cutouts.CACHE_DIR.glob("*.json")):
        if "D3_spx" in side.read_text() and side.with_suffix(".fits").exists():
            X, Y, xs, ys, _ = _zones(side.with_suffix(".fits"), 0, 0)
            # Rectangular tiling: the nearest zone centre must be the zone containing the point.
            rng = np.random.default_rng(1)
            pts = rng.uniform([xs[0], ys[0]], [xs[-1], ys[-1]], (2000, 2))
            near = np.argmin((X[None] - pts[:, :1]) ** 2 + (Y[None] - pts[:, 1:]) ** 2, 1)
            cell = [np.argmin(np.abs(xs - p[0])) * 0 + np.where((X == xs[np.argmin(np.abs(xs - p[0]))])
                                                                 & (Y == ys[np.argmin(np.abs(ys - p[1]))]))[0][0] for p in pts]
            d3 = {"file": side.with_suffix(".fits").name, "n_zones": len(X), "nx": len(xs), "ny": len(ys),
                  "zone_pitch_px": [float(np.diff(xs).mean()), float(np.diff(ys).mean())],
                  "nearest_centre_equals_containing_zone": bool(np.all(near == np.array(cell)))}
            break
    out["zones"] = {"per_epoch": zr, "chi2_nearest": _stats([r["chi2_nearest"] for r in zr]),
                    "chi2_bilinear": _stats([r["chi2_bilinear"] for r in zr]),
                    "amp_bilinear_over_nearest": _stats([r["amp_bilinear_over_nearest"] for r in zr]),
                    "detector3_layout": d3}

    # 4. Background: constant (as used) / plane / fixed annulus median (r 4.5-7 px).
    bg = {"constant": [], "plane": [], "annulus_fixed": []}
    for oid, ep, e, _ in rw:
        ny, nx = ep.image.shape
        yy, xx = np.mgrid[0:ny, 0:nx]
        rr = np.hypot(xx - ep.x, yy - ep.y)
        sky = float(np.median(ep.image[(rr >= 4.5) & (rr < 7) & ~ep.bad]))
        bg["constant"].append(P.fit(ep.image, ep.variance, ep.bad, ep.x, ep.y, e, fit_position=True)["chi2_red"])
        bg["plane"].append(P.fit(ep.image, ep.variance, ep.bad, ep.x, ep.y, e, fit_position=True, background="plane")["chi2_red"])
        bg["annulus_fixed"].append(P.fit(ep.image - sky, ep.variance, ep.bad, ep.x, ep.y, e, fit_position=True,
                                         background="none")["chi2_red"])
    out["background"] = {k: _stats(v) for k, v in bg.items()}

    # 5. Blending: Gaia field stars near the box, and the RW Aur pair itself.
    bl, worst = [], []
    for oid, ep, e, _ in rw:
        nb = field_neighbours(ep, "rw_aur")
        a = P.fit(ep.image, ep.variance, ep.bad, ep.x, ep.y, e, fit_position=True, half=P.FIT_HALF)
        b = P.fit(ep.image, ep.variance, ep.bad, ep.x, ep.y, e, fit_position=True, neighbours=nb)
        z2 = a["residual"] ** 2 / ep.variance[a["box"][0]:a["box"][1], a["box"][2]:a["box"][3]]
        g = gaia_pixels(ep)
        # Pair: anchor on the G=12.18 component, the G=13.04 one as a second free source.
        A, B = g[0], g[1]
        c = P.fit(ep.image, ep.variance, ep.bad, A["x"], A["y"], e, fit_position=True,
                  neighbours=[(B["x"], B["y"])])
        bl.append({"epoch": oid, "n_field_stars_fitted": b["n_neighbours"], "chi2_without": a["chi2_red"],
                   "chi2_with_field_stars": b["chi2_red"], "amp_with_over_without": b["amp"] / a["amp"],
                   "worst_pixel_share_of_chi2": float(np.nanmax(z2) / np.nansum(z2)),
                   "pair_flux_ratio_13_over_12": c["neighbour_amps"][0] / c["amp"] if c["neighbour_amps"] else None,
                   "chi2_pair_free_ratio": c["chi2_red"]})
    out["blending"] = {"per_epoch": bl, "chi2_without": _stats([r["chi2_without"] for r in bl]),
                       "chi2_with_field_stars": _stats([r["chi2_with_field_stars"] for r in bl]),
                       "amp_with_over_without": _stats([r["amp_with_over_without"] for r in bl]),
                       "pair_flux_ratio_13_over_12": _stats([r["pair_flux_ratio_13_over_12"] for r in bl]),
                       "note": "The pair is 0.27 px apart: with a free position its flux ratio is not constrained "
                               "(values swing through zero), so it is fitted as one source."}

    # 6. Morphology (with field stars fitted): chi2 per pixel by radius, mean residual profile,
    #    width scale and Gaussian jitter that minimise chi2.
    from scipy.ndimage import gaussian_filter, map_coordinates

    def scaled(psf, s):
        n = psf.shape[0]
        c0 = (n - 1) / 2
        v, u = np.mgrid[0:n, 0:n].astype(float)
        q = map_coordinates(psf, [c0 + (v - c0) / s, c0 + (u - c0) / s], order=3, mode="constant")
        return q / q.sum()
    rings = [(0, 1.5), (1.5, 3), (3, 99)]
    pb = [0, 0.75, 1.5, 2.25, 3, 3.5, 4, 4.5, 5, 6]
    mo, prof = [], []
    for oid, ep, e, _ in rw:
        nb = field_neighbours(ep, "rw_aur")
        f = P.fit(ep.image, ep.variance, ep.bad, ep.x, ep.y, e, fit_position=True, neighbours=nb)
        i0, i1, j0, j1 = f["box"]
        yy, xx = np.mgrid[i0:i1, j0:j1]
        r = np.hypot(xx - f["x"], yy - f["y"])
        z2 = f["residual"] ** 2 / ep.variance[i0:i1, j0:j1]
        row = {"epoch": oid, "snr": f["amp"] / f["amp_err"],
               **{f"chi2_per_px_r{a}-{b if b < 99 else 'edge'}": float(np.nanmean(z2[(r >= a) & (r < b)])) for a, b in rings}}
        sc = {s: P.fit(ep.image, ep.variance, ep.bad, ep.x, ep.y, dict(e, psf=scaled(e["psf"], s)), fit_position=True,
                       neighbours=nb)["chi2_red"] for s in (0.9, 0.95, 1.0, 1.05, 1.1)}
        ji = {s: P.fit(ep.image, ep.variance, ep.bad, ep.x, ep.y, dict(e, psf=gaussian_filter(e["psf"], s * e["ovs"],
                                                                                                mode="constant")),
                       fit_position=True, neighbours=nb)["chi2_red"] for s in (0.0, 0.05, 0.1, 0.15, 0.2, 0.3)}
        row |= {"best_width_scale": min(sc, key=sc.get), "chi2_at_best_scale": min(sc.values()),
                "best_jitter_sigma_px": min(ji, key=ji.get), "chi2_at_best_jitter": min(ji.values())}
        mo.append(row)
        if 6.5 < ep.x < ep.image.shape[1] - 7.5 and 6.5 < ep.y < ep.image.shape[0] - 7.5:
            g = P.fit(ep.image, ep.variance, ep.bad, ep.x, ep.y, e, fit_position=True, neighbours=nb, half=6)
            i0, i1, j0, j1 = g["box"]
            yy, xx = np.mgrid[i0:i1, j0:j1]
            r = np.hypot(xx - g["x"], yy - g["y"])
            prof.append([float(np.nanmean(g["residual"][(r >= a) & (r < b)]) / g["amp"]) for a, b in zip(pb[:-1], pb[1:])])
    yy, xx = np.mgrid[-6:7, -6:7].astype(float)
    M = P.render(rw[0][2]["psf"], 5, 0.0, 0.0, xx, yy)
    r = np.hypot(xx, yy)
    out["morphology"] = {
        "per_epoch": mo,
        **{k: _stats([m[k] for m in mo]) for k in mo[0] if k.startswith("chi2_per_px")},
        "best_width_scale": [m["best_width_scale"] for m in mo],
        "best_jitter_sigma_px": [m["best_jitter_sigma_px"] for m in mo],
        "radial_bins_px": pb,
        "mean_residual_over_flux_per_px_13x13": np.median(prof, 0).tolist(),
        "epsf_model_over_flux_per_px": [float(M[(r >= a) & (r < b)].mean()) for a, b in zip(pb[:-1], pb[1:])],
        "zone_neff_mean_vs_epsf_neff": {
            "epsf_neff_phase_mean": float(np.mean([1 / np.sum(P.render(rw[0][2]["psf"], 5, a, b, xx, yy) ** 2)
                                                   for a in ph for b in ph]))}}

    # 7. Noise: blank-sky scatter against VARIANCE, and adjacent-pixel correlation,
    #    on the epochs used in the pairs (10 RW Aur, 31 WISE 0855).
    nz = {}
    for tid in ("rw_aur", "wise0855"):
        vals = [_pixel_noise(ep) for (t_, _), (ep, _, _) in E.items() if t_ == tid]
        nz[tid] = {k: _stats([v[k] for v in vals]) for k in vals[0]}
    out["noise"] = nz

    # 8. Astrometry: chi2 with the position fixed at the preset WCS position, at the
    #    Gaia G=12.18 component, at the midpoint of the pair, and free.
    ast = []
    for oid, ep, e, _ in rw:
        nb = field_neighbours(ep, "rw_aur")
        g = gaia_pixels(ep)
        mx, my = (g[0]["x"] + g[1]["x"]) / 2, (g[0]["y"] + g[1]["y"]) / 2
        fr = P.fit(ep.image, ep.variance, ep.bad, ep.x, ep.y, e, fit_position=True, neighbours=nb)
        row = {"epoch": oid,
               "chi2_fixed_preset": P.fit(ep.image, ep.variance, ep.bad, ep.x, ep.y, e, neighbours=nb)["chi2_red"],
               "chi2_fixed_gaia_g12": P.fit(ep.image, ep.variance, ep.bad, g[0]["x"], g[0]["y"], e,
                                            neighbours=nb)["chi2_red"],
               "chi2_fixed_pair_mid": P.fit(ep.image, ep.variance, ep.bad, mx, my, e, neighbours=nb)["chi2_red"],
               "chi2_free": fr["chi2_red"], "free_minus_preset_px": [fr["x"] - ep.x, fr["y"] - ep.y],
               "free_minus_gaia_g12_px": [fr["x"] - g[0]["x"], fr["y"] - g[0]["y"]]}
        ast.append(row)
    out["astrometry"] = {"per_epoch": ast, **{k: _stats([a[k] for a in ast]) for k in ast[0] if k.startswith("chi2")},
                         "shift_from_preset_px": _stats([math.hypot(*a["free_minus_preset_px"]) for a in ast]),
                         "shift_from_gaia_g12_px": _stats([math.hypot(*a["free_minus_gaia_g12_px"]) for a in ast])}

    # 9. Variants: chi2 and the ratios under each fix, RW Aur and WISE 0855.
    scale2 = {k: P.blank_sky_scale(v[0].image, v[0].variance, v[0].bad, v[0].x, v[0].y) ** 2 for k, v in E.items()}

    def run_variant(eps=0.0, nb=False, sky=False, **kw):
        res = {}
        for tid in ("rw_aur", "wise0855"):
            fz = {}
            for (t_, oid), (ep, e, _) in E.items():
                if t_ == tid:
                    fz[oid] = fit_variant(ep, e, tid, neighbours=field_neighbours(ep, tid) if nb else (),
                                          var_scale=scale2[(tid, oid)] if sky else 1.0, model_error=eps, **kw)
            res[tid] = (fz, pair_rows(rob["targets"][tid]["pairs"], fz))
        return res

    # model_error re-weights the pixels (the core counts less), so we scan it rather than assume it.
    eps_scan = {}
    for eps in (0.01, 0.02, 0.04, 0.08):
        res = run_variant(nb=True, sky=True, eps=eps)
        fz, rows = res["rw_aur"]
        eps_scan[str(eps)] = {"chi2_red_median": float(np.median([f["chi2_red"] for f in fz.values()])),
                              "max_abs_ratio_dev": max(abs(r["ratio_epsf"] / r["ratio_aperture"] - 1)
                                                       for r in rows if "ratio_epsf" in r)}
    variants = {"published": {}, "plane": {"background": "plane"}, "normalise_native": {"normalise_native": True},
                "field_stars": {"nb": True}, "field_stars+sky_scale": {"nb": True, "sky": True},
                "field_stars+sky_scale+model_error_0.02": {"nb": True, "sky": True, "eps": 0.02},
                "field_stars+sky_scale+normalise_native": {"nb": True, "sky": True, "normalise_native": True}}
    vs = {}
    base = None
    figchi = {}
    for name, kw in variants.items():
        res = run_variant(**kw)
        figchi[name] = [res["rw_aur"][0][oid]["chi2_red"] for oid, _, _, _ in rw]
        if name == "published":
            base = res
        v = {}
        for tid, (fz, rows) in res.items():
            okr = [r for r in rows if "ratio_epsf" in r]
            dev = [r["ratio_epsf"] / r["ratio_aperture"] - 1 for r in okr]
            v[tid] = {"chi2_red": _stats([f["chi2_red"] for f in fz.values() if f["ok"]]),
                      "agreement_counts": {k: sum(r["agreement"] == k for r in rows)
                                           for k in ("compatible", "inconclusive", "discrepant")},
                      "max_abs_sig_epsf": max((abs(r["sig_epsf"]) for r in rows if "sig_epsf" in r), default=None),
                      "n_pairs_ge_5sigma_epsf": sum(abs(r.get("sig_epsf", 0)) >= 5 for r in rows)}
            if okr:
                v[tid] |= {"ratio_epsf_over_aperture_minus_1": dev, "max_abs_ratio_dev": max(map(abs, dev)),
                           "within_2pct": sum(abs(d) <= 0.02 for d in dev), "n_ratios": len(dev),
                           "abs_z": _stats([abs(r["z_agreement"]) for r in okr])}
            bf = base[tid][0]
            v[tid]["amp_change_vs_published_in_sigma"] = _stats(
                [abs(fz[k]["amp"] - bf[k]["amp"]) / bf[k]["amp_err"] for k in fz if fz[k]["ok"] and bf[k]["ok"]])
        vs[name] = v
    out["model_error_scan_rw_aur"] = eps_scan
    out["variants"] = vs

    # 10. Uncertainties (RW Aur, published fit): formal, chi2-scaled, residual bootstrap at the
    #     fitted position, and with the calibrated model error; plus the empirical scatter of
    #     ln(aperture / ePSF) between epochs (both read the same photons).
    rng = np.random.default_rng(11)
    un = []
    fz_pub = base["rw_aur"][0]
    fz_cal = run_variant(nb=True, sky=True, eps=0.02)["rw_aur"][0]
    for oid, ep, e, _ in rw:
        f = fz_pub[oid]
        i0, i1, j0, j1 = f["box"]
        var = ep.variance[i0:i1, j0:j1]
        good = np.isfinite(f["residual"])
        zr = (f["residual"] / np.sqrt(var))[good]
        amps = []
        for _ in range(300):
            img = ep.image.copy()
            sim = f["model"].copy()
            sim[good] += rng.choice(zr, zr.size) * np.sqrt(var[good])
            img[i0:i1, j0:j1] = np.where(good, sim, img[i0:i1, j0:j1])
            amps.append(P.fit(img, ep.variance, ep.bad, f["x"], f["y"], e)["amp"])
        un.append({"epoch": oid, "formal_frac": f["amp_err"] / f["amp"], "chi2_scaled_frac": f["amp_err_scaled"] / f["amp"],
                   "bootstrap_frac": float(np.std(amps) / f["amp"]),
                   "model_error_0.02_frac": fz_cal[oid]["amp_err_scaled"] / fz_cal[oid]["amp"]})
    ap = {}
    for p in rob["targets"]["rw_aur"]["pairs"]:
        ap.setdefault(p["a"], []).append(p["fa"])
        ap.setdefault(p["b"], []).append(p["fb"])
    lr = {k: math.log(np.mean(v) / fz_pub[k]["amp"]) for k, v in ap.items()}
    lr_cal = {k: math.log(np.mean(v) / fz_cal[k]["amp"]) for k, v in ap.items()}
    out["uncertainty"] = {
        "per_epoch": un, **{k: _stats([u[k] for u in un]) for k in un[0] if k != "epoch"},
        "ln_aperture_over_epsf_scatter_between_epochs": {"published": float(np.std(list(lr.values()), ddof=1)),
                                                         "field_stars+sky_scale+model_error_0.02": float(np.std(list(lr_cal.values()), ddof=1))},
        "note": "Bootstrap resamples the normalised residuals at the fitted position (300 draws); "
                "it ignores their spatial structure, so like chi2 scaling it treats a PSF-shape error as noise."}
    # Figure data (not written to the JSON): the worst-blended epoch with and without field stars.
    oid, ep, e, _ = max(rw, key=lambda r: next(b["worst_pixel_share_of_chi2"] for b in bl if b["epoch"] == r[0]))
    maps = []
    for nb in ((), field_neighbours(ep, "rw_aur")):
        f = P.fit(ep.image, ep.variance, ep.bad, ep.x, ep.y, e, fit_position=True, neighbours=nb)
        i0, i1, j0, j1 = f["box"]
        maps.append((f["residual"] / np.sqrt(ep.variance[i0:i1, j0:j1]), f["chi2_red"]))
    stars = [(s_["x"] - j0, s_["y"] - i0, s_["g"]) for s_ in gaia_pixels(ep)[2:]
             if -1.5 <= s_["x"] - j0 <= 9.5 and -1.5 <= s_["y"] - i0 <= 9.5]
    out["_fig"] = {"epochs": [r[0] for r in rw], "chi2": figchi, "map_epoch": oid, "maps": maps, "stars": stars,
                   "radii": [(a + b) / 2 for a, b in zip(pb[:-1], pb[1:])],
                   "resid_profile": out["morphology"]["mean_residual_over_flux_per_px_13x13"],
                   "model_profile": out["morphology"]["epsf_model_over_flux_per_px"]}
    out["seconds"] = time.perf_counter() - clock
    return out


def diagnostics_figure(fd, path):
    """chi2 per epoch under each fix; residual maps with/without field stars; radial residual profile."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ink, muted = "#0b0b0b", "#52514e"
    series = [("published", "as published", "#2a78d6", "o"), ("field_stars", "+ Gaia field stars", "#eb6834", "s"),
              ("field_stars+sky_scale", "+ field stars, VARIANCE x sky scale$^2$", "#1baf7a", "^")]
    fig = plt.figure(figsize=(10, 3.2))
    gs = fig.add_gridspec(1, 4, width_ratios=[1.6, 0.8, 0.8, 1.3], wspace=0.35)
    a = fig.add_subplot(gs[0])
    x = np.arange(len(fd["epochs"]))
    for key, lab, col, mk in series:
        a.plot(x, fd["chi2"][key], marker=mk, ms=5, lw=1.2, color=col, label=lab)
    a.axhline(1, color=muted, lw=0.8, ls=":")
    a.set_yscale("log")
    a.set_xticks(x, [e[-9:] for e in fd["epochs"]], rotation=60, fontsize=6)
    a.set_ylabel("reduced $\\chi^2$", fontsize=8)
    a.set_title("RW Aur, 10 epochs", fontsize=8, color=ink)
    a.legend(fontsize=6, frameon=False, loc="upper left")
    a.tick_params(labelsize=7)
    for k, (m, c2) in enumerate(fd["maps"]):
        b = fig.add_subplot(gs[1 + k])
        b.imshow(m, origin="lower", cmap="RdBu_r", vmin=-5, vmax=5)
        for sx, sy, g in fd["stars"]:
            b.plot(sx, sy, marker="o", mfc="none", mec=ink, ms=9, mew=0.8, clip_on=False)
            b.text(sx, sy + 0.7, f"G={g:.1f}", fontsize=5, ha="center", color=ink, clip_on=False)
        b.set_xlim(-0.5, 8.5), b.set_ylim(-0.5, 8.5)
        b.set_title(f"{'without' if k == 0 else 'with'} field stars\n$\\chi^2_r$={c2:.1f}", fontsize=7, color=ink)
        if k == 0:
            b.text(-0.5, -2.9, f"{fd['map_epoch']}: residual/$\\sigma$, colour $\\pm$5", fontsize=6, color=muted)
        b.set_xticks([]), b.set_yticks([])
    c = fig.add_subplot(gs[3])
    c.plot(fd["radii"], np.array(fd["resid_profile"]) * 1e3, marker="o", ms=5, lw=1.2, color="#2a78d6",
           label="mean residual (median of epochs)")
    c.axhline(0, color=muted, lw=0.8)
    c.axvline(3.3, color=muted, lw=0.8, ls="--")
    c.text(3.4, c.get_ylim()[1] * 0.85, "ePSF table edge", fontsize=6, color=muted)
    c.set_xlabel("radius (native px)", fontsize=8)
    c.set_ylabel("per-pixel residual / flux ($10^{-3}$)", fontsize=8)
    c.set_title("13x13 box, field stars fitted", fontsize=8, color=ink)
    c.tick_params(labelsize=7)
    fig.suptitle("Why reduced $\\chi^2$ is high on RW Aur (EXPERIMENTAL ePSF check, real SPHEREx pixels)", fontsize=9)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    t0 = time.perf_counter()
    rob = json.loads((EVID / "robustness.json").read_text())
    report = {"status": "EXPERIMENTAL - not used by any published number",
              "method": {"fit_box_px": 2 * P.FIT_HALF + 1, "free_position_snr": FREE_POSITION_SNR,
                         "background": "constant", "weights": "1/VARIANCE", "grid": "native, no reprojection",
                         "error_scaling": "amp_err * sqrt(max(1, chi2_red))"},
              "agreement_rule": __doc__.split("Agreement rule (fixed before looking at the result):")[1].strip(),
              "targets": {}}
    figs = []
    for t in api.TARGETS:
        tid = t["id"]
        pairs = rob["targets"][tid].get("pairs") or []
        if not pairs:
            report["targets"][tid] = {"verdict": "not fitted: no usable epoch (saturated / flagged pixels)"}
            print(tid, "not fitted")
            continue
        paths = epoch_paths(t)
        need = sorted({p["a"] for p in pairs} | {p["b"] for p in pairs})
        fits_, meta = {}, {}
        for oid in need:
            ep, e, f = fit_epoch(paths[oid], oid, t)
            fits_[oid] = f
            meta[oid] = {"zone": e and e["zone"], "zone_dist_px": e and e["dist_px"],
                         "epsf_sha256": e and e["sha256"], "epsf_source": e and e["source"],
                         "detcoord": e and e["detcoord"]}
            if f["ok"] and tid == "rw_aur" and len(figs) < 2:
                figs.append((tid, oid, f))
        rows = pair_rows(pairs, fits_)
        counts = {k: sum(r["agreement"] == k for r in rows) for k in ("compatible", "inconclusive", "discrepant")}
        report["targets"][tid] = {"n_pairs": len(rows), "agreement_counts": counts, "pairs": rows, "epochs": meta,
                                  "fits": {k: {kk: v for kk, v in f.items()
                                               if kk not in ("residual", "model", "data")} for k, f in fits_.items()}}
        sigs = [r["sig_epsf"] for r in rows if "sig_epsf" in r]
        report["targets"][tid]["claims_with_epsf"] = {
            "max_abs_sig_epsf": max(map(abs, sigs), default=None),
            "n_pairs_ge_5sigma_epsf": sum(abs(v) >= 5 for v in sigs),
            "n_pairs_brighter_epsf": sum(v > 0 for v in sigs), "n_fitted": len(sigs)}
        print(tid, counts, report["targets"][tid]["claims_with_epsf"])
    # Combined label from the stability audit and the ePSF check. Fixed rule:
    #   SUPPORTED VARIABILITY: a robust aperture claim of change, every pair
    #     compatible between methods, and the change >= 5 sigma with the ePSF too;
    #   LIKELY ARTIFACT: a >= 5 sigma aperture change that the ePSF calls discrepant
    #     or does not reproduce;
    #   INSUFFICIENT DATA: no usable epoch;  INCONCLUSIVE: anything else
    #     (including "no change seen" at low S/N, which is not proof of constancy).
    for t in api.TARGETS:
        r, tr = report["targets"][t["id"]], rob["targets"][t["id"]]
        if "pairs" not in r:
            r["label"] = "INSUFFICIENT DATA"
            continue
        robust_change = any(c["verdict"] == "robust" and "brightened" in c["claim"] for c in tr.get("claims", []))
        c = r["agreement_counts"]
        ap5 = any(abs(p["sig_aperture"]) >= 5 for p in r["pairs"])
        if robust_change and c["compatible"] == r["n_pairs"] and r["claims_with_epsf"]["n_pairs_ge_5sigma_epsf"] > 0:
            r["label"] = "SUPPORTED VARIABILITY"
        elif ap5 and (c["discrepant"] > 0 or r["claims_with_epsf"]["n_pairs_ge_5sigma_epsf"] == 0):
            r["label"] = "LIKELY ARTIFACT"
        else:
            r["label"] = "INCONCLUSIVE"
        print(t["id"], r["label"])
    sim = simulated_checks(next(t for t in api.TARGETS if t["id"] == "wise0855"))
    report["simulated_injection"] = sim
    k = min(sim["difference_scatter_over_quadrature"].values())  # the strictest (smallest) factor
    for r in report["targets"]["rw_aur"]["pairs"]:
        if "z_agreement" in r:
            r["z_correlated"] = r["z_agreement"] / k
            r["agreement_correlated"] = label(r["z_correlated"])
    report["correlation_factor_used"] = k
    rc = report["targets"]["rw_aur"]
    rc["agreement_counts_correlated"] = {x: sum(p.get("agreement_correlated") == x for p in rc["pairs"])
                                        for x in ("compatible", "inconclusive", "discrepant")}
    print("correlated:", sim["difference_scatter_over_quadrature"], rc["agreement_counts_correlated"],
          [round(p["z_correlated"], 2) for p in rc["pairs"]])
    print("SIMULATED", sim["summary"])
    report["diagnostics"] = diagnostics(rob, None)
    dg = report["diagnostics"]
    diagnostics_figure(dg.pop("_fig"), FIG_DIAG)
    print("diagnostics:", {k: dg["variants"][k]["rw_aur"]["chi2_red"]["median"] for k in dg["variants"]},
          "model_error scan", dg["model_error_scan_rw_aur"])
    report["benchmark"] = {"seconds": time.perf_counter() - t0,
                           "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024}
    OUT.write_text(json.dumps(report, indent=1, default=float) + "\n")
    if figs:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(len(figs), 3, figsize=(7.5, 2.6 * len(figs)))
        for k, (tid, oid, f) in enumerate(figs):
            for j, (img, title) in enumerate(((f["data"], "data"), (f["model"], "ePSF model"),
                                              (f["residual"] / np.nanstd(f["residual"]), "residual / rms"))):
                a = ax[k, j]
                a.imshow(img, origin="lower", cmap="RdBu_r" if j == 2 else "magma",
                         vmin=-3 if j == 2 else None, vmax=3 if j == 2 else None)
                a.set_title(f"{oid[-12:]} {title}", fontsize=7)
                a.set_xticks([]), a.set_yticks([])
        fig.suptitle("RW Aur: ePSF fit on native SPHEREx pixels (EXPERIMENTAL)", fontsize=9)
        fig.tight_layout()
        fig.savefig(FIG, dpi=150)
    print("wrote", OUT, report["benchmark"])


if __name__ == "__main__":
    main()
