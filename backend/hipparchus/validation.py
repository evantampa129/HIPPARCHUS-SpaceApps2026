"""Checks of the method itself: are the error bars right, and what can it detect?

Both checks reuse the real reprojected image pairs of a finished analysis.

* Null test (blank apertures): we run the same photometry at many places in
  the field away from the target. Almost everything there (sky, or ordinary
  constant stars) should not change, so the significances should scatter like
  a standard normal: mean near 0, spread near 1. A spread well above 1 means
  our error bars are too small and our "5 sigma" is not really 5 sigma.

* Injection-recovery: we add an artificial star of known brightness to the
  later epoch and ask whether the comparison finds it. These injected sources
  are SIMULATED; we label them as such everywhere they appear and never mix
  them with the real measurements.
"""

from __future__ import annotations

import numpy as np

from hipparchus.compare import DETECTION_SIGMA, SKY_OUTER, photometry
from hipparchus.quality import APERTURE_PX

# Pixel scale of SPHEREx, used only to turn the header PSF width into pixels.
PIXEL_ARCSEC = 6.15
# Fallback PSF width (pixels) when the header has none.
DEFAULT_FWHM_PX = 1.5
# Distance between test apertures, so neighbouring apertures barely overlap.
GRID_STEP_PX = 5


def test_positions(shape, x, y, min_sep=APERTURE_PX + SKY_OUTER, edge=APERTURE_PX + 1):
    """A regular grid of aperture centres, away from the target and the edges."""
    ny, nx = shape
    out = []
    for yy in np.arange(edge, ny - edge, GRID_STEP_PX):
        for xx in np.arange(edge, nx - edge, GRID_STEP_PX):
            if (xx - x) ** 2 + (yy - y) ** 2 >= min_sep ** 2:
                out.append((float(xx), float(yy)))
    return out


def _pair_sig(arr, x, y, extra=None):
    pa = photometry(arr["a"], arr["a_var"], arr["a_bad"], x, y)
    b = arr["b"] if extra is None else arr["b"] + extra
    pb = photometry(b, arr["b_var"], arr["bad"], x, y)
    err = float(np.hypot(pa["flux_err"], pb["flux_err"]))
    return (pb["flux"] - pa["flux"]) / err if err > 0 else float("nan"), err


def _clean(arr, x, y, r=APERTURE_PX + 1):
    """True when no masked or missing pixel touches the test aperture."""
    ny, nx = arr["bad"].shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    near = (xx - x) ** 2 + (yy - y) ** 2 <= r ** 2
    return not (arr["bad"][near].any() or arr["a_bad"][near].any()
                or not np.isfinite(arr["b"][near]).all())


def null_test(pair: dict, x: float, y: float) -> list[float]:
    """Significances of 'change' at blank positions of one compared pair."""
    arr = pair["_arrays"]
    return [s for px, py in test_positions(arr["a"].shape, x, y) if _clean(arr, px, py)
            for s, _ in [_pair_sig(arr, px, py)] if np.isfinite(s)]


def null_summary(z: list[float]) -> dict:
    z = np.asarray(z, float)
    if z.size == 0:
        return {"n": 0}
    # The spread from the middle 68% is less sensitive to the odd real variable
    # star than the plain standard deviation, so we report both.
    q16, q84 = np.percentile(z, [16, 84])
    return {"n": int(z.size), "mean": float(z.mean()), "std": float(z.std()),
            "robust_std": float((q84 - q16) / 2),
            "frac_abs_over_3": float(np.mean(np.abs(z) > 3)),
            "frac_abs_over_5": float(np.mean(np.abs(z) > DETECTION_SIGMA))}


def gaussian_star(shape, x, y, fwhm_px, total):
    s = fwhm_px / 2.3548
    ny, nx = shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    return total * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * s * s)) / (2 * np.pi * s * s)


def injection_recovery(pair: dict, x: float, y: float, fwhm_px: float,
                       snr_levels=(1, 2, 3, 4, 5, 6, 7, 8, 10, 15)) -> list[dict]:
    """SIMULATED: add a star of known S/N to epoch b at blank positions.

    We define the injected S/N as the flux that falls inside our aperture
    divided by the noise of the aperture difference, so a perfect method
    detects it half of the time at S/N = 5. We don't add the photon noise of
    the injected star itself, which makes bright injections slightly easier.
    """
    arr = pair["_arrays"]
    shape = arr["a"].shape
    out = []
    for px, py in test_positions(shape, x, y):
        if not _clean(arr, px, py):
            continue
        base, err = _pair_sig(arr, px, py)
        if not np.isfinite(base):
            continue
        unit = gaussian_star(shape, px, py, fwhm_px, 1.0)
        yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
        in_ap = unit[(xx - px) ** 2 + (yy - py) ** 2 <= APERTURE_PX ** 2].sum()
        for k in snr_levels:
            total = k * err / in_ap
            sig, _ = _pair_sig(arr, px, py, gaussian_star(shape, px, py, fwhm_px, total))
            out.append({"snr_injected": k, "x": px, "y": py, "significance": sig,
                        "recovered": bool(sig >= DETECTION_SIGMA), "simulated": True})
    return out


def recovery_curve(trials: list[dict]) -> list[dict]:
    levels = sorted({t["snr_injected"] for t in trials})
    return [{"snr_injected": k,
             "n": sum(t["snr_injected"] == k for t in trials),
             "recovered_fraction": float(np.mean([t["recovered"] for t in trials if t["snr_injected"] == k]))}
            for k in levels]


def fwhm_px(epoch) -> float:
    f = epoch.psf_fwhm_arcsec
    return f / PIXEL_ARCSEC if np.isfinite(f) and f > 0 else DEFAULT_FWHM_PX
