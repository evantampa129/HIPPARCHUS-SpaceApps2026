"""Wavelength sources on REAL SPHEREx cutouts (fixtures); calibration maps are SIMULATED or absent."""

import warnings
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning

from hipparchus import quality, spectral_cal as S

FX = Path(__file__).parent / "fixtures"
BARNARD = (FX / "barnard_d6.fits", "2025W33_2C_0321_1", 269.4463, 4.7667)
RW_AUR = (FX / "rwaur_d1_2025.fits", "2025W36_1A_0233_3", 76.956, 30.401)


def _wcs_w(h, sip=True):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FITSFixedWarning)
        w = WCS(h["IMAGE"].header, fobj=h, key="W")
    if not sip:
        w.sip = None
    return w


@pytest.mark.parametrize("fx", [BARNARD, RW_AUR])
def test_legacy_default_is_unchanged_astropy_read(fx):
    path, oid, ra, dec = fx
    ep = quality.load(str(path), oid, ra, dec)
    assert quality.DEFAULT_WAVELENGTH_SOURCE == "wcs" and ep.wavelength_source == "wcs"
    with fits.open(path) as h:
        lam, dlam = _wcs_w(h).pixel_to_world_values(ep.x, ep.y)
    # Bit for bit: the published numbers depend on it.
    assert ep.wavelength_um == float(lam) and ep.bandwidth_um == float(dlam)


@pytest.mark.parametrize("fx", [BARNARD, RW_AUR])
def test_sip_is_the_whole_legacy_offset(fx):
    path = fx[0]
    with fits.open(path) as h:
        hd = h["IMAGE"].header
        legacy, nosip = _wcs_w(h), _wcs_w(h, sip=False)
        # astropy attaches the celestial SIP to the W lookup, around the W reference pixel.
        assert hd["CTYPE1W"] == "WAVE-TAB" and hd["CTYPE1"].endswith("-SIP")
        assert legacy.sip is not None and tuple(legacy.sip.crpix) == (hd["CRPIX1W"], hd["CRPIX2W"])
        ny, nx = h["IMAGE"].data.shape
        for x, y in [(0.0, 0.0), (nx - 1.0, 0.0), ((nx - 1) / 2, (ny - 1) / 2), (3.3, ny - 1.0)]:
            # Without SIP astropy's -TAB read equals the documented bilinear recipe.
            assert np.allclose(nosip.pixel_to_world_values(x, y), S.wcs_wave_table(h, x, y), rtol=0, atol=1e-12)
            # With SIP it equals that recipe at p + SIP(p + 1 - CRPIXW).
            u, v = x + 1 - hd["CRPIX1W"], y + 1 - hd["CRPIX2W"]
            a, b = legacy.sip.a, legacy.sip.b
            du = sum(a[i, j] * u ** i * v ** j for i in range(a.shape[0]) for j in range(a.shape[1]))
            dv = sum(b[i, j] * u ** i * v ** j for i in range(b.shape[0]) for j in range(b.shape[1]))
            assert np.allclose(legacy.pixel_to_world_values(x, y), S.wcs_wave_table(h, x + du, y + dv),
                               rtol=0, atol=1e-12)
    # On Barnard's D6 cutout the shift is large enough to matter (several nm).
    if path == BARNARD[0]:
        ep0 = quality.load(*map(str, BARNARD[:2]), *BARNARD[2:])
        ep1 = quality.load(*map(str, BARNARD[:2]), *BARNARD[2:], wavelength_source="wcs_nosip")
        assert abs(ep1.wavelength_um - ep0.wavelength_um) > 1e-3
        assert ep1.wavelength_source == "wcs_nosip"


def test_cwave_reads_the_map_at_the_parent_pixel(monkeypatch):
    path, oid, ra, dec = BARNARD
    yy, xx = np.mgrid[0:S.NPIX, 0:S.NPIX].astype(float)
    cal = {"cwave": 4.4 + 1e-4 * yy + 1e-7 * xx, "cband": 0.035 + 1e-6 * xx, "detector": 6,
           "sha256": "sim", "verified": None, "version": "sim"}            # SIMULATED map
    monkeypatch.setattr(S, "load", lambda det, *a, **k: cal if det == 6 else None)
    ep = quality.load(str(path), oid, ra, dec, wavelength_source="cwave")
    with fits.open(path) as h:
        px, py = S.parent_pixel(h["IMAGE"].header, ep.x, ep.y)
    assert ep.wavelength_source == "cwave"
    assert ep.wavelength_um == pytest.approx(4.4 + 1e-4 * py + 1e-7 * px, abs=1e-12)
    assert ep.bandwidth_um == pytest.approx(0.035 + 1e-6 * px, abs=1e-12)
    assert not any(i.code == "wavelength_fallback" for i in ep.issues)


def test_cwave_without_map_falls_back_to_nosip_and_warns(monkeypatch):
    path, oid, ra, dec = RW_AUR
    monkeypatch.setattr(S, "load", lambda *a, **k: None)
    ep = quality.load(str(path), oid, ra, dec, wavelength_source="cwave")
    ref = quality.load(str(path), oid, ra, dec, wavelength_source="wcs_nosip")
    assert ep.wavelength_source == "wcs_nosip"
    assert ep.wavelength_um == pytest.approx(ref.wavelength_um, abs=1e-12)
    fb = [i for i in ep.issues if i.code == "wavelength_fallback"]
    assert len(fb) == 1 and fb[0].severity == "warn" and ep.usable == ref.usable


def test_unknown_source_is_refused():
    path, oid, ra, dec = RW_AUR
    with pytest.raises(ValueError):
        quality.load(str(path), oid, ra, dec, wavelength_source="cwav")
