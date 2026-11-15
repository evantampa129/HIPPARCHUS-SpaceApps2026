"""Audit checks for the photometry, each reproducible without network access."""

import numpy as np

from hipparchus import robustness as R
from hipparchus.compare import photometry


def _flat(n=29):
    return np.zeros((n, n)), np.ones((n, n)), np.zeros((n, n), bool)


def test_flagged_pixel_in_aperture_gives_no_flux():
    img, var, bad = _flat()
    bad[14, 15] = True
    assert np.isnan(photometry(img, var, bad, 14, 14)["flux"])


def test_too_little_sky_gives_no_flux_instead_of_zero_sky():
    img, var, bad = _flat()
    img += 5.0                      # a sky of 5 that a zero default would miss
    bad[:, :] = True
    bad[12:17, 12:17] = False       # aperture clean, annulus all flagged
    p = photometry(img, var, bad, 14, 14)
    assert np.isnan(p["flux"]) and p["n_sky"] < 8


def test_reprojected_errors_match_real_scatter():
    m = R.reprojection_noise_mc(n_trials=200)
    assert 0.85 < m["aperture_scatter_over_predicted"] < 1.15   # aperture sums: already right
    assert m["pixel_scatter_over_predicted_old"] < 0.7          # old per-pixel map: too timid
    assert 0.85 < m["pixel_scatter_over_predicted"] < 1.15      # corrected


def test_psf_width_change_bias_shrinks_with_aperture():
    small = R.psf_mismatch_bias(1.5, 2.0, 1.5)
    prod = R.psf_mismatch_bias(1.5, 2.0, 2.0)
    big = R.psf_mismatch_bias(1.5, 2.0, 3.0)
    assert small["ratio_mean"] < prod["ratio_mean"] < big["ratio_mean"]
    assert abs(big["ratio_mean"] - 1) < 0.01
    assert abs(prod["ratio_mean"] - 1) < 0.10


def test_trials_factor():
    t = R.trials(35)
    assert t["p_any_false_alarm"] < 1e-4 and 5.5 < t["sigma_bonferroni"] < 5.8


def test_classify_rule():
    assert R.classify("x", [True] * 4) == "robust"
    assert R.classify("x", [True, True, False, False]) == "sensitive"
    assert R.classify("x", [True, False, False]) == "inconclusive"
    assert R.classify("x", []) == "inconclusive"


def _field(scale_b, n=41, seed=3):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:n, 0:n]
    stars = [(8, 9, 300), (31, 10, 250), (10, 31, 400), (30, 30, 200), (20, 33, 350)]
    def img(scale):
        im = rng.normal(0, 1, (n, n))
        for x, y, f in stars:
            im += scale * f * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 0.65 ** 2)) / (2 * np.pi * 0.65 ** 2)
        return im
    z = np.zeros((n, n), bool)
    return {"a": img(1.0), "b": img(scale_b), "a_var": np.ones((n, n)), "b_var": np.ones((n, n)),
            "a_bad": z, "bad": z}


def test_ensemble_measures_a_field_wide_change():
    A = _field(1.10)
    e = R.ensemble(A, 20, 20)
    assert e["n"] >= 4
    assert abs(e["median"] - 1.10) < 0.03


def test_ensemble_finds_no_stars_in_empty_field():
    n = 41
    A = {"a": np.zeros((n, n)), "b": np.zeros((n, n)), "a_var": np.ones((n, n)), "b_var": np.ones((n, n)),
         "a_bad": np.zeros((n, n), bool), "bad": np.zeros((n, n), bool)}
    assert R.ensemble(A, 20, 20)["n"] == 0
