"""Quality checks on real SPHEREx cutouts (see fixtures/fixtures_provenance.json)."""

from pathlib import Path

import numpy as np

from hipparchus import quality

FX = Path(__file__).parent / "fixtures"
RW_AUR = (76.956, 30.401)
BARNARD = (269.4463, 4.7667)


def test_clean_epoch_is_usable_with_physical_metadata():
    ep = quality.load(str(FX / "rwaur_d1_2025.fits"), "2025W36_1A_0233_3", *RW_AUR)
    assert ep.usable, ep.issues
    assert ep.detector == 1
    # Detector 1 covers roughly 0.75-1.1 microns.
    assert 0.74 < ep.wavelength_um < 1.1
    assert 0 < ep.bandwidth_um < 0.05
    # Mid-exposure time must agree with the archive listing (early September 2025).
    assert ep.date_obs.startswith("2025-09")
    assert 60900 < ep.mjd < 60930
    # The target lands inside the cutout, and the variance is positive there.
    ny, nx = ep.image.shape
    assert 2 <= ep.x <= nx - 3 and 2 <= ep.y <= ny - 3
    assert np.all(ep.variance[int(ep.y), int(ep.x)] > 0)


def test_saturated_star_is_rejected_with_named_flags():
    ep = quality.load(str(FX / "barnard_d6.fits"), "2025W33_2C_0321_1", *BARNARD)
    assert not ep.usable
    codes = {i.code for i in ep.issues}
    assert "flagged_pixels" in codes
    # Barnard's Star is far too bright for SPHEREx: the reason must say so
    # in terms a person can check against the FLAGS header.
    assert any(k in ep.flag_counts for k in ("OVERFLOW", "BLOOM", "NONLINEAR"))


def test_plane_names_come_from_the_file_header():
    from astropy.io import fits
    with fits.open(FX / "barnard_d6.fits") as h:
        planes = quality._plane_masks(h["FLAGS"].header)
    assert planes["OVERFLOW"] == 2
    assert planes["SOURCE"] == 2097152
    assert "SOURCE" not in quality.BAD_PLANES
