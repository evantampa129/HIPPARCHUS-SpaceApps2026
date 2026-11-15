"""Second, independent flux measurement: fit the SPHEREx ePSF to the native pixels.

EXPERIMENTAL. The production numbers come from aperture photometry on images
reprojected to a common grid (compare.py). Here we measure the same star a
different way, so we can check the two against each other:

* we read the effective PSF (ePSF) from the EPSF extension of the same cutout:
  a 21x21 grid of zones over the detector, each a 33x33 table oversampled x5;
* we use the zone whose centre is nearest the star in parent-detector
  pixels (cutout pixel + 1 - CRPIX1A, as in the IRSA SPHEREx PSF tutorial);
* model = amplitude * ePSF(star position) + constant background, fitted by
  weighted least squares (weights 1/variance) to the epoch's own pixels.
  We reproject nothing, so there is no interpolation noise.

The amplitude is the total flux of the star in the units of the image summed
over pixels (MJy/sr x pixel), the same units as the aperture sum but without
the aperture loss. We only compare ratios between epochs.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np
from astropy.io import fits
from scipy.ndimage import map_coordinates
from scipy.optimize import minimize

FIT_HALF = 4          # fit box: +-4 native pixels around the star (9x9)
MIN_PIXELS = 30       # fewer clean pixels than this and we refuse the fit


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


def _solve(img, var, X):
    """Weighted linear least squares; X columns: star, [neighbours], background terms."""
    w = 1.0 / var
    XtW = X.T * w
    cov = np.linalg.inv(XtW @ X)
    beta = cov @ (XtW @ img)
    resid = img - X @ beta
    return beta, cov, float(np.sum(resid ** 2 * w)), resid


def native_sum(psf: np.ndarray, ovs: int, x0: float, y0: float) -> float:
    """Sum of the rendered ePSF over every native pixel it touches, at this sub-pixel phase.

    It is ~1 but not exactly: 0.983-1.018 for the RW Aur zones (11x11 phases), depending on
    where the star falls inside its pixel (cubic sampling of a table that is
    only 33/ovs = 6.6 native pixels wide). Used by normalise_native.
    """
    r = int(math.ceil(psf.shape[0] / (2 * ovs))) + 1
    yy, xx = np.mgrid[round(y0) - r:round(y0) + r + 1, round(x0) - r:round(x0) + r + 1].astype(float)
    return float(render(psf, ovs, x0, y0, xx, yy).sum())


def fit(image, variance, bad, x0, y0, epsf: dict, fit_position: bool = False, half: int = FIT_HALF,
        background: str = "constant", neighbours=(), model_error: float = 0.0, var_scale: float = 1.0,
        normalise_native: bool = False) -> dict:
    """Fit amplitude (+ background) of the ePSF at (x0, y0) on the native grid.

    The defaults reproduce the published experimental check. We added the
    options while looking for the cause of the high reduced chi2 on RW Aur
    (reproduce_epsf.py, "diagnostics"); none of them is used by a published number:

    background        "constant", "plane" (constant + x and y gradient) or "none"
                      (the caller has already subtracted a sky, e.g. an annulus median).
    neighbours        (x, y) cutout pixels of other catalogue stars; each is fitted
                      with its own free amplitude at that position. With a free
                      position they move with the target: the offset is a WCS
                      error, common to the whole cutout.
    model_error       fractional ePSF error: (model_error * star model)**2 is added
                      to each pixel's variance (3 iterations, the model changes).
    var_scale         multiplies the VARIANCE plane (excess sky scatter measured
                      by blank_sky_scale).
    normalise_native  divide the model by native_sum, so the amplitude does not
                      depend on the sub-pixel phase (up to ~1.8%).
    """
    ny, nx = image.shape
    i0, i1 = int(round(y0)) - half, int(round(y0)) + half + 1
    j0, j1 = int(round(x0)) - half, int(round(x0)) + half + 1
    warn = []
    if i0 < 0 or j0 < 0 or i1 > ny or j1 > nx:
        return {"ok": False, "reason": "fit box leaves the cutout"}
    if background not in ("constant", "plane", "none"):
        raise ValueError(f"unknown background model {background!r}")
    yy, xx = np.mgrid[i0:i1, j0:j1].astype(float)
    img, var, b = image[i0:i1, j0:j1], variance[i0:i1, j0:j1] * var_scale, bad[i0:i1, j0:j1]
    good = ~b & np.isfinite(img) & np.isfinite(var) & (var > 0)
    core = (xx - x0) ** 2 + (yy - y0) ** 2 <= 1.5 ** 2
    if (core & ~good).any():
        # Same rule as the aperture photometry: if a flagged pixel sits on the star, we refuse the fit.
        return {"ok": False, "reason": "flagged pixel in the PSF core"}
    if good.sum() < MIN_PIXELS:
        return {"ok": False, "reason": f"only {int(good.sum())} clean pixels"}
    psf, ovs = epsf["psf"], epsf["ovs"]
    # We fit a neighbour only if >3% of its light lands on clean pixels of the
    # box, and decide that once, at the start position, so the chi2 surface stays smooth.
    nbs = [(float(a), float(c)) for a, c in neighbours
           if render(psf, ovs, a, c, xx, yy)[good].sum() > 0.03]

    sky_cols = {"constant": [np.ones_like(xx)], "plane": [np.ones_like(xx), xx - x0, yy - y0], "none": []}[background]

    def star(px, py):
        P = render(psf, ovs, px, py, xx, yy)
        return P / native_sum(psf, ovs, px, py) if normalise_native else P

    def run(px, py):
        P = star(px, py)
        cols = [P] + [render(psf, ovs, a + px - x0, c + py - y0, xx, yy) for a, c in nbs] + sky_cols
        X = np.stack([c[good] for c in cols], axis=1)
        v = var[good]
        for _ in range(3 if model_error > 0 else 1):
            beta, cov, chi2, resid = _solve(img[good], v, X)
            v = var[good] + (model_error * beta[0] * P[good]) ** 2
        return beta, cov, chi2, resid, P

    pos = (x0, y0)
    if fit_position:
        res = minimize(lambda p: run(*p)[2], [x0, y0], method="Nelder-Mead",
                       options={"xatol": 1e-3, "fatol": 1e-3, "maxiter": 400})
        if math.hypot(res.x[0] - x0, res.x[1] - y0) < 1.0:
            pos = (float(res.x[0]), float(res.x[1]))
        else:
            warn.append("free position moved >1 px; kept the WCS position")
    beta, cov, chi2, resid, P = run(*pos)
    # We don't subtract the position parameters (kept as published); with a free
    # position the true dof is 2 smaller (~2.5% on a 9x9 box).
    dof = int(good.sum()) - len(beta)
    k = len(nbs) + 1
    amp, bkg = float(beta[0]), (float(beta[k]) if sky_cols else 0.0)
    amp_err = float(math.sqrt(cov[0, 0]))
    red = chi2 / dof
    if red > 3:
        warn.append(f"reduced chi2 {red:.1f}: the ePSF does not describe these pixels well")
    if P[good].sum() < 0.8:
        warn.append("less than 80% of the ePSF falls on clean pixels in the box")
    full = np.full(img.shape, np.nan)
    full[good] = resid
    model = np.stack([P] + [render(psf, ovs, a + pos[0] - x0, c + pos[1] - y0, xx, yy) for a, c in nbs]
                     + sky_cols, -1) @ beta
    return {"ok": True, "amp": amp, "amp_err": amp_err, "bkg": bkg,
            "bkg_err": float(math.sqrt(cov[k, k])) if sky_cols else 0.0,
            "chi2_red": red, "dof": dof, "x": pos[0], "y": pos[1],
            "shift_px": math.hypot(pos[0] - x0, pos[1] - y0), "psf_sum_in_box": float(P.sum()),
            "neighbour_amps": [float(v) for v in beta[1:k]], "n_neighbours": len(nbs),
            "warnings": warn, "residual": full, "model": model, "data": img, "box": [i0, i1, j0, j1]}


def blank_sky_scale(image, variance, bad, x0, y0, r_min: float = 6.0) -> float:
    """Robust (MAD) scatter of sky pixels in units of sqrt(VARIANCE), local median removed.

    1.00 on the WISE 0855 cutouts (the VARIANCE plane is right there); ~1.34 in the
    RW Aur field, where faint stars and nebulosity add structure that is not noise
    but is not modelled either. We skip pixels within r_min of the target.
    """
    from scipy.ndimage import median_filter
    z = (image - median_filter(image, size=7, mode="nearest")) / np.sqrt(variance)
    ny, nx = image.shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    m = ~bad & np.isfinite(z) & (variance > 0) & (np.hypot(xx - x0, yy - y0) > r_min)
    m[:2] = m[-2:] = False
    m[:, :2] = m[:, -2:] = False
    zz = z[m]
    return float(1.4826 * np.median(np.abs(zz - np.median(zz)))) if zz.size > 20 else float("nan")


def compare(fa: dict, fb: dict) -> dict:
    """Flux ratio and significance between two independent ePSF fits."""
    err = math.hypot(fa["amp_err"], fb["amp_err"])
    return {"ratio": fb["amp"] / fa["amp"] if fa["amp"] > 0 else float("nan"),
            "sig": (fb["amp"] - fa["amp"]) / err, "err": err}


