"""Calibrated wavelength and bandwidth at a target, from the SPHEREx Spectral WCS product.

The WCS-WAVE lookup table inside every spectral image (and cutout) is a 9x9
grid of control points with bilinear interpolation. IRSA describes it as meant
for visualization and asks science analyses to use the CWAVE and CBAND images
of the Spectral WCS calibration product instead: one 2040x2040 map per detector
with the central wavelength and the bandwidth of every pixel, in microns.

This module reads those maps and evaluates them at the target. A cutout pixel
is mapped to the full-detector ("parent") pixel with the cutout's alternate
WCS "A" (0-based active pixel coordinates): parent = cutout(0-based) + 1 - CRPIX1A.

If the calibration file is not available, the cutout's WCS-WAVE table is read
instead (bilinear between control points, as the IRSA user guide describes)
and the result says so ("source": "wcs-wave fallback").
"""

from __future__ import annotations

import hashlib
import warnings
from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning

from hipparchus.archive import DATA_DIR

CAL_DIR = DATA_DIR / "cache" / "calibration"

# The Spectral WCS product behind DR1 and QR3. IRSA serves the same version in
# both releases (identical MD5 checksums on the IRSA S3 mirror, 2026-11-15), so
# one file per detector covers every epoch we use.
VERSION = "cal-swcs-v5-2026-191"
URL = ("https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/spectral_wcs/"
       "{version}/{det}/spectral_wcs_D{det}_spx_{version}.fits")

# SHA-256 of the files we downloaded and checked. A detector without an entry
# is still read, but its result is marked as unverified.
# D2-D5 added 2026-11-16; their MD5 equals the S3 ETag listed in wavecal_check.json.
SHA256 = {
    1: "44fb48b236e25a99d42c8986da0064cc58359527e1fc76e182eda52371a1ae23",
    2: "0eb4e27f351e6161e21372818f9e811480a7ab8bab9295722f180791e151a463",
    3: "51750c8f948a30541d391e54930279aa067c62c398a7cc2679e592bc6044427a",
    4: "dbdcb8addb4ffe817f31786c8cb359b1f47df3528173e9d4602b94c84f7d7c1a",
    5: "3361428284bddad1dcdce42081ebfbd225acb0b19f6caa94fba3e133bbabfc1c",
    6: "19195d253892883586aa2183cb66238b32f6032ade62d490b36b85b0dd18f212",
}

NPIX = 2040


def cal_path(detector: int, version: str = VERSION) -> Path:
    return CAL_DIR / f"spectral_wcs_D{int(detector)}_spx_{version}.fits"


def download(detector: int, version: str = VERSION, timeout: float = 600.0) -> Path:
    """Fetch the Spectral WCS file of one detector (about 33 MB) into CAL_DIR."""
    path = cal_path(detector, version)
    if path.exists():
        return path
    CAL_DIR.mkdir(parents=True, exist_ok=True)
    url = URL.format(version=version, det=int(detector))
    with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as r:
        r.raise_for_status()
        data = b"".join(r.iter_bytes())
    if not data.startswith(b"SIMPLE"):
        raise ValueError(f"{url} did not return a FITS file")
    want = SHA256.get(int(detector))
    if want and hashlib.sha256(data).hexdigest() != want:
        raise ValueError(f"{url}: SHA-256 does not match the recorded value")
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.rename(path)
    return path


@lru_cache(maxsize=6)
def load(detector: int, version: str = VERSION, path: str | None = None) -> dict | None:
    """CWAVE/CBAND maps and provenance for one detector, or None if the file is absent or broken."""
    p = Path(path) if path else cal_path(detector, version)
    if not p.exists():
        return None
    raw = p.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    try:
        with fits.open(p) as h:
            cw = np.asarray(h["CWAVE"].data, float)
            cb = np.asarray(h["CBAND"].data, float)
            ph = h[0].header
            det = int(str(h["CWAVE"].header.get("DETECTOR", detector)).strip())
            info = {
                "detcoord": str(ph.get("DETCOORD", "")).strip(),
                "history": [str(v) for v in ph.get("HISTORY", [])],
                "comment": [str(v) for v in ph.get("COMMENT", [])],
                "wl_err_max_um": ph.get("WLERRMAX"), "bw_err_max_um": ph.get("BWERRMAX"),
                "wl_err_p99_um": ph.get("WLERRP99"), "bw_err_p99_um": ph.get("BWERRP99"),
            }
    except (OSError, KeyError, ValueError, TypeError):
        return None
    # We refuse a map of the wrong shape or for another detector rather than
    # index it silently: a swapped file would give plausible but wrong numbers.
    if cw.shape != (NPIX, NPIX) or cb.shape != (NPIX, NPIX) or det != int(detector):
        return None
    want = SHA256.get(int(detector))
    return {"cwave": cw, "cband": cb, "detector": det, "path": str(p), "sha256": sha,
            "verified": (sha == want) if want else None, "version": version, **info}


def parent_pixel(image_header, x: float, y: float) -> tuple[float, float]:
    """Full-detector pixel (0-based) of cutout pixel (x, y), 0-based."""
    h = image_header
    # The "A" WCS is a pure shift (CDELT = 1, CRVAL = 0). We check that instead
    # of assuming it, because a scaled or offset "A" would need the full formula.
    if float(h.get("CDELT1A", 1)) != 1 or float(h.get("CDELT2A", 1)) != 1:
        raise ValueError("alternate WCS A is not a unit pixel shift")
    return (x + 1 - float(h["CRPIX1A"]) + float(h.get("CRVAL1A", 0)),
            y + 1 - float(h["CRPIX2A"]) + float(h.get("CRVAL2A", 0)))


