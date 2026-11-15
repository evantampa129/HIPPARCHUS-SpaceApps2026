"""Moving-source detection and linking on SIMULATED data (offline): every source here is synthetic."""

import numpy as np
from astropy.wcs import WCS

from hipparchus import motion as M

SCALE = 6.15  # arcsec/pixel, as SPHEREx


def _wcs(n=80, ra=200.0, dec=-8.0):
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-SCALE / 3600, SCALE / 3600]
    return w


def _sequence(rng, mover=(8.0, -5.0), accel=0.0, amp=12.0, n_stars=25, times=None, with_mover=True):
    """SIMULATED: static stars + one mover, unit Gaussian noise, unit variance."""
    w = _wcs()
    if times is None:
        times = 60860 + np.concatenate([v + np.arange(3) * 0.0015 for v in (0.0, 0.3, 0.6, 1.0)])
    stars = [(200 + rng.uniform(-0.09, 0.09), -8 + rng.uniform(-0.09, 0.09)) for _ in range(n_stars)]
    t0 = times.mean()
    dets, truth = [], []
    for k, t in enumerate(times):
        img = rng.normal(0, 1, (80, 80))
        for ra, dec in stars:
            img = M.inject_point_source(img, w, ra, dec, 20.0, 9.0)
        h = (t - t0) * 24
        x, y = mover[0] * h + accel * h * h, mover[1] * h
        ra, dec = M.from_plane(x, y, 200.0, -8.0)
        truth.append((x, y))
        if with_mover:
            img = M.inject_point_source(img, w, float(ra), float(dec), amp, 9.0)
        dets += M.detect(img, np.ones_like(img), np.zeros(img.shape, bool), w, t, epoch=k)
    t = np.array([d.mjd for d in dets])
    xi, eta = M.to_plane([d.ra for d in dets], [d.dec for d in dets], 200.0, -8.0)
    return dets, t, xi, eta, np.array([d.err_arcsec for d in dets]), np.array([d.epoch for d in dets]), truth


def test_plane_round_trip():
    ra, dec = M.from_plane([100.0, -250.0], [30.0, 400.0], 359.99, 45.0)
    xi, eta = M.to_plane(ra, dec, 359.99, 45.0)
    assert np.allclose(xi, [100.0, -250.0], atol=1e-6) and np.allclose(eta, [30.0, 400.0], atol=1e-6)


def test_detect_centroid_and_mask():
    # SIMULATED: one source at a known sub-pixel position; a flagged pixel on a second one.
    rng = np.random.default_rng(1)
    w = _wcs()
    img = rng.normal(0, 1, (80, 80))
    ra, dec = (float(v) for v in w.pixel_to_world_values(30.3, 41.7))
    img = M.inject_point_source(img, w, ra, dec, 30.0, 9.0)
    ra2, dec2 = (float(v) for v in w.pixel_to_world_values(60.0, 20.0))
    img = M.inject_point_source(img, w, ra2, dec2, 30.0, 9.0)
    bad = np.zeros(img.shape, bool)
    bad[20, 60] = True
    d = M.detect(img, np.ones_like(img), bad, w, 60000.0)
    assert len(d) == 1
    sep = np.hypot((d[0].ra - ra) * np.cos(np.radians(dec)), d[0].dec - dec) * 3600
    assert sep < 3 * d[0].err_arcsec + 0.2 and d[0].err_arcsec < 1.0


def test_amplitude_for_snr_matches_filter():
    w = _wcs()
    var = np.full((80, 80), 4.0)
    a = M.amplitude_for_snr(var, np.zeros((80, 80), bool), w, 40.0, 40.0, 10.0, 9.0)
    ra, dec = (float(v) for v in w.pixel_to_world_values(40.0, 40.0))
    img = M.inject_point_source(np.zeros((80, 80)), w, ra, dec, a, 9.0)
    sigma = 9.0 / SCALE * M.FWHM_TO_SIGMA
    snr, _, _ = M.matched_filter(img, var, np.zeros((80, 80), bool), sigma)
    assert abs(snr[40, 40] - 10.0) < 0.3


def test_fit_track_rejects_outlier():
    rng = np.random.default_rng(2)
    t = 60000 + np.linspace(0, 2, 12)
    h = (t - t.mean()) * 24
    xi, eta = 10 * h + rng.normal(0, 0.3, 12), -4 * h + rng.normal(0, 0.3, 12)
    xi[5] += 20
    f = M.fit_track(t, xi, eta, np.full(12, 0.3), order=1)
    assert not f.inliers[5] and f.inliers.sum() == 11
    vx, vy, ex, ey = f.rate_arcsec_per_hour
    assert abs(vx - 10) < 4 * ex and abs(vy + 4) < 4 * ey


def test_visits_groups_dithers():
    t = 60000 + np.array([0, 0.001, 0.002, 0.5, 0.5015, 1.2])
    assert M.visits(t).tolist() == [0, 0, 0, 1, 1, 2]


def test_link_recovers_simulated_mover_with_acceleration():
    rng = np.random.default_rng(3)
    dets, t, xi, eta, err, ep, truth = _sequence(rng, accel=0.05)
    static = M.flag_static(t, xi, eta, 6.0, 4.0)
    tracks = M.link(t, xi, eta, err, epoch=ep, v_min=1.5, v_max=120, tol_arcsec=12, exclude=static, order=2)
    assert len(tracks) == 1
    tr = tracks[0]
    assert tr.n_visits == 4 and tr.n_epochs >= 10
    vx, vy, _, _ = tr.fit.rate_arcsec_per_hour
    h_ref = (tr.fit.t_ref - t.mean()) * 24
    assert abs(vx - (8 + 2 * 0.05 * h_ref)) < 0.5 and abs(vy + 5) < 0.5


def test_no_track_without_mover_or_with_shuffled_times():
    # SIMULATED static field: nothing should link. Then the same detections of
    # a field WITH a mover, but with epoch times permuted: no coherent motion.
    rng = np.random.default_rng(4)
    _, t, xi, eta, err, ep, _ = _sequence(rng, with_mover=False)
    static = M.flag_static(t, xi, eta, 6.0, 4.0)
    assert M.link(t, xi, eta, err, epoch=ep, v_min=1.5, v_max=120, tol_arcsec=12, exclude=static) == []

    _, t, xi, eta, err, ep, _ = _sequence(rng, mover=(30.0, 20.0))
    times = np.unique(t)
    perm = dict(zip(times, rng.permutation(times)))
    ts = np.array([perm[v] for v in t])
    static = M.flag_static(ts, xi, eta, 6.0, 4.0)
    assert M.link(ts, xi, eta, err, epoch=ep, v_min=1.5, v_max=120, tol_arcsec=12, exclude=static, order=1) == []


def test_static_flag_needs_time_baseline():
    t = 60000 + np.array([0.0, 0.002, 0.5])
    xi, eta = np.array([0.0, 0.5, 200.0]), np.array([0.0, 0.0, 0.0])
    # Two dithers 3 minutes apart at the same place are NOT enough to call a source static.
    assert M.flag_static(t, xi, eta, 6.0, 4.0).tolist() == [False, False, False]
    t2 = 60000 + np.array([0.0, 0.5])
    assert M.flag_static(t2, np.zeros(2), np.zeros(2), 6.0, 4.0).tolist() == [True, True]
