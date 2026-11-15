"""Spectral calibration lookup on SIMULATED files (offline): every map and cutout here is synthetic."""

import numpy as np
import pytest
from astropy.io import fits

from hipparchus import psf_photometry as P
from hipparchus import spectral_cal as S

CRPIX1A, CRPIX2A = -451.0, -1510.0   # cutout pixel 0 -> parent pixel 452 (x), 1511 (y)


def _maps():
    # SIMULATED: wavelength rises along y, bandwidth along x, so a swapped axis
    # or an off-by-one in the parent mapping gives a different number.
    yy, xx = np.mgrid[0:S.NPIX, 0:S.NPIX].astype(float)
    return 1.0 + 1e-4 * yy + 1e-6 * xx, 0.02 + 1e-6 * xx


def _cutout(det=6, sip=False):
    """SIMULATED 29x29 cutout with the A and W alternate WCS of a real SPHEREx cutout."""
    img = fits.ImageHDU(np.zeros((29, 29), np.float32), name="IMAGE")
    h = img.header
    h["DETECTOR"] = det
    h["CRPIX1A"], h["CRPIX2A"], h["CRVAL1A"], h["CRVAL2A"] = CRPIX1A, CRPIX2A, 0.0, 0.0
    h["CDELT1A"] = h["CDELT2A"] = 1.0
    h["WCSAXESW"] = 2
    for j in (1, 2):
        h[f"CTYPE{j}W"] = "WAVE-TAB"
        h[f"CUNIT{j}W"] = "um"
        h[f"CDELT{j}W"] = 1
        h[f"CRVAL{j}W"] = 1
        h[f"PS{j}_0W"] = "WCS-WAVE"
        h[f"PS{j}_1W"] = "VALUES"
        h[f"PV{j}_3W"] = j
    h["CRPIX1W"], h["CRPIX2W"] = CRPIX1A, CRPIX2A
    h["PS1_2W"], h["PS2_2W"] = "X", "Y"
    if sip:
        # A celestial TAN-SIP solution with a quadratic term, as in the real files. Astropy
        # evaluates it around the W reference pixel, so it must stay small to keep
        # the distorted position on the 1..2040 table.
        h["CTYPE1"], h["CTYPE2"] = "RA---TAN-SIP", "DEC--TAN-SIP"
        h["CRPIX1"], h["CRPIX2"], h["CRVAL1"], h["CRVAL2"] = 15.0, 15.0, 100.0, 10.0
        h["CDELT1"], h["CDELT2"] = -0.0017, 0.0017
        h["A_ORDER"], h["B_ORDER"] = 2, 2
        h["A_2_0"], h["B_0_2"] = 1e-5, 1e-5
    grid = np.array([1, 256, 511, 766, 1021, 1275, 1530, 1785, 2040], np.int32)
    cw, cb = _maps()
    gi = grid - 1
    vals = np.stack([cw[np.ix_(gi, gi)], cb[np.ix_(gi, gi)]], axis=-1).astype(np.float32)   # [iy, ix, k]
    t = fits.BinTableHDU.from_columns([
        fits.Column("X", "9J", array=grid[None]), fits.Column("Y", "9J", array=grid[None]),
        fits.Column("VALUES", "162E", dim="(2,9,9)", array=vals[None])], name="WCS-WAVE")
    return fits.HDUList([fits.PrimaryHDU(), img, t])


def _cal(det=6):
    cw, cb = _maps()
    return {"cwave": cw, "cband": cb, "detector": det, "sha256": "x", "verified": None, "version": "sim"}


def test_parent_pixel_follows_crpix_a():
    hdr = _cutout()["IMAGE"].header
    assert S.parent_pixel(hdr, 0.0, 0.0) == (452.0, 1511.0)
    assert S.parent_pixel(hdr, 13.5, 2.25) == (465.5, 1513.25)
    hdr["CDELT1A"] = 2.0
    with pytest.raises(ValueError):
        S.parent_pixel(hdr, 0.0, 0.0)


def test_bilinear_is_exact_on_a_plane_and_nan_outside():
    cw, _ = _maps()
    assert S.bilinear(cw, 100.25, 7.5) == pytest.approx(1.0 + 1e-4 * 7.5 + 1e-6 * 100.25, abs=1e-12)
    assert S.bilinear(cw, 2039.0, 2039.0) == pytest.approx(cw[2039, 2039])
    assert np.isnan(S.bilinear(cw, -0.5, 10.0)) and np.isnan(S.bilinear(cw, 10.0, 2039.5))


def test_calibrated_value_at_target():
    r = S.at_target(_cutout(), 14.0, 14.0, cal=_cal())
    px, py = 466.0, 1525.0
    assert r["source"] == "cwave/cband" and r["parent_xy"] == [px, py]
    assert r["wavelength_um"] == pytest.approx(1.0 + 1e-4 * py + 1e-6 * px, abs=1e-12)
    assert r["bandwidth_um"] == pytest.approx(0.02 + 1e-6 * px, abs=1e-12)
    # The maps are planes, so the 9x9 table interpolates them exactly as well
    # (up to float32 storage): table and calibrated value agree.
    assert r["wcs_wave_table_um"] == pytest.approx(r["wavelength_um"], abs=1e-6)
    assert r["wcs_band_table_um"] == pytest.approx(r["bandwidth_um"], abs=1e-6)