def bilinear(img: np.ndarray, x: float, y: float) -> float:
    """Value of img at (x, y), 0-based pixel centres, bilinear between the 4 neighbours."""
    ny, nx = img.shape
    if not (0 <= x <= nx - 1 and 0 <= y <= ny - 1):
        return float("nan")
    x0, y0 = min(int(np.floor(x)), nx - 2), min(int(np.floor(y)), ny - 2)
    fx, fy = x - x0, y - y0
    q = img[y0:y0 + 2, x0:x0 + 2]
    return float(q[0, 0] * (1 - fx) * (1 - fy) + q[0, 1] * fx * (1 - fy)
                 + q[1, 0] * (1 - fx) * fy + q[1, 1] * fx * fy)


def wcs_wave_astropy(hdul: fits.HDUList, x: float, y: float) -> tuple[float, float]:
    """WCS-WAVE value exactly as quality.py reads it: astropy WCS(key="W").

    Astropy also applies the celestial SIP polynomial (A_*/B_* keywords carry
    no alternate letter) to this lookup, so the table is read at a distorted
    pixel position. We keep this function only to reproduce the production value.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FITSFixedWarning)
        w = WCS(hdul["IMAGE"].header, fobj=hdul, key="W")
        lam, dlam = w.pixel_to_world_values(x, y)
    return float(lam), float(dlam)


def wcs_wave_table(hdul: fits.HDUList, x: float, y: float) -> tuple[float, float]:
    """WCS-WAVE value by the documented recipe: bilinear between the 4 nearest control points.

    The table coordinate is (pixel + 1 - CRPIXjW) * CDELTjW + CRVALjW (FITS -TAB,
    raw 1-based parent coordinates). VALUES is stored as (2, nX, nY) in FITS
    order, i.e. [iy, ix, k] in numpy; PV1_3W / PV2_3W say which k is which.
    """
    h = hdul["IMAGE"].header
    t = hdul["WCS-WAVE"].data
    gx = np.asarray(t["X"][0], float)
    gy = np.asarray(t["Y"][0], float)
    v = np.asarray(t["VALUES"][0], float)
    u = (x + 1 - float(h["CRPIX1W"])) * float(h.get("CDELT1W", 1)) + float(h.get("CRVAL1W", 1))
    w = (y + 1 - float(h["CRPIX2W"])) * float(h.get("CDELT2W", 1)) + float(h.get("CRVAL2W", 1))
    if not (gx[0] <= u <= gx[-1] and gy[0] <= w <= gy[-1]):
        return float("nan"), float("nan")
    i = min(int(np.searchsorted(gx, u, side="right")) - 1, len(gx) - 2)
    j = min(int(np.searchsorted(gy, w, side="right")) - 1, len(gy) - 2)
    fx = (u - gx[i]) / (gx[i + 1] - gx[i])
    fy = (w - gy[j]) / (gy[j + 1] - gy[j])
    q = v[j:j + 2, i:i + 2, :]
    val = (q[0, 0] * (1 - fx) * (1 - fy) + q[0, 1] * fx * (1 - fy)
           + q[1, 0] * (1 - fx) * fy + q[1, 1] * fx * fy)
    k_lam, k_band = int(h.get("PV1_3W", 1)) - 1, int(h.get("PV2_3W", 2)) - 1
    return float(val[k_lam]), float(val[k_band])


def at_target(path_or_hdul, x: float, y: float, cal: dict | None = None) -> dict:
    """Calibrated centre wavelength and bandwidth at cutout pixel (x, y), 0-based.

    Falls back to the cutout's WCS-WAVE table when the calibration is missing,
    belongs to another detector, or the parent pixel is off the detector. The
    production value (astropy, see wcs_wave_astropy) is returned alongside.
    """
    own = not isinstance(path_or_hdul, fits.HDUList)
    h = fits.open(path_or_hdul) if own else path_or_hdul
    try:
        hdr = h["IMAGE"].header
        det = int(hdr.get("DETECTOR", 0))
        lam_a, dlam_a = wcs_wave_astropy(h, x, y)
        lam_w, dlam_w = wcs_wave_table(h, x, y)
        # Our fallback is the table read the documented way; if even that fails
        # (target outside the control grid), we fall back to the production value.
        if not np.isfinite(lam_w):
            lam_w, dlam_w = lam_a, dlam_a
        out = {"detector": det, "wcs_wave_astropy_um": lam_a, "wcs_band_astropy_um": dlam_a,
               "wcs_wave_table_um": lam_w, "wcs_band_table_um": dlam_w}
        try:
            px, py = parent_pixel(hdr, x, y)
        except (KeyError, ValueError) as e:
            return out | {"source": "wcs-wave fallback", "wavelength_um": lam_w, "bandwidth_um": dlam_w,
                          "note": f"no usable parent-pixel mapping ({e})"}
        out["parent_xy"] = [px, py]
        cal = cal if cal is not None else load(det)
        if cal is None or cal["detector"] != det:
            return out | {"source": "wcs-wave fallback", "wavelength_um": lam_w, "bandwidth_um": dlam_w,
                          "note": f"Spectral WCS calibration for D{det} not available"}
        lam, dlam = bilinear(cal["cwave"], px, py), bilinear(cal["cband"], px, py)
        if not (np.isfinite(lam) and np.isfinite(dlam) and dlam > 0):
            return out | {"source": "wcs-wave fallback", "wavelength_um": lam_w, "bandwidth_um": dlam_w,
                          "note": "parent pixel outside the calibration map"}
        return out | {"source": "cwave/cband", "wavelength_um": lam, "bandwidth_um": dlam,
                      "cal_sha256": cal["sha256"], "cal_verified": cal["verified"], "cal_version": cal["version"]}
    finally:
        if own:
            h.close()
