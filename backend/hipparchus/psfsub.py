"""PSF-matched difference imaging, tried against our direct difference.

EXPERIMENTAL (R&D). Nothing published uses this. compare.py subtracts epoch a from
epoch b after putting b on a's grid with bilinear reprojection, without matching
the PSFs. Here we try three alternatives on the same aligned pixels:

* "gauss": convolve the sharper epoch with a Gaussian so both have the same
  second moments (the simplest PSF matching);
* "al": an Alard & Lupton (1998) style kernel, a sum of Gaussians x polynomials,
  but fitted to the two ePSF *models*, not to stars: a 29x29 px cutout holds
  too few clean stars to fit a kernel from the data;
* "zogy": proper image subtraction (Zackay, Ofek & Gal-Yam 2016), with the
  matched-filter score S_corr. "zogy_white" uses one noise level per image, as in
  the paper; "zogy_colored" models the noise of the reprojected epoch as white
  noise smoothed by the bilinear interpolation kernel.

Which ZOGY assumptions SPHEREx breaks, and what we do about it:

* known, shift-invariant PSF: the ePSF is undersampled (FWHM ~1.2-1.5 px of
  6.15"), so a star's pixel image depends on where it falls inside the pixel.
  We use the ePSF averaged over sub-pixel phase (and, for b, over its own phase
  on its native grid) as "the" PSF. Point sources still differ from it by the phase.
* PSF of the reprojected epoch: we build it explicitly, the b ePSF sampled on
  b's pixels and bilinearly interpolated onto a's grid through the local WCS
  Jacobian, exactly as reproject_interp does to the data.
* white noise: VARIANCE varies (source noise near bright stars, nebulosity
  in the RW Aur field), and bilinear reprojection correlates neighbouring pixels.
  We use the full VARIANCE maps in the S_corr normalisation (the paper's
  source-noise term), and the "colored" variant for the interpolation.
* flux scale F_r = F_n = 1: both images are calibrated in MJy/sr; we do not fit
  a zero-point (the target varies, and there are 0-1 control stars per cutout).
* no resampling covariance: violated by construction (we reproject b). Only the
  "colored" variant models it, and only on average over the cutout.

Units: images in MJy/sr per pixel, so point-source "fluxes" are MJy/sr summed
over pixels, as in compare.photometry. Positions are 0-based pixels of a's grid.
"""

from __future__ import annotations

import math

import numpy as np
from reproject import reproject_interp
from scipy.signal import fftconvolve

from hipparchus import psf_photometry as P
from hipparchus.compare import bilinear_var_factor, photometry

STAMP_HALF = 6        # PSF stamps 13x13 native px: the ePSF table is 6.6 px wide
KERNEL_HALF = 3       # matching kernels 7x7 px
AL_BASIS = ((0.5, 4), (1.0, 2), (2.0, 2))   # (sigma px, polynomial degree), AL98 defaults scaled to our pixels
AL_RIDGE = 1e-6       # small ridge: 27 basis functions on a 13x13 target are nearly degenerate
N_PHASE = 4           # 4x4 sub-pixel phases per grid when averaging the PSF


def jacobian(wcs_a, wcs_b, x, y, h=0.5):
    """d(b pixel)/d(a pixel) at a's pixel (x, y), by central differences through the sky."""
    def to_b(px, py):
        return np.array(wcs_b.world_to_pixel_values(*wcs_a.pixel_to_world_values(px, py)), float)
    jx = (to_b(x + h, y) - to_b(x - h, y)) / (2 * h)
    jy = (to_b(x, y + h) - to_b(x, y - h)) / (2 * h)
    return np.stack([jx, jy], axis=1)   # columns: response to a's x and a's y


