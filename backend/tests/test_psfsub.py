"""PSF-matched / ZOGY difference imaging (experimental). Synthetic inputs are SIMULATED;
the last test is a smoke test on the two real RW Aur fixture cutouts."""

import math
from pathlib import Path

import numpy as np
import pytest

from hipparchus import compare, psfsub as S, quality

FX = Path(__file__).parent / "fixtures"
RW_AUR = (76.956, 30.401)


def _gauss_epsf(fwhm_px, ovs=5, n=33):
    s = fwhm_px / 2.3548 * ovs
    y, x = np.mgrid[0:n, 0:n] - (n - 1) / 2
    g = np.exp(-(x ** 2 + y ** 2) / (2 * s ** 2))
    return {"psf": g / g.sum(), "ovs": ovs}


def test_stamps_have_unit_flux():
    # SIMULATED Gaussian ePSF; through a 180 deg rotation the bilinear stamp still keeps the flux
    e = _gauss_epsf(1.4)
    assert abs(S.psf_stamp(e, (0.3, -0.2)).sum() - 1) < 0.02
    rot = np.array([[-1.0, 0.0], [0.0, -1.0]])
    assert abs(S.psf_stamp(e, (0.3, -0.2), rot, (0.1, 0.4)).sum() - 1) < 0.02
    pb = S.mean_psf(e, rot, n=2)
    assert abs(pb.sum() - 1) < 1e-9
    # interpolation broadens: b's mean PSF is wider than a's
    assert np.trace(S.second_moments(pb)) > np.trace(S.second_moments(S.mean_psf(e, None, n=2)))


def test_kernels_match_simulated_psfs():
    sharp, broad = S.mean_psf(_gauss_epsf(1.2), None, 2), S.mean_psf(_gauss_epsf(1.7), None, 2)
    none = S.match_residual(sharp, broad, np.pad([[1.0]], S.KERNEL_HALF))
    kg, ka = S.gauss_match(sharp, broad), S.al_match(sharp, broad)
    assert abs(kg.sum() - 1) < 1e-9 and abs(ka.sum() - 1) < 1e-6
    rg, ra = S.match_residual(sharp, broad, kg), S.match_residual(sharp, broad, ka)
    assert none > 0.2 and rg < 0.5 * none and ra < 0.05


def test_zogy_null_is_unit_and_finds_simulated_source():
    # SIMULATED white noise, two different Gaussian PSFs, no source: S_corr ~ N(0, 1)
    rng = np.random.default_rng(1)
    pr, pn = S.mean_psf(_gauss_epsf(1.3), None, 2), S.mean_psf(_gauss_epsf(1.6), None, 2)
    vals = []
    for _ in range(6):
        R, N = rng.normal(0, 1.0, (29, 29)), rng.normal(0, 1.5, (29, 29))
        _, Sc, _, _ = S.zogy(R, N, np.ones((29, 29)), np.full((29, 29), 2.25), pr, pn)
        vals.append(Sc[6:-6, 6:-6].ravel())
    v = np.concatenate(vals)
    assert 0.85 < v.std() < 1.15 and abs(v.mean()) < 0.1
    # SIMULATED star appearing in N only, S/N ~ 15 in the optimal sense
    yy, xx = np.mgrid[0:29, 0:29].astype(float)
    star = S.P.render(_gauss_epsf(1.6)["psf"], 5, 14.0, 14.0, xx, yy)
    flux = 15 * 1.5 / math.sqrt(np.sum(star ** 2))
    R, N = rng.normal(0, 1.0, (29, 29)), rng.normal(0, 1.5, (29, 29)) + flux * star
    _, Sc, S_hat, shp = S.zogy(R, N, np.ones((29, 29)), np.full((29, 29), 2.25), pr, pn)
    assert Sc[14, 14] > 7 and np.unravel_index(np.argmax(Sc), Sc.shape) == (14, 14)
    # Fourier interpolation reproduces the pixel value at a pixel centre
    Sraw = np.fft.ifft2(S_hat).real[:29, :29]
    assert abs(S.value_at(S_hat, shp, (29, 29), 14.0, 14.0) - Sraw[14, 14]) < 1e-9


@pytest.mark.skipif(not (FX / "rwaur_d1_2026.fits").exists(), reason="fixture missing")
def test_real_fixture_pair_smoke():
    # Real cutouts, but the fixtures carry no EPSF extension: a SIMULATED Gaussian ePSF of the
    # header FWHM stands in. We check plumbing, not science: direct = published significance, and a
    # SIMULATED bright injection in blank sky shows up in every method.
    a = quality.load(str(FX / "rwaur_d1_2025.fits"), "2025W36_1A_0233_3", *RW_AUR)
    b = quality.load(str(FX / "rwaur_d1_2026.fits"), "2026W37_1A_0234_3", *RW_AUR)
    cmp = compare.compare(a, b)
    ea, eb = (_gauss_epsf(ep.psf_fwhm_arcsec / 6.15) for ep in (a, b))
    pr = S.Pair(a, b, cmp, ea, eb, n_phase=2)
    m0 = pr.methods(pr.img_b0)
    # the published number is the aperture significance (the per-pixel z map uses a different sky)
    assert abs(S.Pair.stat_at(m0["direct"], a.x, a.y) - cmp["significance"]) < 1e-6
    spots = S.blank_positions(pr, [(a.x, a.y)], n=3, seed=0)
    assert spots
    x, y = spots[0]
    m1 = pr.methods(pr.inject(x, y, 30 * pr.optimal_sigma(x, y)))
    for name in S.METHODS:
        s0 = pr.psf_stat(m0[name], x, y)
        s1 = pr.psf_stat(m1[name], x, y)
        if math.isfinite(s1):
            assert s1 - s0 > 8, name
