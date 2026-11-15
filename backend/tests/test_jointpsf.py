"""Joint multi-epoch ePSF fit (experimental). Every star here is SIMULATED."""

import math

import numpy as np

from hipparchus import jointpsf as J, psf_photometry as P


def _gauss_epsf(fwhm_px=1.4, ovs=5, n=33):
    s = fwhm_px / 2.3548 * ovs
    y, x = np.mgrid[0:n, 0:n] - (n - 1) / 2
    g = np.exp(-(x ** 2 + y ** 2) / (2 * s ** 2))
    return {"psf": g / g.sum(), "ovs": ovs}


def _epoch(rng, comps_true, fluxes, comps_assumed, sky=3.0, sigma=0.5, rot_deg=0.0):
    """A SIMULATED 29x29 cutout with point sources at comps_true, and its fit box."""
    e = _gauss_epsf()
    yy, xx = np.mgrid[0:29, 0:29].astype(float)
    img = sky + sum(f * P.render(e["psf"], 5, x, y, xx, yy) for (x, y), f in zip(comps_true, fluxes))
    img = img + rng.normal(0, sigma, img.shape)
    c, s = math.cos(math.radians(rot_deg)), math.sin(math.radians(rot_deg))
    s2p = np.array([[c, -s], [s, c]]) / 6.15
    return J.epoch_box(img, np.full(img.shape, sigma ** 2), np.zeros(img.shape, bool), 14.0, 14.0, e,
                       comps_assumed, (), s2p)


def test_close_pair_is_degenerate():
    # SIMULATED single star at S/N ~ 60; a "B" 0.27 px away (RW Aur's separation) cannot be told
    # apart: with the shift free, B only broadens the image by ~(0.27/2)^2 px^2 along one axis.
    # (At S/N in the hundreds an exact PSF would see that broadening; the real ePSF is not that exact.)
    rng = np.random.default_rng(0)
    comps = [(14.1, 13.9), (14.1 + 0.27, 13.9)]
    e = _epoch(rng, comps[:1], [60.0], comps)
    f = J.fit_epoch(e, "pair")
    fi = J.fisher(e, f["beta"], f["shift_px"], "pair", True)
    assert fi["corr_AB"] < -0.95
    assert fi["fB_err"] > 0.3     # f_B unconstrained over most of [0, 1]
    # the total flux is still fine
    tot, err = J.total_flux(f)
    assert abs(tot - 60) < 4 * err and err < 0.1 * tot


def test_wide_pair_is_resolved():
    # SIMULATED control: at 2 px separation the same machinery does split A and B
    rng = np.random.default_rng(1)
    comps = [(13.0, 14.0), (15.0, 14.0)]
    e = _epoch(rng, comps, [300.0, 150.0], comps)
    f = J.fit_epoch(e, "pair")
    fi = J.fisher(e, f["beta"], f["shift_px"], "pair", True)
    assert abs(fi["corr_AB"]) < 0.6 and fi["fB_err"] < 0.03
    assert abs(fi["fB"] - 1 / 3) < 4 * fi["fB_err"]
    c, _ = J.profile_fraction(e, np.linspace(0, 1, 21), True)
    lo, hi = J.interval(np.linspace(0, 1, 21), c)
    assert lo > 0.15 and hi < 0.5


def test_joint_fit_shares_one_sky_offset():
    # SIMULATED: three epochs with different orientations, all offset by the same (1.0", -0.6")
    rng = np.random.default_rng(2)
    E = []
    for rot in (0.0, 90.0, 180.0):
        c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        d = np.array([[c, -s], [s, c]]) @ np.array([1.0, -0.6]) / 6.15
        E.append(_epoch(rng, [(14.0 + d[0], 14.0 + d[1])], [500.0], [(14.0, 14.0)], rot_deg=rot))
    jf = J.fit_joint(E, "single")
    assert abs(jf["offset_arcsec"][0] - 1.0) < 0.3 and abs(jf["offset_arcsec"][1] + 0.6) < 0.3
    assert 0.7 < jf["chi2_red"] < 1.4
    per = J.summary_per_epoch([J.fit_epoch(e, "single") for e in E])
    # the joint fit spends 4 fewer shift parameters for about the same chi2
    assert per["dof"] == jf["dof"] - 4 and abs(per["chi2_red"] - jf["chi2_red"]) < 0.2


def test_interval():
    g = np.linspace(0, 1, 11)
    assert np.allclose(J.interval(g, (g - 0.5) ** 2 * 99), [0.4, 0.6])
    assert np.allclose(J.interval(g, (g - 0.5) ** 2 * 99, scale=4.0), [0.3, 0.7])