def psf_stamp(epsf, phase_a=(0.0, 0.0), jac=None, phase_b=(0.0, 0.0), half=STAMP_HALF):
    """Pixel image, on a's grid, of a unit point source at a-offset phase_a from the stamp centre.

    jac None: the epoch is a itself, the ePSF sampled at a's own pixel centres.
    jac given: the epoch is b, seen through the reprojection. b's pixels sample its
    ePSF (source at sub-pixel phase_b on b's grid), then each a pixel centre takes
    the bilinear mix of the 4 b pixels around it, as reproject_interp does.
    """
    psf, ovs = epsf["psf"], epsf["ovs"]
    v, u = np.mgrid[-half:half + 1, -half:half + 1].astype(float)
    if jac is None:
        return P.render(psf, ovs, phase_a[0], phase_a[1], u, v)
    # a pixel centre (u, v) in b coordinates, the source sitting at phase_b
    bx = phase_b[0] + jac[0, 0] * (u - phase_a[0]) + jac[0, 1] * (v - phase_a[1])
    by = phase_b[1] + jac[1, 0] * (u - phase_a[0]) + jac[1, 1] * (v - phase_a[1])
    ix, iy = np.floor(bx), np.floor(by)
    fx, fy = bx - ix, by - iy
    out = np.zeros_like(u)
    for dx, dy, w in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
        out += w * P.render(psf, ovs, phase_b[0], phase_b[1], ix + dx, iy + dy)
    return out


def mean_psf(epsf, jac=None, n=N_PHASE, half=STAMP_HALF):
    """psf_stamp averaged over sub-pixel phases (n x n on a, and n x n on b if jac), unit sum.

    This is the PSF a randomly placed point source has on average. Cost: n**2 (or n**4)
    renders of a 13x13 stamp, ~0.1 s for n=4 with jac.
    """
    ph = (np.arange(n) + 0.5) / n - 0.5
    acc = np.zeros((2 * half + 1,) * 2)
    for pa in ((a, b) for a in ph for b in ph):
        for pb in (((a, b) for a in ph for b in ph) if jac is not None else [(0.0, 0.0)]):
            acc += psf_stamp(epsf, pa, jac, pb, half)
    return acc / acc.sum()


def second_moments(p):
    """Covariance (px^2) of a stamp around its centroid; the negative ePSF wings are kept."""
    h = p.shape[0] // 2
    v, u = np.mgrid[-h:h + 1, -h:h + 1].astype(float)
    s = p.sum()
    mx, my = (p * u).sum() / s, (p * v).sum() / s
    cxx = (p * (u - mx) ** 2).sum() / s
    cyy = (p * (v - my) ** 2).sum() / s
    cxy = (p * (u - mx) * (v - my)).sum() / s
    return np.array([[cxx, cxy], [cxy, cyy]])


def gaussian_kernel(cov, half=KERNEL_HALF):
    """Sampled 2-D Gaussian with covariance cov (px^2), unit sum; a delta if cov ~ 0."""
    v, u = np.mgrid[-half:half + 1, -half:half + 1].astype(float)
    if np.trace(cov) < 1e-4:
        k = np.zeros_like(u)
        k[half, half] = 1
        return k
    ci = np.linalg.inv(cov + 1e-6 * np.eye(2))
    k = np.exp(-0.5 * (ci[0, 0] * u * u + 2 * ci[0, 1] * u * v + ci[1, 1] * v * v))
    return k / k.sum()


def _conv(img, k):
    return fftconvolve(img, k, mode="same")


def gauss_match(p_sharp, p_broad, half=KERNEL_HALF):
    """Gaussian kernel taking p_sharp to p_broad: covariance difference, negative eigenvalues clipped."""
    d = second_moments(p_broad) - second_moments(p_sharp)
    w, V = np.linalg.eigh(d)
    return gaussian_kernel(V @ np.diag(np.clip(w, 0, None)) @ V.T, half)


def al_basis(half=KERNEL_HALF, basis=AL_BASIS):
    """AL98 basis: exp(-r^2/2s^2) u^i v^j, i+j <= deg. The first has unit sum, the rest zero sum,
    so any combination keeps the flux scale at 1 (we do not fit a zero-point)."""
    v, u = np.mgrid[-half:half + 1, -half:half + 1].astype(float)
    out = []
    for s, deg in basis:
        g = np.exp(-(u * u + v * v) / (2 * s * s))
        for i in range(deg + 1):
            for j in range(deg + 1 - i):
                out.append(g * u ** i * v ** j)
    b0 = out[0] / out[0].sum()
    return [b0] + [b - b.sum() * b0 for b in out[1:]]


def al_match(p_sharp, p_broad, half=KERNEL_HALF, ridge=AL_RIDGE):
    """Least-squares AL kernel with p_sharp (x) K ~ p_broad on the model stamps (no noise involved)."""
    B = al_basis(half)
    target = (p_broad - _conv(p_sharp, B[0])).ravel()
    X = np.stack([_conv(p_sharp, b).ravel() for b in B[1:]], 1)
    c = np.linalg.solve(X.T @ X + ridge * np.trace(X.T @ X) / X.shape[1] * np.eye(X.shape[1]), X.T @ target)
    return B[0] + np.tensordot(c, np.array(B[1:]), 1)


