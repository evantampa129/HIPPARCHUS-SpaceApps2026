"""ePSF photometry on SIMULATED stars (offline): every star here is synthetic."""

import numpy as np
from astropy.io import fits

from hipparchus import psf_photometry as P


def _gauss_epsf(fwhm_px=1.5, ovs=5, n=33):
    s = fwhm_px / 2.3548 * ovs
    y, x = np.mgrid[0:n, 0:n] - (n - 1) / 2
    g = np.exp(-(x ** 2 + y ** 2) / (2 * s ** 2))
    return g / g.sum()


def _hdul(psf, with_epsf=True):
    img = fits.ImageHDU(np.zeros((29, 29)), name="IMAGE")
    img.header["CRPIX1A"], img.header["CRPIX2A"] = -100.0, -200.0
    hd = [fits.PrimaryHDU(), img]
    if with_epsf:
        cols = [fits.Column("XCENTER", "D", array=[50.0, 500.0]), fits.Column("YCENTER", "D", array=[50.0, 500.0]),
                fits.Column("EPSF", f"{psf.size}D", array=[psf.ravel(), psf.ravel() * 0 + 1 / psf.size])]
        t = fits.BinTableHDU.from_columns(cols, name="EPSF")
        t.header["OVSMPX"] = t.header["OVSMPY"] = 5
        hd.append(t)
    return fits.HDUList(hd)


def test_zone_and_missing_extension():
    psf = _gauss_epsf()
    e = P.load_epsf(_hdul(psf), 14.0, 14.0)  # parent pixel (115, 215): zone 0 is nearer
    assert e["zone"] == 0 and e["ovs"] == 5 and len(e["sha256"]) == 64
    assert P.load_epsf(_hdul(psf, with_epsf=False), 14.0, 14.0) is None


def test_recovers_simulated_flux_and_ratio():
    # SIMULATED: a star of known flux on a known background with Gaussian noise.
    rng = np.random.default_rng(3)
    e = {"psf": _gauss_epsf(), "ovs": 5}
    yy, xx = np.mgrid[0:29, 0:29].astype(float)
    pulls = []
    fits_ = {}
    for flux in (50.0, 100.0):
        for k in range(40):
            x0, y0 = 14 + rng.uniform(-0.5, 0.5), 14 + rng.uniform(-0.5, 0.5)
            img = flux * P.render(e["psf"], 5, x0, y0, xx, yy) + 2.0 + rng.normal(0, 0.5, xx.shape)
            f = P.fit(img, np.full(xx.shape, 0.25), np.zeros(xx.shape, bool), x0, y0, e)
            pulls.append((f["amp"] - flux) / f["amp_err"])
            fits_.setdefault(flux, []).append(f["amp"])
    assert abs(np.mean(pulls)) < 0.4 and 0.75 < np.std(pulls) < 1.3
    assert abs(np.mean(fits_[100.0]) / np.mean(fits_[50.0]) - 2.0) < 0.05


def test_flagged_core_is_refused():
    e = {"psf": _gauss_epsf(), "ovs": 5}
    bad = np.zeros((29, 29), bool)
    bad[14, 14] = True
    f = P.fit(np.ones((29, 29)), np.ones((29, 29)), bad, 14.0, 14.0, e)
    assert not f["ok"] and "flagged" in f["reason"]
