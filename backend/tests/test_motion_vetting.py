"""Track-vetting helpers on SIMULATED data (offline): every source here is synthetic."""

import numpy as np
from astropy.wcs import WCS

from hipparchus import motion as M

SCALE = 6.15


def _wcs(n=40):
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [200.0, -8.0]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-SCALE / 3600, SCALE / 3600]
    return w


def test_position_groups_friends_of_friends():
    xi = np.array([0.0, 1.0, 2.5, 50.0, 51.0, -80.0])
    eta = np.zeros(6)
    lab = M.position_groups(xi, eta, 2.0)
    assert lab[0] == lab[1] == lab[2] and lab[3] == lab[4] and len(set(lab.tolist())) == 3


def test_degenerate_track_three_static_clumps():
    # SIMULATED: three static positions, each seen in a burst shorter than 4 h.
    # A quadratic passes through any three points, so this must be flagged.
    t = 60000 + np.array([0.0, 0.47, 0.61, 2.37, 2.44, 2.441])
    xi = np.array([-110.6, -125.1, -123.6, -184.0, -182.9, -183.5])
    eta = np.array([173.9, 169.4, 169.5, 211.0, 212.9, 212.2])
    d = M.degenerate_track(t, xi, eta, order=2, radius_arcsec=6.0, min_dt_hours=4.0)
    assert d is not None and d["n_position_groups"] == 3


def test_degenerate_track_passes_real_mover():
    # SIMULATED steady mover at 5 arcsec/h over 3 days: one group per exposure.
    t = 60000 + np.linspace(0, 3, 9)
    h = (t - t[0]) * 24
    assert M.degenerate_track(t, 5 * h, -2 * h, order=2, radius_arcsec=6.0, min_dt_hours=4.0) is None


def test_forced_snr_sees_static_source():
    rng = np.random.default_rng(5)
    w = _wcs()
    img = rng.normal(0, 1, (40, 40))
    ra, dec = (float(v) for v in w.pixel_to_world_values(20.0, 20.0))
    img = M.inject_point_source(img, w, ra, dec, 8.0, 9.0)
    sig = 9.0 / SCALE * M.FWHM_TO_SIGMA
    s_on, _ = M.forced_snr(img, np.ones_like(img), np.zeros(img.shape, bool), 20.0, 20.0, sig)
    s_off, _ = M.forced_snr(img, np.ones_like(img), np.zeros(img.shape, bool), 8.0, 30.0, sig)
    assert s_on > 5 and abs(s_off) < 4
    assert M.forced_snr(img, np.ones_like(img), np.zeros(img.shape, bool), 99.0, 5.0, sig) is None


def test_peak_sharpness_separates_cosmic_ray_from_psf():
    rng = np.random.default_rng(6)
    w = _wcs()
    sig = 9.0 / SCALE * M.FWHM_TO_SIGMA
    img = rng.normal(0, 1, (40, 40))
    ra, dec = (float(v) for v in w.pixel_to_world_values(20.0, 20.0))
    star = M.inject_point_source(img, w, ra, dec, 40.0, 9.0)
    r_star, expected = M.peak_sharpness(star, np.ones_like(img), 20.0, 20.0, sig)
    hit = img.copy()
    hit[20, 20] += 40.0        # SIMULATED single-pixel event
    r_hit, _ = M.peak_sharpness(hit, np.ones_like(img), 20.0, 20.0, sig)
    assert abs(r_star - expected) < 1.5 and r_hit > 3 * expected