def match_residual(p_sharp, p_broad, k):
    """|p_sharp (x) k - p_broad| / |p_broad| (L2): how well the kernel matches the models."""
    return float(np.linalg.norm(_conv(p_sharp, k) - p_broad) / np.linalg.norm(p_broad))


def bilinear_tkernel(wcs_a, wcs_b, shape):
    """2x2 bilinear kernel whose noise power matches the cutout-mean interpolation smoothing.

    Per axis the factor (1-f)^2 + f^2 varies with position (the grids are rotated);
    we take its mean m and the f that gives it, f = (1 - sqrt(2m - 1)) / 2.
    """
    ny, nx = shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    bx, by = wcs_b.world_to_pixel_values(*wcs_a.pixel_to_world_values(xx, yy))
    t = []
    for b in (by, bx):
        f = b - np.floor(b)
        m = float(np.mean((1 - f) ** 2 + f ** 2))
        fe = (1 - math.sqrt(max(2 * m - 1, 0.0))) / 2
        t.append(np.array([1 - fe, fe]))
    return np.outer(*t)


def _embed(stamp, shape):
    """Stamp centred on index (0, 0) of an array of `shape` (FFT convention)."""
    out = np.zeros(shape)
    h0, h1 = stamp.shape[0] // 2, stamp.shape[1] // 2
    out[:stamp.shape[0], :stamp.shape[1]] = stamp
    return np.roll(out, (-h0, -h1), axis=(0, 1))


def _corner(t, shp):
    """FFT of a small kernel placed at offsets (0, 0)..(1, 1), unrolled: the 2x2 bilinear
    weights act on the pixel and its +1 neighbours, so this is its natural origin."""
    z = np.zeros(shp)
    z[:t.shape[0], :t.shape[1]] = t
    return np.fft.fft2(z)


def zogy(R, N, VR, VN, p_r, p_n, tkern=None, pad=64):
    """ZOGY S and S_corr on a's grid (F_r = F_n = 1).

    R, N: sky-subtracted reference (epoch a) and new (b on a's grid), masked pixels = 0.
    VR, VN: per-pixel variance maps, 0 where masked. Without tkern they are used as
    independent-pixel variances (the paper's white-noise model, with its source-noise
    term). With tkern, VN is b's native variance seen on a's grid and N's noise is
    taken as that white noise convolved with tkern (the reprojection).
    Returns (S, S_corr, S_hat) on the original shape. Cost: a few FFTs of pad x pad.
    """
    ny, nx = R.shape
    shp = (max(pad, 2 * ny), max(pad, 2 * nx))

    def fft(a):
        z = np.zeros(shp)
        z[:ny, :nx] = a
        return np.fft.fft2(z)
    Pr, Pn = np.fft.fft2(_embed(p_r, shp)), np.fft.fft2(_embed(p_n, shp))
    good_r, good_n = VR > 0, VN > 0
    sr2 = float(np.median(VR[good_r]))
    sn2 = float(np.median(VN[good_n]))
    That = _corner(tkern, shp) if tkern is not None else None
    T2 = np.abs(That) ** 2 if tkern is not None else 1.0
    den2 = sn2 * T2 * np.abs(Pr) ** 2 + sr2 * np.abs(Pn) ** 2
    den2 = np.maximum(den2, 1e-12 * den2.max())
    kn_hat = np.conj(Pn) * np.abs(Pr) ** 2 / den2
    kr_hat = np.conj(Pr) * np.abs(Pn) ** 2 / den2
    S_hat = kn_hat * fft(N) - kr_hat * fft(R)
    S = np.fft.ifft2(S_hat).real[:ny, :nx]
    kn, kr = np.fft.ifft2(kn_hat).real, np.fft.ifft2(kr_hat).real
    if tkern is not None:
        # N = tkern (x) (white noise of variance VN): its contribution goes through (tkern (x) kn)^2
        kn = np.fft.ifft2(kn_hat * That).real
    var = (np.fft.ifft2(fft(VN) * np.fft.fft2(kn ** 2)).real
           + np.fft.ifft2(fft(VR) * np.fft.fft2(kr ** 2)).real)[:ny, :nx]
    with np.errstate(invalid="ignore", divide="ignore"):
        Sc = S / np.sqrt(np.clip(var, 1e-30, None))
    return S, Sc, S_hat, shp


