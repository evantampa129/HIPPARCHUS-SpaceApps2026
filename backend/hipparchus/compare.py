"""Decide whether two SPHEREx epochs can be compared, and compare them if so."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
from reproject import reproject_interp

from hipparchus.quality import APERTURE_PX, Epoch

# Two exposures are only comparable if the target was seen at (nearly) the same
# wavelength. Because of the linear variable filters, the same star lands on a
# different part of the detector in each visit, and so at a different
# wavelength. A brightness "change" between 1.2 and 1.4 microns is just the
# star's spectrum, not variability. We allow a shift of at most half of one
# spectral channel's width.
MAX_DLAMBDA_FRACTION = 0.5

# Exposures closer than this in time come from the same visit. They are still
# useful, but as a null test: any "change" there measures our own noise.
SAME_VISIT_DAYS = 0.5

# A difference counts as real only above this significance. 5 sigma keeps the
# expected number of false alarms tiny even when we test many pairs.
DETECTION_SIGMA = 5.0

# Annulus (pixels) used to measure the local sky level around the target.
SKY_INNER, SKY_OUTER = 4.0, 7.0


@dataclass
class Verdict:
    comparable: bool
    kind: str                  # "comparison", "null_test" or "refused"
    reasons: list[str] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)   # one stable code per reason, for counting


def compatibility(a: Epoch, b: Epoch) -> Verdict:
    """Check, before touching any pixels, whether a and b may be compared."""
    reasons, codes = [], []
    for e in (a, b):
        for i in e.issues:
            if i.severity == "reject":
                reasons.append(f"{e.obs_id}: {i.message}")
                codes.append(i.code)
    if a.detector != b.detector:
        reasons.append(f"Different detectors (D{a.detector} vs D{b.detector}) see different wavelength ranges.")
        codes.append("different_detector")
    dlam = abs(a.wavelength_um - b.wavelength_um)
    limit = MAX_DLAMBDA_FRACTION * min(a.bandwidth_um, b.bandwidth_um)
    if dlam > limit:
        reasons.append(
            f"The target was observed at {a.wavelength_um:.3f} um and {b.wavelength_um:.3f} um. "
            f"The shift of {dlam:.3f} um is larger than the {limit:.3f} um allowed, so a change in "
            f"brightness could just be the spectrum.")
        codes.append("wavelength_mismatch")
    if reasons:
        return Verdict(False, "refused", reasons, codes)
    if abs(b.mjd - a.mjd) < SAME_VISIT_DAYS:
        return Verdict(True, "null_test", ["Both exposures come from the same visit, so this pair tests our noise level."], ["same_visit"])
    return Verdict(True, "comparison", [], [])


def _rings(shape, x, y):
    ny, nx = shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    d2 = (xx - x) ** 2 + (yy - y) ** 2
    ap = d2 <= APERTURE_PX ** 2
    sky = (d2 >= SKY_INNER ** 2) & (d2 <= SKY_OUTER ** 2)
    return ap, sky


def photometry(img, var, bad, x, y) -> dict:
    """Aperture sum minus the local sky, with its 1-sigma uncertainty.

    Values are in MJy/sr summed over pixels. That is enough to compare two
    epochs of the same detector and wavelength; converting to an absolute flux
    density would also need the pixel solid angle, which cancels in a ratio.
    """
    ap, sky = _rings(img.shape, x, y)
    sky_ok = sky & ~bad & np.isfinite(img)
    # The median ignores stars that fall inside the annulus.
    bkg = float(np.median(img[sky_ok])) if sky_ok.sum() >= 8 else 0.0
    n = int(ap.sum())
    flux = float(np.sum(img[ap] - bkg))
    # Uncertainty: pixel variances in the aperture, plus the error of the sky
    # level estimate, which is subtracted from every one of the n pixels.
    sky_err2 = float(np.var(img[sky_ok]) / max(sky_ok.sum(), 1)) if sky_ok.sum() >= 8 else 0.0
    err = float(np.sqrt(np.sum(var[ap]) + n ** 2 * sky_err2))
    return {"flux": flux, "flux_err": err, "sky": bkg, "n_pix": n}


def centroid(img, bad, x0, y0, half=3) -> tuple[float, float]:
    """Light-weighted centre of the star within a small box around (x0, y0)."""
    ny, nx = img.shape
    xs, ys = int(round(x0)), int(round(y0))
    y1, y2 = max(ys - half, 0), min(ys + half + 1, ny)
    x1, x2 = max(xs - half, 0), min(xs + half + 1, nx)
    box = img[y1:y2, x1:x2].copy()
    box[bad[y1:y2, x1:x2]] = np.nan
    # Use only the light above the box median, so the sky does not pull the
    # centre towards the middle of the box.
    w = np.clip(box - np.nanmedian(box), 0, None)
    w[~np.isfinite(w)] = 0
    if w.sum() <= 0:
        return float("nan"), float("nan")
    yy, xx = np.mgrid[y1:y2, x1:x2]
    return float((w * xx).sum() / w.sum()), float((w * yy).sum() / w.sum())


def control_star(img, bad, x, y, min_sep=APERTURE_PX + SKY_OUTER, edge=APERTURE_PX + 1):
    """Brightest clean pixel away from the target, used as a constancy check.

    If the target "changes" but a neighbouring star in the same two images does
    not, the change is unlikely to come from calibration or the method itself.
    Returns pixel (x, y) or None when no suitable star is in the cutout.
    """
    ny, nx = img.shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    ok = (~bad & np.isfinite(img)
          # Far enough that the target's light does not fall in the control
          # star's sky annulus. Near the cutout edge part of the annulus is
          # missing; photometry() then uses the sky pixels that remain.
          & ((xx - x) ** 2 + (yy - y) ** 2 >= min_sep ** 2)
          & (xx >= edge) & (xx <= nx - 1 - edge) & (yy >= edge) & (yy <= ny - 1 - edge))
    # It must be the peak of a star (brighter than its 8 neighbours), not the
    # wing of a star whose centre lies outside the cutout.
    from scipy.ndimage import maximum_filter
    filled = np.where(np.isfinite(img), img, -np.inf)
    ok &= filled == maximum_filter(filled, size=3, mode="constant", cval=-np.inf)
    if not ok.any():
        return None
    cand = np.where(ok, img, -np.inf)
    j = int(np.argmax(cand))
    return float(xx.flat[j]), float(yy.flat[j])


def compare(a: Epoch, b: Epoch) -> dict:
    """Full comparison of epoch b against epoch a, on a's pixel grid."""
    verdict = compatibility(a, b)
    out = {
        "a": a.obs_id, "b": b.obs_id,
        "dt_days": b.mjd - a.mjd,
        "lambda_a_um": a.wavelength_um, "lambda_b_um": b.wavelength_um,
        "verdict": asdict(verdict),
    }
    if not verdict.comparable:
        return out

    # Put b on a's pixel grid. The two visits have different pointings and
    # rotations, so subtracting raw arrays would compare different sky.
    # Interpolating the variance the same way is an approximation (it slightly
    # smooths the noise), which we accept for a quick-look difference.
    b_img, footprint = reproject_interp((b.image, b.wcs), a.wcs, shape_out=a.image.shape)
    b_var, _ = reproject_interp((b.variance, b.wcs), a.wcs, shape_out=a.image.shape)
    b_bad, _ = reproject_interp((b.bad.astype(float), b.wcs), a.wcs, shape_out=a.image.shape)
    bad = a.bad | (b_bad > 0) | (footprint == 0) | ~np.isfinite(b_img)

    pa = photometry(a.image, a.variance, a.bad, a.x, a.y)
    pb = photometry(b_img, b_var, bad, a.x, a.y)
    dflux = pb["flux"] - pa["flux"]
    dflux_err = float(np.hypot(pa["flux_err"], pb["flux_err"]))
    sig = dflux / dflux_err if dflux_err > 0 else float("nan")

    # Constancy check on another star in the same two images. Its own
    # significance should be small; if it is large too, the "change" is more
    # likely a calibration difference between the epochs than real variability.
    ctrl = None
    pos = control_star(a.image, bad, a.x, a.y)
    if pos is not None:
        ca_ = photometry(a.image, a.variance, a.bad, *pos)
        cb_ = photometry(b_img, b_var, bad, *pos)
        e = float(np.hypot(ca_["flux_err"], cb_["flux_err"]))
        # Only meaningful if the control star is clearly detected in epoch a.
        if ca_["flux"] > 10 * ca_["flux_err"]:
            ctrl = {"x": pos[0], "y": pos[1], "flux_a": ca_["flux"], "flux_b": cb_["flux"],
                    "ratio": cb_["flux"] / ca_["flux"], "significance": (cb_["flux"] - ca_["flux"]) / e if e > 0 else None}

    # Where is the star in each epoch? The shift between the two centroids,
    # turned into arcseconds on the sky, is a direct measurement of motion.
    ca = centroid(a.image, a.bad, a.x, a.y)
    cb = centroid(b_img, bad, a.x, a.y)
    wa = a.wcs.pixel_to_world_values(*ca)
    wb = a.wcs.pixel_to_world_values(*cb)
    dra = (float(wb[0]) - float(wa[0])) * np.cos(np.radians(float(wa[1]))) * 3600
    ddec = (float(wb[1]) - float(wa[1])) * 3600

    # Significance map: the difference divided by its own noise, pixel by pixel.
    diff = (b_img - pb["sky"]) - (a.image - pa["sky"])
    z = diff / np.sqrt(a.variance + b_var)
    z[bad] = np.nan

    out.update({
        "flux_a": pa, "flux_b": pb,
        "delta_flux": dflux, "delta_flux_err": dflux_err, "significance": sig,
        "changed": bool(abs(sig) >= DETECTION_SIGMA),
        "flux_ratio": pb["flux"] / pa["flux"] if pa["flux"] > 0 else None,
        "control_star": ctrl,
        "centroid_shift_arcsec": {"dra": dra, "ddec": ddec, "total": float(np.hypot(dra, ddec))},
        "max_abs_z": float(np.nanmax(np.abs(z))) if np.isfinite(z).any() else None,
        # Kept in memory for the images and the validation checks; not serialised.
        "_arrays": {"a": a.image, "b": b_img, "diff": diff, "z": z,
                    "a_var": a.variance, "b_var": b_var, "a_bad": a.bad, "bad": bad},
    })
    return out
