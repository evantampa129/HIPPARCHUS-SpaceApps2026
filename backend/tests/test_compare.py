"""Comparison logic on a real pair of RW Aurigae epochs one year apart."""

from dataclasses import replace
from pathlib import Path

import numpy as np

from hipparchus import compare, quality

FX = Path(__file__).parent / "fixtures"
RW_AUR = (76.956, 30.401)


def _pair():
    a = quality.load(str(FX / "rwaur_d1_2025.fits"), "2025W36_1A_0233_3", *RW_AUR)
    b = quality.load(str(FX / "rwaur_d1_2026.fits"), "2026W37_1A_0234_3", *RW_AUR)
    return a, b


def test_real_pair_is_compatible_and_compared():
    a, b = _pair()
    v = compare.compatibility(a, b)
    assert v.comparable and v.kind == "comparison"
    r = compare.compare(a, b)
    assert 360 < r["dt_days"] < 380
    assert r["flux_a"]["flux_err"] > 0 and r["flux_b"]["flux_err"] > 0
    assert np.isfinite(r["significance"])
    # The centroid moves by less than a pixel (6.15"): same star, same place.
    assert r["centroid_shift_arcsec"]["total"] < 3.0


def test_epoch_against_itself_shows_no_change():
    a, _ = _pair()
    r = compare.compare(a, replace(a, obs_id="copy", mjd=a.mjd + 10))
    # Not exactly zero: reprojecting through the SIP distortion and back moves
    # pixels by a tiny fraction, so allow a residual far below the noise.
    assert abs(r["significance"]) < 0.5
    assert not r["changed"]


def test_wavelength_mismatch_is_refused():
    a, b = _pair()
    b = replace(b, wavelength_um=a.wavelength_um + 0.1)
    v = compare.compatibility(a, b)
    assert not v.comparable and "wavelength_mismatch" in v.codes
    assert "spectrum" in v.reasons[0]


def test_flagged_epoch_is_refused():
    a, _ = _pair()
    bad = quality.load(str(FX / "barnard_d6.fits"), "2025W33_2C_0321_1", 269.4463, 4.7667)
    v = compare.compatibility(a, bad)
    assert not v.comparable
    assert "flagged_pixels" in v.codes and "different_detector" in v.codes


def test_same_visit_pair_is_a_null_test():
    a, _ = _pair()
    v = compare.compatibility(a, replace(a, obs_id="twin", mjd=a.mjd + 0.1))
    assert v.comparable and v.kind == "null_test"


def test_control_star_stays_constant_on_the_real_pair():
    # A neighbouring star in the same two images is the check that the method
    # and calibration are stable: it must not "change" like the target does.
    a, b = _pair()
    r = compare.compare(a, b)
    c = r["control_star"]
    assert c is not None
    assert abs(c["significance"]) < 5
