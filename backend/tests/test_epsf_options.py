"""ePSF fit options (neighbours, background, error model, normalisation) on SIMULATED data.

Every star, background and noise field here is synthetic; no real SPHEREx pixel is used.
"""

import numpy as np
from astropy.io import fits

from hipparchus import psf_photometry as P


def _epsf(fwhm_px=1.5, ovs=5, n=33, skew=0.0):
    s = fwhm_px / 2.3548 * ovs
    y, x = np.mgrid[0:n, 0:n] - (n - 1) / 2
    g = np.exp(-(x ** 2 + y ** 2) / (2 * s ** 2)) * (1 + skew * x / n)  # skew makes it asymmetric
    return g / g.sum()


def _scene(stars, bkg=2.0, sigma=0.5, seed=0, shape=(29, 29), psf=None, plane=(0.0, 0.0)):
    """SIMULATED image: (flux, x, y) stars + background (+ gradient) + Gaussian noise."""
    psf = _epsf() if psf is None else psf
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]].astype(float)
    img = bkg + plane[0] * (xx - 14) + plane[1] * (yy - 14)
    for f, x, y in stars:
        img = img + f * P.render(psf, 5, x, y, xx, yy)
    img = img + np.random.default_rng(seed).normal(0, sigma, shape)
    return img, np.full(shape, sigma ** 2), np.zeros(shape, bool)


def test_defaults_unchanged_by_new_options():
    e = {"psf": _epsf(), "ovs": 5}
    img, var, bad = _scene([(100.0, 14.2, 13.9)])
    a = P.fit(img, var, bad, 14.2, 13.9, e)
    b = P.fit(img, var, bad, 14.2, 13.9, e, background="constant", neighbours=(), model_error=0.0,
              var_scale=1.0, normalise_native=False)
    assert a["amp"] == b["amp"] and a["chi2_red"] == b["chi2_red"] and a["dof"] == 79


def test_neighbour_removes_bias_and_chi2():
    # SIMULATED: a star 3.5 px away with 30% of the target's flux.
    e = {"psf": _epsf(), "ovs": 5}
    img, var, bad = _scene([(100.0, 14.0, 14.0), (30.0, 17.5, 14.0)], seed=1)
    plain = P.fit(img, var, bad, 14.0, 14.0, e)
    nb = P.fit(img, var, bad, 14.0, 14.0, e, neighbours=[(17.5, 14.0)])
    assert plain["chi2_red"] > 3 and nb["chi2_red"] < 1.5
    assert abs(nb["amp"] - 100) < 3 * nb["amp_err"] and abs(nb["neighbour_amps"][0] - 30) < 3
    # A neighbour whose light misses the box is dropped, not fitted as a degenerate column.
    far = P.fit(img, var, bad, 14.0, 14.0, e, neighbours=[(14.0, 26.0)])
    assert far["n_neighbours"] == 0


def test_neighbour_moves_with_free_position():
    # SIMULATED: the WCS is off by 0.2 px for both stars; the fit must recover both fluxes.
    e = {"psf": _epsf(), "ovs": 5}
    img, var, bad = _scene([(400.0, 14.2, 14.0), (80.0, 17.7, 14.0)], seed=2)
    f = P.fit(img, var, bad, 14.0, 14.0, e, fit_position=True, neighbours=[(17.5, 14.0)])
    assert abs(f["x"] - 14.2) < 0.03 and abs(f["neighbour_amps"][0] - 80) < 4 and f["chi2_red"] < 1.5


def test_plane_and_none_background():
    e = {"psf": _epsf(), "ovs": 5}
    img, var, bad = _scene([(100.0, 14.0, 14.0)], plane=(0.3, -0.2), seed=3)
    const = P.fit(img, var, bad, 14.0, 14.0, e)
    plane = P.fit(img, var, bad, 14.0, 14.0, e, background="plane")
    assert plane["chi2_red"] < 1.5 < const["chi2_red"]
    none = P.fit(img - 2.0 - 0.3 * (np.arange(29)[None] - 14) + 0.2 * (np.arange(29)[:, None] - 14),
                 var, bad, 14.0, 14.0, e, background="none")
    assert none["bkg"] == 0.0 and none["dof"] == 81 - 1 and abs(none["amp"] - 100) < 3 * none["amp_err"]