def value_at(S_hat, shp, shape, x, y):
    """S at a sub-pixel position by Fourier interpolation (S is smooth after the matched filter)."""
    ky = np.fft.fftfreq(shp[0])[:, None]
    kx = np.fft.fftfreq(shp[1])[None, :]
    return float((S_hat * np.exp(2j * np.pi * (kx * x + ky * y))).sum().real / (shp[0] * shp[1]))


def _fill(img, mask, value):
    out = np.where(mask | ~np.isfinite(img), value, img)
    return out


def _dilate(mask, k, frac=0.01):
    """Pixels that take >= frac of the kernel's total |weight| from a masked pixel.

    A masked pixel is filled with the sky median before convolving, so a pixel that
    gets weight w from it is off by w * (true - sky); below 1% we accept that.
    """
    foot = (np.abs(k) >= frac * np.abs(k).sum()).astype(float)
    return fftconvolve(mask.astype(float), foot, mode="same") > 0.5


class Pair:
    """Everything the methods need for one (a, b) pair, built once.

    cmp is the output of compare.compare(a, b) (it carries the aligned arrays, so the
    direct difference is exactly the published one). epsf_a, epsf_b: load_epsf at the
    target in each epoch's own cutout. We use the target's zone for the whole cutout
    (29x29 px against a zone pitch of ~100 px).
    """

    def __init__(self, a, b, cmp, epsf_a, epsf_b, n_phase=N_PHASE):
        A = cmp["_arrays"]
        self.a, self.b = a, b
        self.shape = a.image.shape
        self.img_a, self.var_a = a.image, a.variance
        self.img_b0, self.var_b = A["b"], A["b_var"]      # b on a's grid; var_b = sum(w var), b's native level
        self.bad = A["bad"]
        self.vfac = bilinear_var_factor(a.wcs, b.wcs, self.shape)   # per-pixel variance after interpolation
        self.jac = jacobian(a.wcs, b.wcs, a.x, a.y)
        self.epsf_a, self.epsf_b = epsf_a, epsf_b
        self.p_a = mean_psf(epsf_a, None, n_phase)
        self.p_b = mean_psf(epsf_b, self.jac, n_phase)
        self.tkern = bilinear_tkernel(a.wcs, b.wcs, self.shape)
        ma, mb = second_moments(self.p_a), second_moments(self.p_b)
        self.sharper = "a" if np.trace(ma) < np.trace(mb) else "b"
        ps, pb_ = (self.p_a, self.p_b) if self.sharper == "a" else (self.p_b, self.p_a)
        self.k_gauss = gauss_match(ps, pb_)
        self.k_al = al_match(ps, pb_)
        self.psf_info = {"trace_cov_a_px2": float(np.trace(ma)), "trace_cov_b_px2": float(np.trace(mb)),
                         "sharper": self.sharper, "jacobian": self.jac.tolist(),
                         "rotation_deg": float(math.degrees(math.atan2(self.jac[1, 0], self.jac[0, 0]))),
                         "match_residual_none": match_residual(ps, pb_, np.pad([[1.0]], KERNEL_HALF)),
                         "match_residual_gauss": match_residual(ps, pb_, self.k_gauss),
                         "match_residual_al": match_residual(ps, pb_, self.k_al)}

    def inject(self, x, y, flux):
        """b on a's grid with a SIMULATED point source of `flux` added in b's native frame at a-pixel (x, y)."""
        if flux == 0:
            return self.img_b0
        b = self.b
        xb, yb = b.wcs.world_to_pixel_values(*self.a.wcs.pixel_to_world_values(x, y))
        ny, nx = b.image.shape
        yy, xx = np.mgrid[0:ny, 0:nx].astype(float)
        stamp = flux * P.render(self.epsf_b["psf"], self.epsf_b["ovs"], float(xb), float(yb), xx, yy)
        # reproject is linear, so reprojecting the star alone and adding it is the same as reprojecting b+star
        add, _ = reproject_interp((stamp, b.wcs), self.a.wcs, shape_out=self.shape)
        return self.img_b0 + np.nan_to_num(add)

    def optimal_sigma(self, x, y):
        """1-sigma of an optimal (PSF-weighted) flux of a point source at (x, y): a and b in quadrature.

        sigma^2 = 1 / sum(P^2 / VARIANCE) on each epoch's native pixels; this is the
        error of the ePSF fit with the background known. The injected "S/N" is flux / this.
        """
        out = []
        for ep, e, (px, py) in ((self.a, self.epsf_a, (x, y)),
                                (self.b, self.epsf_b, self.b.wcs.world_to_pixel_values(*self.a.wcs.pixel_to_world_values(x, y)))):
            ny, nx = ep.image.shape
            yy, xx = np.mgrid[0:ny, 0:nx].astype(float)
            p = P.render(e["psf"], e["ovs"], float(px), float(py), xx, yy)
            ok = ~ep.bad & (ep.variance > 0) & np.isfinite(ep.variance)
            out.append(1 / np.sum(p[ok] ** 2 / ep.variance[ok]))
        return math.sqrt(sum(out))

    def methods(self, img_b, only=None):
        """Run the methods (all, or those in `only`) on (a, img_b); per-method maps for stat_at."""
        want = set(only or METHODS)
        a_sky = float(np.median(self.img_a[~self.bad & np.isfinite(self.img_a)]))
        b_sky = float(np.median(img_b[~self.bad & np.isfinite(img_b)]))
        va_pix, vb_pix = self.var_a, self.var_b * self.vfac   # per-pixel variances on a's grid
        res = {}
        # direct: the published difference
        if "direct" in want:
            z = ((img_b - b_sky) - (self.img_a - a_sky)) / np.sqrt(va_pix + vb_pix)
            res["direct"] = {"bad": self.bad, "bad_a": self.a.bad, "z": np.where(self.bad, np.nan, z),
                             "ia": self.img_a, "va": self.var_a, "ib": img_b, "vb": self.var_b,
                             "D": (img_b - b_sky) - (self.img_a - a_sky), "V": va_pix + vb_pix, "kb": None}
        # PSF-matched: convolve the sharper epoch; the variance goes through K^2 (correlations ignored)
        for name, k in (("gauss", self.k_gauss), ("al", self.k_al)):
            if name not in want:
                continue
            bad = self.bad | _dilate(self.bad, k)
            ia, ib = _fill(self.img_a, self.bad, a_sky), _fill(img_b, self.bad, b_sky)
            fva = _fill(self.var_a, self.bad, np.nanmedian(self.var_a))
            fvb = _fill(self.var_b, self.bad, np.nanmedian(self.var_b))
            fvbp = _fill(vb_pix, self.bad, np.nanmedian(vb_pix))
            # Per-pixel z: variance through K^2 (pixel correlations ignored). Aperture sums
            # keep the unconvolved variance: with sum(K) = 1 and K much smaller than the
            # r = 2 px aperture, the sum's variance is close to sum(var), the same argument
            # compare.py uses for the reprojected epoch.
            if self.sharper == "a":
                ia, vap, vbp = _conv(ia, k), _conv(fva, k * k), fvbp
            else:
                ib, vap, vbp = _conv(ib, k), fva, _conv(fvbp, k * k)
            zz = ((ib - b_sky) - (ia - a_sky)) / np.sqrt(vap + vbp)
            res[name] = {"bad": bad, "bad_a": bad, "z": np.where(bad, np.nan, zz), "ia": ia, "va": fva, "ib": ib, "vb": fvb,
                         "D": (ib - b_sky) - (ia - a_sky), "V": vap + vbp, "kb": k if self.sharper == "b" else None}
        # ZOGY: global sky removed, masked pixels set to 0 with 0 variance
        R = np.where(self.bad, 0.0, self.img_a - a_sky)
        N = np.where(self.bad, 0.0, img_b - b_sky)
        VR = np.where(self.bad, 0.0, self.var_a)
        for name, tk, VN in (("zogy_white", None, np.where(self.bad, 0.0, vb_pix)),
                             ("zogy_colored", self.tkern, np.where(self.bad, 0.0, self.var_b))):
            if name not in want:
                continue
            S, Sc, S_hat, shp = zogy(R, N, VR, VN, self.p_a, self.p_b, tk)
            # No dilation: masked pixels enter as 0 with 0 variance, so S_corr stays
            # normalised next to them (it just has less signal there).
            bad = self.bad
            res[name] = {"bad": bad, "z": np.where(bad, np.nan, Sc), "S": S, "S_hat": S_hat, "shp": shp,
                         "Sden": np.where(Sc != 0, S / np.where(Sc == 0, 1, Sc), np.nan)}
        return res

    def psf_stat(self, m, x, y, half=STAMP_HALF):
        """Forced PSF-weighted significance of a brightening in b at (x, y) on a difference image.

        s = sum(P D / V) / sqrt(sum(P^2 / V)), P the PSF a point source in b has on a's grid
        at this exact sub-pixel phase (through the reprojection, and through K if b was
        convolved). V treats pixels as independent: the interpolation correlation is ignored,
        so the null width tells us what that costs. ZOGY maps fall back to stat_at.
        """
        if "D" not in m:
            return self.stat_at(m, x, y)
        i, j = int(round(y)), int(round(x))
        xb, yb = self.b.wcs.world_to_pixel_values(*self.a.wcs.pixel_to_world_values(x, y))
        xb, yb = float(xb), float(yb)
        p = psf_stamp(self.epsf_b, (x - j, y - i), self.jac, (xb - round(xb), yb - round(yb)), half)
        if m["kb"] is not None:
            p = _conv(p, m["kb"])
        ny, nx = self.shape
        i0, i1, j0, j1 = max(i - half, 0), min(i + half + 1, ny), max(j - half, 0), min(j + half + 1, nx)
        p = p[i0 - (i - half):p.shape[0] - (i + half + 1 - i1), j0 - (j - half):p.shape[1] - (j + half + 1 - j1)]
        D, V, bad = m["D"][i0:i1, j0:j1], m["V"][i0:i1, j0:j1], m["bad"][i0:i1, j0:j1]
        core = np.zeros_like(bad)
        core[max(i - 1 - i0, 0):i + 2 - i0, max(j - 1 - j0, 0):j + 2 - j0] = True
        ok = ~bad & np.isfinite(D) & np.isfinite(V) & (V > 0)
        if (core & ~ok).any():
            return float("nan")   # as everywhere else: no number from a flagged core
        return float(np.sum(p[ok] * D[ok] / V[ok]) / math.sqrt(np.sum(p[ok] ** 2 / V[ok])))

    @staticmethod
    def stat_at(m, x, y):
        """Forced significance of a brightening at (x, y) for one method's output."""
        if "S_hat" in m:
            j, i = int(round(x)), int(round(y))
            if m["bad"][i, j]:
                return float("nan")
            # sub-pixel S by Fourier interpolation, over the S_corr denominator of the nearest pixel
            return value_at(m["S_hat"], m["shp"], m["bad"].shape, x, y) / m["Sden"][i, j]
        pa = photometry(m["ia"], m["va"], m["bad_a"], x, y)   # direct: a's own mask, as compare.py
        pb = photometry(m["ib"], m["vb"], m["bad"], x, y)
        e = math.hypot(pa["flux_err"], pb["flux_err"])
        return (pb["flux"] - pa["flux"]) / e if e > 0 else float("nan")


