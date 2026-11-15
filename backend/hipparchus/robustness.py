"""How much do the conclusions depend on our analysis choices?

Four checks, all run on the real comparisons from pipeline.analyze():

* stability(): repeat the photometry with other reasonable aperture radii, sky
  annuli, masks and calibrations, and see whether the conclusion survives.
* ensemble(): use every clean, isolated star in the cutout (not just one) to
  measure how much the whole field changed between two epochs.
* systematic_floor(): turn the scatter of those field stars into a fractional
  calibration error and add it to the formal error of the target.
* trials(): what a 5 sigma threshold means when many pairs are tested.

Nothing here changes the production measurement; we report it alongside.
The labels robust / sensitive / inconclusive follow the explicit rule in
classify(). They are not probabilities.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import binary_dilation, maximum_filter
from scipy.stats import norm

from hipparchus.compare import DETECTION_SIGMA, SKY_INNER, SKY_OUTER, photometry
from hipparchus.quality import APERTURE_PX

# Variations around the production settings (r=2, annulus 4-7 px). Each is a
# choice another careful analyst could reasonably have made with 6.15" pixels
# and a PSF FWHM of about 1.5 px; none is tuned on the results.
APERTURES = (1.5, 2.0, 2.5, 3.0)
ANNULI = ((3.5, 6.0), (4.0, 7.0), (5.0, 8.0))
MASKS = ("as_flagged", "flags_grown_1px")
CALIBRATIONS = ("none", "ensemble")

# Field stars we use for the ensemble: a local peak, detected at S/N >= 10 in
# epoch a (the same bar as the single control star in compare.py), at least
# this far from the target and from any brighter accepted star, and with no
# flagged pixel in its aperture in either epoch. Near the cutout edge part of
# the sky annulus is missing; photometry() needs 8 clean sky pixels or refuses.
ENSEMBLE_MIN_SNR = 10.0
ENSEMBLE_MIN_SEP = APERTURE_PX + SKY_OUTER
ISOLATION_PX = 4.0


def _phot_pair(A: dict, x: float, y: float, r_ap: float, r_in: float, r_out: float, grow: bool) -> dict | None:
    a_bad, bad = A["a_bad"], A["bad"]
    if grow:
        a_bad = binary_dilation(a_bad)
        bad = binary_dilation(bad)
    pa = photometry(A["a"], A["a_var"], a_bad, x, y, r_ap, r_in, r_out)
    pb = photometry(A["b"], A["b_var"], bad, x, y, r_ap, r_in, r_out)
    if not (np.isfinite(pa["flux"]) and np.isfinite(pb["flux"])) or pa["flux"] <= 0:
        return None
    err = math.hypot(pa["flux_err"], pb["flux_err"])
    return {"ratio": pb["flux"] / pa["flux"], "sig": (pb["flux"] - pa["flux"]) / err,
            "fa": pa["flux"], "fb": pb["flux"], "err": err}


def field_stars(A: dict, tx: float, ty: float) -> list[tuple[float, float]]:
    """Candidate reference stars in a cutout (pixel positions on a's grid)."""
    img = A["a"]
    ny, nx = img.shape
    filled = np.where(np.isfinite(img), img, -np.inf)
    peaks = (filled == maximum_filter(filled, size=3, mode="constant", cval=-np.inf)) & np.isfinite(img)
    edge = APERTURE_PX + 1  # the aperture itself must fit inside the cutout
    yy, xx = np.nonzero(peaks)
    pts = [(float(x), float(y)) for x, y in zip(xx, yy)
           if edge <= x <= nx - 1 - edge and edge <= y <= ny - 1 - edge
           and math.hypot(x - tx, y - ty) >= ENSEMBLE_MIN_SEP]
    out = []
    for x, y in pts:
        r = _phot_pair(A, x, y, APERTURE_PX, SKY_INNER, SKY_OUTER, False)
        if r is None or r["fa"] < ENSEMBLE_MIN_SNR * r["err"] / math.sqrt(2):
            continue
        out.append((x, y, r["fa"]))
    # Isolation: we drop a star if a brighter accepted one is within ISOLATION_PX.
    out.sort(key=lambda s: -s[2])
    kept: list[tuple[float, float, float]] = []
    for s in out:
        if all(math.hypot(s[0] - k[0], s[1] - k[1]) >= ISOLATION_PX for k in kept):
            kept.append(s)
    return [(x, y) for x, y, _ in kept]


def ensemble(A: dict, tx: float, ty: float, r_ap=APERTURE_PX, r_in=SKY_INNER, r_out=SKY_OUTER,
             grow=False) -> dict:
    """Median flux ratio b/a of the field stars, with a robust scatter."""
    ratios = []
    for x, y in field_stars(A, tx, ty):
        r = _phot_pair(A, x, y, r_ap, r_in, r_out, grow)
        if r is not None:
            ratios.append(r["ratio"])
    n = len(ratios)
    if n == 0:
        return {"n": 0, "median": None, "scatter": None}
    med = float(np.median(ratios))
    mad = float(1.4826 * np.median(np.abs(np.array(ratios) - med))) if n >= 3 else None
    return {"n": n, "median": med, "scatter": mad, "ratios": [float(v) for v in ratios]}


def trials(n_tests: int, sigma: float = DETECTION_SIGMA) -> dict:
    """Chance of at least one false |z| >= sigma among n independent Gaussian tests."""
    p1 = 2 * norm.sf(sigma)
    fwer = 1 - (1 - p1) ** n_tests
    return {"n_tests": n_tests, "p_single": p1, "p_any_false_alarm": fwer,
            # Threshold that keeps the family-wise rate at the single-test 5 sigma level.
            "sigma_bonferroni": float(norm.isf(p1 / 2 / max(n_tests, 1)))}


def systematic_floor(pairs: list[dict]) -> float | None:
    """Fractional calibration error between epochs, from the field stars.

    The robust scatter of the ensemble medians around 1 over all pairs of a
    target; None when fewer than three pairs have an ensemble.
    """
    meds = [p["ensemble"]["median"] for p in pairs if p["ensemble"]["median"] is not None]
    if len(meds) < 3:
        return None
    m = np.array(meds)
    return float(1.4826 * np.median(np.abs(m - 1.0)))


def stability(A: dict, tx: float, ty: float) -> list[dict]:
    """Ratio and significance of the target for every combination of choices."""
    rows = []
    for r_ap in APERTURES:
        for r_in, r_out in ANNULI:
            for mask in MASKS:
                grow = mask == "flags_grown_1px"
                t = _phot_pair(A, tx, ty, r_ap, r_in, r_out, grow)
                if t is None:
                    rows.append({"r_ap": r_ap, "annulus": [r_in, r_out], "mask": mask, "valid": False})
                    continue
                ens = ensemble(A, tx, ty, r_ap, r_in, r_out, grow)
                for cal in CALIBRATIONS:
                    if cal == "ensemble" and not ens["median"]:
                        continue
                    k = ens["median"] if cal == "ensemble" else 1.0
                    rows.append({"r_ap": r_ap, "annulus": [r_in, r_out], "mask": mask, "calibration": cal,
                                 "valid": True, "ratio": t["ratio"] / k,
                                 "sig": (t["fb"] / k - t["fa"]) / t["err"], "n_ref": ens["n"]})
    return rows


def classify(claim: str, per_config: list[bool]) -> str:
    """robust: the claim holds in every valid configuration; sensitive: in at
    least half; inconclusive: in fewer than half (or nothing could be measured)."""
    if not per_config:
        return "inconclusive"
    f = sum(per_config) / len(per_config)
    return "robust" if f == 1.0 else "sensitive" if f >= 0.5 else "inconclusive"


def _tan_wcs(crval, rot_deg=0.0, shift=(0.0, 0.0), n=29):
    from astropy.wcs import WCS
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = list(crval)
    w.wcs.crpix = [(n + 1) / 2 + shift[0], (n + 1) / 2 + shift[1]]
    s = 6.15 / 3600
    c, si = math.cos(math.radians(rot_deg)), math.sin(math.radians(rot_deg))
    w.wcs.cd = [[-s * c, s * si], [s * si, s * c]]
    return w


def reprojection_noise_mc(n_trials: int = 300, rot_deg: float = 37.0, seed: int = 1) -> dict:
    """Pure white noise, rotated and shifted onto another grid as in compare().

    We compare the real scatter of the aperture flux (and of single pixels)
    after reprojection with the error our code predicts from the
    reprojected variance. Ratios near 1 mean the aperture error is right.
    """
    from reproject import reproject_interp
    rng = np.random.default_rng(seed)
    n = 29
    wa = _tan_wcs((50.0, 10.0), 0.0, (0, 0), n)
    wb = _tan_wcs((50.0, 10.0), rot_deg, (0.37, -0.21), n)
    var = np.ones((n, n))
    v_rep, _ = reproject_interp((var, wb), wa, shape_out=(n, n))
    c = (n - 1) / 2
    fl, px = [], []
    for _ in range(n_trials):
        img = rng.standard_normal((n, n))
        rep, _ = reproject_interp((img, wb), wa, shape_out=(n, n))
        p = photometry(rep, v_rep, np.zeros((n, n), bool), c, c)
        fl.append(p["flux"])
        px.append(rep[int(c), int(c)])
    p = photometry(np.zeros((n, n)), v_rep, np.zeros((n, n), bool), c, c)
    from hipparchus.compare import bilinear_var_factor
    k = bilinear_var_factor(wa, wb, (n, n))[int(c), int(c)]
    return {"aperture_scatter_over_predicted": float(np.std(fl) / p["flux_err"]),
            "pixel_scatter_over_predicted_old": float(np.std(px) / math.sqrt(v_rep[int(c), int(c)])),
            "pixel_scatter_over_predicted": float(np.std(px) / math.sqrt(k * v_rep[int(c), int(c)])),
            "n_trials": n_trials, "rotation_deg": rot_deg}


def psf_mismatch_bias(fwhm_a: float, fwhm_b: float, r_ap: float = APERTURE_PX, n_phase: int = 25) -> dict:
    """Apparent flux ratio of a constant star whose PSF width differs between epochs.

    Gaussian PSFs integrated over pixels, averaged over sub-pixel positions
    (SPHEREx is undersampled, so the star's position inside a pixel matters).
    """
    n = 29
    yy, xx = np.mgrid[0:n, 0:n]
    rng = np.random.default_rng(0)

    def star(fwhm, x0, y0):
        from scipy.special import erf
        s = fwhm / 2.3548 * math.sqrt(2)
        gx = 0.5 * (erf((xx + 0.5 - x0) / s) - erf((xx - 0.5 - x0) / s))
        gy = 0.5 * (erf((yy + 0.5 - y0) / s) - erf((yy - 0.5 - y0) / s))
        return gx * gy

    ratios = []
    z = np.zeros((n, n), bool)
    for _ in range(n_phase):
        x0, y0 = 14 + rng.uniform(-0.5, 0.5), 14 + rng.uniform(-0.5, 0.5)
        fa = photometry(star(fwhm_a, x0, y0), np.full((n, n), 1e-6), z, x0, y0, r_ap)["flux"]
        fb = photometry(star(fwhm_b, x0, y0), np.full((n, n), 1e-6), z, x0, y0, r_ap)["flux"]
        ratios.append(fb / fa)
    return {"fwhm_a_px": fwhm_a, "fwhm_b_px": fwhm_b, "r_ap_px": r_ap,
            "ratio_mean": float(np.mean(ratios)), "ratio_min": float(np.min(ratios)),
            "ratio_max": float(np.max(ratios))}
