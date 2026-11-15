"""Second, independent flux measurement: fit the SPHEREx ePSF to the native pixels.

EXPERIMENTAL. The production numbers come from aperture photometry on images
reprojected to a common grid (compare.py). This module measures the same star
a different way, so the two can be checked against each other:

* the effective PSF (ePSF) is read from the EPSF extension of the same cutout:
  a 21x21 grid of zones over the detector, each a 33x33 table oversampled x5;
* the zone is the one whose centre is nearest the star in parent-detector
  pixels (cutout pixel + 1 - CRPIX1A, as in the IRSA SPHEREx PSF tutorial);
* model = amplitude * ePSF(star position) + constant background, fitted by
  weighted least squares (weights 1/variance) to the epoch's own pixels.
  Nothing is reprojected, so there is no interpolation noise.

The amplitude is the total flux of the star in the units of the image summed
over pixels (MJy/sr x pixel), the same units as the aperture sum but without
the aperture loss. Only ratios between epochs are compared.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np
from astropy.io import fits
from scipy.ndimage import map_coordinates
from scipy.optimize import minimize

FIT_HALF = 4          # fit box: +-4 native pixels around the star (9x9)
MIN_PIXELS = 30       # fewer clean pixels than this and the fit is refused


def load_epsf(path_or_hdul, x_cut: float, y_cut: float) -> dict | None:
    """ePSF for a star at cutout pixel (x_cut, y_cut), 0-based. None if absent or broken."""
    own = not isinstance(path_or_hdul, fits.HDUList)
    h = fits.open(path_or_hdul) if own else path_or_hdul
    try:
        if "EPSF" not in h or "IMAGE" not in h:
            return None
        t, hdr = h["EPSF"].data, h["EPSF"].header
        ih = h["IMAGE"].header
        if t is None or "EPSF" not in t.columns.names or "CRPIX1A" not in ih:
            return None
        ovs = int(hdr.get("OVSMPX", 0))
        if ovs < 1 or int(hdr.get("OVSMPY", ovs)) != ovs:
            return None
        xo = x_cut + 1 - float(ih["CRPIX1A"])
        yo = y_cut + 1 - float(ih["CRPIX2A"])
        d2 = (t["XCENTER"] - xo) ** 2 + (t["YCENTER"] - yo) ** 2
        i = int(np.argmin(d2))
        psf = np.asarray(t["EPSF"][i], float)
        n = int(round(math.sqrt(psf.size)))
        if n * n != psf.size or not np.all(np.isfinite(psf)) or psf.sum() <= 0:
            return None
        psf = psf.reshape(n, n)  # rows = y, "x-fast then y" (EPSF header ORDERING)
        return {"psf": psf, "ovs": ovs, "zone": i,
                "zone_center": [float(t["XCENTER"][i]), float(t["YCENTER"][i])],
                "dist_px": float(math.sqrt(d2[i])), "parent_xy": [xo, yo],
                "detcoord": str(hdr.get("DETCOORD", "")),
                "source": next((str(v) for v in hdr.get("HISTORY", []) if "source file" in str(v)), None),
                "sha256": hashlib.sha256(psf.tobytes()).hexdigest()}
    except (KeyError, ValueError, TypeError):
        return None
    finally:
        if own:
            h.close()


def render(psf: np.ndarray, ovs: int, x0: float, y0: float, xx: np.ndarray, yy: np.ndarray) -> np.ndarray:
    """ePSF sampled at native pixel centres (xx, yy) for a star at (x0, y0).

    The ePSF already includes the pixel response, so a native pixel's value is
    the table value at that offset; ovs**2 turns the oversampled normalisation
    (sum = 1 over the fine grid) into sum ~ 1 over native pixels.
    """
    c = (psf.shape[0] - 1) / 2
    u = c + ovs * (xx - x0)
    v = c + ovs * (yy - y0)
    return ovs ** 2 * map_coordinates(psf, [v.ravel(), u.ravel()], order=3, mode="constant",
                                      cval=0.0).reshape(xx.shape)


def _solve(img, var, P):
    """Weighted linear least squares for amplitude and background."""
    w = 1.0 / var
    X = np.stack([P, np.ones_like(P)], axis=1)
    XtW = X.T * w
    cov = np.linalg.inv(XtW @ X)
    beta = cov @ (XtW @ img)
    resid = img - X @ beta
    return beta, cov, float(np.sum(resid ** 2 * w)), resid


def fit(image, variance, bad, x0, y0, epsf: dict, fit_position: bool = False, half: int = FIT_HALF) -> dict:
    """Fit amplitude (+ background) of the ePSF at (x0, y0) on the native grid."""
    ny, nx = image.shape
    i0, i1 = int(round(y0)) - half, int(round(y0)) + half + 1
    j0, j1 = int(round(x0)) - half, int(round(x0)) + half + 1
    warn = []
    if i0 < 0 or j0 < 0 or i1 > ny or j1 > nx:
        return {"ok": False, "reason": "fit box leaves the cutout"}
    yy, xx = np.mgrid[i0:i1, j0:j1].astype(float)
    img, var, b = image[i0:i1, j0:j1], variance[i0:i1, j0:j1], bad[i0:i1, j0:j1]
    good = ~b & np.isfinite(img) & np.isfinite(var) & (var > 0)
    core = (xx - x0) ** 2 + (yy - y0) ** 2 <= 1.5 ** 2
    if (core & ~good).any():
        # Same rule as the aperture photometry: a flagged pixel on the star refuses the fit.
        return {"ok": False, "reason": "flagged pixel in the PSF core"}
    if good.sum() < MIN_PIXELS:
        return {"ok": False, "reason": f"only {int(good.sum())} clean pixels"}
    psf, ovs = epsf["psf"], epsf["ovs"]

    def run(px, py):
        P = render(psf, ovs, px, py, xx, yy)
        return _solve(img[good], var[good], P[good]) + (P,)

    pos = (x0, y0)
    if fit_position:
        res = minimize(lambda p: run(*p)[2], [x0, y0], method="Nelder-Mead",
                       options={"xatol": 1e-3, "fatol": 1e-3, "maxiter": 400})
        if math.hypot(res.x[0] - x0, res.x[1] - y0) < 1.0:
            pos = (float(res.x[0]), float(res.x[1]))
        else:
            warn.append("free position moved >1 px; kept the WCS position")
    beta, cov, chi2, resid, P = run(*pos)
    dof = int(good.sum()) - 2
    amp, bkg = float(beta[0]), float(beta[1])
    amp_err = float(math.sqrt(cov[0, 0]))
    red = chi2 / dof
    if red > 3:
        warn.append(f"reduced chi2 {red:.1f}: the ePSF does not describe these pixels well")
    if P[good].sum() < 0.8:
        warn.append("less than 80% of the ePSF falls on clean pixels in the box")
    full = np.full(img.shape, np.nan)
    full[good] = resid
    return {"ok": True, "amp": amp, "amp_err": amp_err, "bkg": bkg, "bkg_err": float(math.sqrt(cov[1, 1])),
            "chi2_red": red, "dof": dof, "x": pos[0], "y": pos[1],
            "shift_px": math.hypot(pos[0] - x0, pos[1] - y0), "psf_sum_in_box": float(P.sum()),
            "warnings": warn, "residual": full, "model": amp * P + bkg, "data": img, "box": [i0, i1, j0, j1]}


def compare(fa: dict, fb: dict) -> dict:
    """Flux ratio and significance between two independent ePSF fits."""
    err = math.hypot(fa["amp_err"], fb["amp_err"])
    return {"ratio": fb["amp"] / fa["amp"] if fa["amp"] > 0 else float("nan"),
            "sig": (fb["amp"] - fa["amp"]) / err, "err": err}