def test_table_matches_astropy_without_sip_and_differs_with_sip():
    h = _cutout()
    lam_a, _ = S.wcs_wave_astropy(h, 3.0, 20.0)
    lam_t, _ = S.wcs_wave_table(h, 3.0, 20.0)
    assert lam_a == pytest.approx(lam_t, abs=1e-6)
    # With SIP keywords present astropy distorts the pixel before the lookup.
    hs = _cutout(sip=True)
    lam_as, _ = S.wcs_wave_astropy(hs, 3.0, 20.0)
    lam_ts, _ = S.wcs_wave_table(hs, 3.0, 20.0)
    assert lam_ts == pytest.approx(lam_t, abs=1e-9)
    assert abs(lam_as - lam_ts) > 1e-5


def test_missing_or_wrong_calibration_falls_back_and_says_so(tmp_path):
    h = _cutout()
    r = S.at_target(h, 14.0, 14.0, cal=_cal(det=1))       # map of another detector
    assert r["source"] == "wcs-wave fallback" and "D6" in r["note"]
    assert r["wavelength_um"] == r["wcs_wave_table_um"]
    assert S.load(6, path=str(tmp_path / "absent.fits")) is None
    del h["IMAGE"].header["CRPIX1A"]
    r = S.at_target(h, 14.0, 14.0, cal=_cal())
    assert r["source"] == "wcs-wave fallback" and "parent-pixel" in r["note"]


def test_load_reads_maps_and_refuses_wrong_shape(tmp_path):
    cw, cb = _maps()
    p = tmp_path / "sim_D6.fits"
    hw, hb = fits.ImageHDU(cw.astype(np.float32), name="CWAVE"), fits.ImageHDU(cb.astype(np.float32), name="CBAND")
    hw.header["DETECTOR"] = hb.header["DETECTOR"] = "6"
    ph = fits.PrimaryHDU()
    ph.header["DETCOORD"] = "sky"
    fits.HDUList([ph, hw, hb]).writeto(p)
    c = S.load(6, path=str(p))
    assert c["detector"] == 6 and c["cwave"].shape == (S.NPIX, S.NPIX) and c["detcoord"] == "sky"
    assert c["verified"] is False          # D6 has a recorded hash; a simulated file must not match it
    assert S.load(5, path=str(p)) is None  # header says D6, so we refuse it for D5
    small = tmp_path / "small.fits"
    fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(np.ones((10, 10)), name="CWAVE"),
                  fits.ImageHDU(np.ones((10, 10)), name="CBAND")]).writeto(small)
    assert S.load(6, path=str(small)) is None


def _epsf_hdul(nx, ny):
    """SIMULATED EPSF table with a uniform nx x ny zone tiling of the 2040x2040 detector."""
    wx, wy = S.NPIX / nx, S.NPIX / ny
    bx, by = np.meshgrid(np.arange(nx), np.arange(ny))      # x fast, then y
    xc, yc = (bx.ravel() + 0.5) * wx - 0.5, (by.ravel() + 0.5) * wy - 0.5
    n = nx * ny
    psf = np.full((n, 33 * 33), 1.0 / (33 * 33))
    t = fits.BinTableHDU.from_columns([
        fits.Column("BINX", "J", array=bx.ravel()), fits.Column("BINY", "J", array=by.ravel()),
        fits.Column("XCENTER", "E", array=xc), fits.Column("YCENTER", "E", array=yc),
        fits.Column("XWIDTH", "E", array=np.full(n, wx)), fits.Column("YWIDTH", "E", array=np.full(n, wy)),
        fits.Column("EPSF", "1089D", array=psf)], name="EPSF")
    t.header["OVSMPX"] = t.header["OVSMPY"] = 5
    img = fits.ImageHDU(np.zeros((29, 29)), name="IMAGE")
    img.header["CRPIX1A"], img.header["CRPIX2A"] = 1.0, 1.0   # cutout pixel = parent pixel
    return fits.HDUList([fits.PrimaryHDU(), img, t])


@pytest.mark.parametrize("nx,ny", [(21, 21), (11, 41)])
def test_load_epsf_picks_the_containing_zone_for_both_layouts(nx, ny):
    h = _epsf_hdul(nx, ny)
    t = h["EPSF"].data
    rng = np.random.default_rng(1)
    for x, y in rng.uniform(0, S.NPIX - 1, size=(300, 2)):
        e = P.load_epsf(h, x, y)
        i = e["zone"]
        assert t["BINX"][i] == int((x + 0.5) // (S.NPIX / nx)) and t["BINY"][i] == int((y + 0.5) // (S.NPIX / ny))