METHODS = ("direct", "gauss", "al", "zogy_white", "zogy_colored")


def blank_positions(pair, avoid, n=12, r_min=8.0, edge=4, sep=3.0, seed=0):
    """Up to n positions on blank sky: >= r_min px from the target, >= sep from each other
    and from every (x, y) in avoid, aperture and 3x3 core clean in every method's mask."""
    rng = np.random.default_rng(seed)
    ny, nx = pair.shape
    a = pair.a
    cand = [(i, j) for i in range(edge, ny - edge) for j in range(edge, nx - edge)
            if math.hypot(j - a.x, i - a.y) >= r_min]
    rng.shuffle(cand)
    out = []
    for i, j in cand:
        x, y = j + rng.uniform(-0.4, 0.4), i + rng.uniform(-0.4, 0.4)
        if any(math.hypot(x - u, y - v) < sep for u, v in out + list(avoid)):
            continue
        if pair.bad[max(i - 2, 0):i + 3, max(j - 2, 0):j + 3].any():
            continue
        out.append((x, y))
        if len(out) == n:
            break
    return out


def local_peaks(z, bad, exclude, thresh=5.0):
    """Local maxima of |z| >= thresh outside the exclude mask (blind false-positive count)."""
    from scipy.ndimage import maximum_filter
    a = np.where(bad | exclude | ~np.isfinite(z), 0.0, np.abs(z))
    pk = (a == maximum_filter(a, size=3)) & (a >= thresh)
    return int(pk.sum())
