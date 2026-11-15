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


def _mover_plus_clumps(rng):
    """SIMULATED field: one steady mover, and three static clumps that line up.

    The clumps sit 120" apart at one-day intervals, so together they look like
    a 5"/h track; each is seen only in a ~1 h burst, too short for flag_static.
    The mover is placed far away so the two cannot share detections.
    """
    t, xi, eta = [], [], []
    for k, t0 in enumerate((0.0, 1.0, 2.0)):          # clumps
        for dt in (0.0, 0.02, 0.04):
            t.append(60000 + t0 + dt)
            xi.append(120.0 * k + rng.normal(0, 0.3))
            eta.append(2.0 * k * k + rng.normal(0, 0.3))
    for tm in 60000 + np.linspace(0.3, 2.7, 9):         # mover, 4 "/h east, 1.5 "/h north
        h = (tm - 60000) * 24
        t.append(tm)
        xi.append(20000.0 + 4.0 * h + rng.normal(0, 0.3))
        eta.append(-1.5 * h + rng.normal(0, 0.3))
    t, xi, eta = np.array(t), np.array(xi), np.array(eta)
    return t, xi, eta, np.full(len(t), 0.5)


LINK_KW = dict(v_min=1.5, v_max=120.0, tol_arcsec=12.0, min_visits=3, order=2)


def test_link_without_vetting_is_unchanged_and_finds_the_clump_track():
    # SIMULATED. With vet=None (the default, as in motion_check.json) the clumps
    # are linked into a second, spurious track, as happened on Kleopatra's field.
    t, xi, eta, err = _mover_plus_clumps(np.random.default_rng(11))
    tracks = M.link(t, xi, eta, err, **LINK_KW)
    assert len(tracks) == 2
    assert sorted(len(tr.members) for tr in tracks) == [9, 9]


def test_link_with_vetting_keeps_only_the_mover():
    # SIMULATED. Same field with vetting on: the clump track is rejected and
    # reported, the mover's track is identical to the unvetted one.
    t, xi, eta, err = _mover_plus_clumps(np.random.default_rng(11))
    plain = M.link(t, xi, eta, err, **LINK_KW)
    rejected = []
    vetted = M.link(t, xi, eta, err, vet={"radius_arcsec": 6.0, "min_dt_hours": 4.0}, rejected=rejected, **LINK_KW)
    assert len(vetted) == 1
    mover = vetted[0]
    assert np.all(xi[mover.members] > 10000)
    vx, vy, _, _ = mover.fit.rate_arcsec_per_hour
    assert abs(vx - 4.0) < 0.1 and abs(vy + 1.5) < 0.1
    same = [tr for tr in plain if np.array_equal(tr.members, mover.members)]
    assert same and np.allclose(same[0].fit.coef_xi, mover.fit.coef_xi)
    assert rejected and all(r["check"]["n_position_groups"] <= 3 for r in rejected)
    assert all(np.all(xi[r["members"]] < 1000) for r in rejected)


def test_degenerate_track_keeps_fast_mover_in_three_short_visits():
    # SIMULATED Eros-like case: 72 "/h, three visits of ~7 min each, so each
    # visit is one tight position group. Without errors and rate the geometry
    # alone calls it degenerate; with them, the motion inside each visit shows.
    rng = np.random.default_rng(3)
    t = 60000 + np.concatenate([v + np.linspace(0, 0.005, 5) for v in (0.0, 0.3, 0.68)])
    h = (t - t[0]) * 24
    xi, eta = 56.5 * h + rng.normal(0, 0.2, t.size), 45.3 * h + rng.normal(0, 0.2, t.size)
    err = np.full(t.size, 0.2)
    assert M.degenerate_track(t, xi, eta, 2, 6.0, 4.0) is not None
    assert M.degenerate_track(t, xi, eta, 2, 6.0, 4.0, err=err, rate=(56.5, 45.3)) is None


def test_degenerate_track_static_clumps_stay_degenerate_with_rate():
    # SIMULATED: the static clumps of the Kleopatra-like case do not move inside
    # their bursts, so supplying the track's slow rate must not rescue them.
    t = 60000 + np.array([0.0, 0.003, 0.006, 1.0, 1.003, 2.0, 2.003])
    xi = np.array([0.0, 0.1, -0.1, 120.0, 120.2, 240.0, 239.9])
    eta = np.array([0.0, -0.1, 0.1, 2.0, 2.1, 8.0, 7.9])
    d = M.degenerate_track(t, xi, eta, 2, 6.0, 4.0, err=np.full(7, 0.5), rate=(5.0, 0.2))
    assert d is not None and d["n_position_groups"] == 3