def test_var_scale_only_rescales_chi2():
    e = {"psf": _epsf(), "ovs": 5}
    img, var, bad = _scene([(100.0, 14.0, 14.0)], seed=4)
    a = P.fit(img, var, bad, 14.0, 14.0, e)
    b = P.fit(img, var, bad, 14.0, 14.0, e, var_scale=4.0)
    assert np.isclose(a["amp"], b["amp"]) and np.isclose(a["chi2_red"] / 4, b["chi2_red"])
    assert np.isclose(2 * a["amp_err"], b["amp_err"])


def test_model_error_lowers_chi2_of_a_wrong_psf():
    # SIMULATED: data made with an asymmetric PSF, fitted with the symmetric one.
    e = {"psf": _epsf(), "ovs": 5}
    img, var, bad = _scene([(2000.0, 14.0, 14.0)], psf=_epsf(skew=3.0), seed=5)
    a = P.fit(img, var, bad, 14.0, 14.0, e)
    b = P.fit(img, var, bad, 14.0, 14.0, e, model_error=0.05)
    assert b["chi2_red"] < a["chi2_red"] and b["amp_err"] > a["amp_err"]


def test_normalise_native_removes_phase_dependence():
    # SIMULATED, noiseless: the same star at many sub-pixel phases, rendered with the
    # model itself scaled to sum 1 on native pixels, must come back with the same flux.
    psf = _epsf(fwhm_px=1.0)
    e = {"psf": psf, "ovs": 5}
    yy, xx = np.mgrid[0:29, 0:29].astype(float)
    amps_raw, amps_norm, sums = [], [], []
    for dx in np.linspace(-0.5, 0.5, 7):
        x0 = 14 + dx
        ns = P.native_sum(psf, 5, x0, 14.0)
        sums.append(ns)
        img = 100.0 * P.render(psf, 5, x0, 14.0, xx, yy) / ns
        var, bad = np.ones((29, 29)), np.zeros((29, 29), bool)
        amps_raw.append(P.fit(img, var, bad, x0, 14.0, e)["amp"])
        amps_norm.append(P.fit(img, var, bad, x0, 14.0, e, normalise_native=True)["amp"])
    assert np.ptp(sums) > 1e-3  # the raw model does depend on phase for a narrow PSF
    assert np.ptp(amps_norm) < 1e-6 * 100 and np.ptp(amps_raw) > 0.1


def test_zone_is_containing_cell_on_detector3_layout():
    # SIMULATED zone table with the detector-3 layout: 11 x 41 zones, pitch 185.5 x 49.8 px.
    xs = 92.23 + 185.45 * np.arange(11)
    ys = 24.38 + 49.76 * np.arange(41)
    X, Y = np.meshgrid(xs, ys)
    psf = _epsf()
    stack = np.repeat(psf.ravel()[None], X.size, 0)
    img = fits.ImageHDU(np.zeros((29, 29)), name="IMAGE")
    img.header["CRPIX1A"], img.header["CRPIX2A"] = 0.0, 0.0
    cols = [fits.Column("XCENTER", "E", array=X.ravel()), fits.Column("YCENTER", "E", array=Y.ravel()),
            fits.Column("EPSF", f"{psf.size}D", array=stack)]
    t = fits.BinTableHDU.from_columns(cols, name="EPSF")
    t.header["OVSMPX"] = t.header["OVSMPY"] = 5
    h = fits.HDUList([fits.PrimaryHDU(), img, t])
    rng = np.random.default_rng(6)
    for _ in range(200):
        xc, yc = rng.uniform(0, 2040), rng.uniform(0, 2040)
        e = P.load_epsf(h, xc - 1, yc - 1)  # parent = cutout + 1 - CRPIX1A
        i = e["zone"]
        assert abs(X.ravel()[i] - xc) <= 185.45 / 2 + 1e-3 and abs(Y.ravel()[i] - yc) <= 49.76 / 2 + 1e-3


def test_blank_sky_scale_matches_simulated_noise():
    # SIMULATED: noise 1.3x larger than the variance plane says.
    rng = np.random.default_rng(7)
    img = 5 + rng.normal(0, 1.3, (40, 40))
    s = P.blank_sky_scale(img, np.ones((40, 40)), np.zeros((40, 40), bool), 20, 20)
    assert 1.15 < s < 1.45
