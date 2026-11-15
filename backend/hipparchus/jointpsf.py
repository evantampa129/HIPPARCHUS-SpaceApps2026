"""Joint multi-epoch ePSF fit, and whether SPHEREx can split RW Aur A from B.

EXPERIMENTAL (R&D). Nothing published uses this. psf_photometry.fit treats each
epoch alone (its own position, flux and sky). Here all epochs share one sky
position, each keeps its own flux(es) and background, and we can add a second
point source at a fixed offset (RW Aur B, 1.4-1.6" from A in Gaia DR3, i.e.
~0.25 SPHEREx pixel of 6.15"). We then ask how well A and B fluxes are separated:
Fisher matrix (correlation of the two fluxes) and profile likelihood in the
flux fraction of B and in the separation.

Each epoch is a dict made by `epoch_box`:
  img, var, good, xx, yy  9x9 native pixels around the target (MJy/sr, MJy^2/sr^2)
  psf, ovs                its ePSF table (psf_photometry.load_epsf)
  comps                   [(x, y), ...] pixel positions of A (and B) before any shift
  neigh                   [(x, y), ...] other catalogue stars, free amplitudes, move with the shift
  sky_to_pix              2x2 matrix: pixel shift per arcsec of (east, north) offset
A shift in pixels moves every component together (a WCS error or a common offset).
Fluxes are amplitude x ePSF, in MJy/sr summed over pixels, as in psf_photometry.
Cost: one linear solve per evaluation (9x9 pixels, <= ~6 columns), ~0.3 ms.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import minimize

from hipparchus import psf_photometry as P

FIT_HALF = P.FIT_HALF
MAX_SHIFT_PX = 1.0    # as psf_photometry.fit: a larger free shift means the fit went elsewhere


def epoch_box(image, variance, bad, x0, y0, epsf, comps, neigh=(), sky_to_pix=None, half=FIT_HALF, var_scale=1.0):
    """Cut the (2 half + 1)^2 fit box around (x0, y0). None if it leaves the image or the core is flagged."""
    ny, nx = image.shape
    i0, j0 = int(round(y0)) - half, int(round(x0)) - half
    i1, j1 = i0 + 2 * half + 1, j0 + 2 * half + 1
    if i0 < 0 or j0 < 0 or i1 > ny or j1 > nx:
        return None
    yy, xx = np.mgrid[i0:i1, j0:j1].astype(float)
    img, var = image[i0:i1, j0:j1], variance[i0:i1, j0:j1] * var_scale
    good = ~bad[i0:i1, j0:j1] & np.isfinite(img) & np.isfinite(var) & (var > 0)
    if (((xx - x0) ** 2 + (yy - y0) ** 2 <= 1.5 ** 2) & ~good).any():
        return None
    psf, ovs = epsf["psf"], epsf["ovs"]
    # same 3% rule as psf_photometry.fit for neighbours worth fitting
    nb = [(float(a), float(c)) for a, c in neigh if P.render(psf, ovs, a, c, xx, yy)[good].sum() > 0.03]
    return {"img": img, "var": var, "good": good, "xx": xx, "yy": yy, "psf": psf, "ovs": ovs,
            "comps": [tuple(map(float, c)) for c in comps], "neigh": nb,
            "sky_to_pix": np.eye(2) / 6.15 if sky_to_pix is None else np.asarray(sky_to_pix, float)}


def _columns(e, shift, model, comps=None):
    sx, sy = shift
    comps = e["comps"] if comps is None else comps
    use = comps[:1] if model == "single" else comps[:2]
    cols = [P.render(e["psf"], e["ovs"], x + sx, y + sy, e["xx"], e["yy"]) for x, y in use]
    cols += [P.render(e["psf"], e["ovs"], x + sx, y + sy, e["xx"], e["yy"]) for x, y in e["neigh"]]
    cols.append(np.ones_like(e["xx"]))
    return cols, len(use)


def solve(e, shift, model="single", comps=None):
    """Linear fluxes (+ neighbours, + constant sky) at a given shift. Returns beta, cov, chi2, n_good, n_comp."""
    cols, nc = _columns(e, shift, model, comps)
    g = e["good"]
    X = np.stack([c[g] for c in cols], 1)
    w = 1.0 / e["var"][g]
    A = (X.T * w) @ X
    # pinv, not inv: at zero separation the A and B columns are identical
    cov = np.linalg.pinv(A)
    beta = cov @ ((X.T * w) @ e["img"][g])
    r = e["img"][g] - X @ beta
    return beta, cov, float(np.sum(r * r * w)), int(g.sum()), nc


def _nm(fun, x0, scale=0.05):
    x0 = np.asarray(x0, float)
    simplex = [x0] + [x0 + scale * np.eye(len(x0))[k] for k in range(len(x0))]
    return minimize(fun, x0, method="Nelder-Mead",
                    options={"xatol": 1e-4, "fatol": 1e-4, "maxiter": 600, "initial_simplex": simplex})


def fit_epoch(e, model="single", free_shift=True, comps=None):
    """One epoch alone: fluxes + sky, and a free 2-D pixel shift (|shift| <= MAX_SHIFT_PX) if asked."""
    shift = np.zeros(2)
    if free_shift:
        res = _nm(lambda s: solve(e, s, model, comps)[2] + 1e6 * max(0.0, math.hypot(*s) - MAX_SHIFT_PX), [0.0, 0.0])
        shift = res.x
    beta, cov, chi2, n, nc = solve(e, shift, model, comps)
    return {"shift_px": shift.tolist(), "beta": beta, "cov": cov, "chi2": chi2, "n": n, "n_comp": nc,
            "k_linear": len(beta), "k_nonlinear": 2 if free_shift else 0}


def fit_joint(E, model="single", free=True, comps_list=None):
    """All epochs: one shared sky offset (arcsec, east/north) mapped to each epoch's pixels; fluxes per epoch."""
    comps_list = comps_list or [None] * len(E)

    def total(off):
        return sum(solve(e, e["sky_to_pix"] @ off, model, c)[2] for e, c in zip(E, comps_list))
    off = _nm(total, [0.0, 0.0], scale=0.3).x if free else np.zeros(2)
    per = []
    for e, c in zip(E, comps_list):
        s = e["sky_to_pix"] @ off
        beta, cov, chi2, n, nc = solve(e, s, model, c)
        per.append({"shift_px": s.tolist(), "beta": beta, "cov": cov, "chi2": chi2, "n": n, "n_comp": nc,
                    "k_linear": len(beta)})
    chi2 = sum(p["chi2"] for p in per)
    dof = sum(p["n"] - p["k_linear"] for p in per) - (2 if free else 0)
    return {"offset_arcsec": off.tolist(), "epochs": per, "chi2": chi2, "dof": dof, "chi2_red": chi2 / dof}


def summary_per_epoch(fits):
    """Pooled chi2_red of independent per-epoch fits, with the shift parameters subtracted from the dof."""
    chi2 = sum(f["chi2"] for f in fits)
    dof = sum(f["n"] - f["k_linear"] - f["k_nonlinear"] for f in fits)
    return {"chi2": chi2, "dof": dof, "chi2_red": chi2 / dof,
            "chi2_red_each": [f["chi2"] / (f["n"] - f["k_linear"] - f["k_nonlinear"]) for f in fits]}


def total_flux(f):
    """A (+ B) flux and its error from one epoch's fit."""
    k = f["n_comp"]
    v = np.ones(k)
    return float(v @ f["beta"][:k]), float(math.sqrt(max(v @ f["cov"][:k, :k] @ v, 0.0)))


def fisher(e, beta, shift, model="pair", free_shift=True, h=1e-3):
    """Fisher matrix of (A, B, [neighbours], sky, [sx, sy]) at the fit; 1/var weights.

    The derivatives in the shift are numerical (+-h px). Returns cov and the
    correlation matrix; the A-B correlation and the error of f_B = B/(A+B) are
    what tell us whether the pair is split.
    """
    cols, nc = _columns(e, shift, model)
    g = e["good"]
    J = [c[g] for c in cols]
    if free_shift:
        for d in (np.array([h, 0.0]), np.array([0.0, h])):
            up, _ = _columns(e, np.asarray(shift) + d, model)
            dn, _ = _columns(e, np.asarray(shift) - d, model)
            # each shifted component weighted by its own fitted flux (the sky column has no derivative)
            J.append(sum(beta[k] * (up[k][g] - dn[k][g]) / (2 * h) for k in range(len(cols) - 1)))
    J = np.stack(J, 1)
    F = (J.T / e["var"][g]) @ J
    cov = np.linalg.pinv(F)
    sd = np.sqrt(np.clip(np.diag(cov), 0, None))
    corr = cov / np.outer(sd, sd)
    out = {"cov": cov, "corr": corr, "cond": float(np.linalg.cond(F))}
    if model == "pair":
        A_, B_ = beta[0], beta[1]
        grad = np.zeros(len(cov))
        grad[0], grad[1] = -B_ / (A_ + B_) ** 2, A_ / (A_ + B_) ** 2
        out |= {"corr_AB": float(corr[0, 1]), "fB": float(B_ / (A_ + B_)),
                "fB_err": float(math.sqrt(max(grad @ cov @ grad, 0.0)))}
    return out


def fisher_joint(E, fit, model="pair", h=1e-3):
    """Fisher matrix of the joint fit: per-epoch linear terms (A, B, neighbours, sky) and the shared
    sky offset (2, arcsec) last. Returns, per epoch, the A-B correlation and the error of f_B with
    every other parameter (including the shared offset) marginalised."""
    blocks, offs, sizes = [], [], []
    for e, f in zip(E, fit["epochs"]):
        cols, nc = _columns(e, f["shift_px"], model)
        g = e["good"]
        w = 1.0 / e["var"][g]
        Jl = np.stack([c[g] for c in cols], 1)
        Jo = []
        for k in range(2):
            d = e["sky_to_pix"][:, k] * h / np.linalg.norm(e["sky_to_pix"][:, k])
            up, _ = _columns(e, np.asarray(f["shift_px"]) + d, model)
            dn, _ = _columns(e, np.asarray(f["shift_px"]) - d, model)
            # derivative per arcsec: per-pixel derivative along the column, times its length
            Jo.append(sum(f["beta"][j] * (up[j][g] - dn[j][g]) / (2 * h) for j in range(len(cols) - 1))
                      * np.linalg.norm(e["sky_to_pix"][:, k]))
        blocks.append((Jl, w))
        offs.append((np.stack(Jo, 1), w))
        sizes.append(Jl.shape[1])
    n = sum(sizes) + 2
    F = np.zeros((n, n))
    i = 0
    for (Jl, w), (Jo, _), k in zip(blocks, offs, sizes):
        F[i:i + k, i:i + k] = (Jl.T * w) @ Jl
        F[i:i + k, -2:] = (Jl.T * w) @ Jo
        F[-2:, i:i + k] = F[i:i + k, -2:].T
        F[-2:, -2:] += (Jo.T * w) @ Jo
        i += k
    cov = np.linalg.pinv(F)
    out, i = [], 0
    for f, k in zip(fit["epochs"], sizes):
        A_, B_ = f["beta"][0], f["beta"][1]
        c = cov[i:i + 2, i:i + 2]
        grad = np.array([-B_ / (A_ + B_) ** 2, A_ / (A_ + B_) ** 2])
        out.append({"corr_AB": float(c[0, 1] / math.sqrt(c[0, 0] * c[1, 1])), "fB": float(B_ / (A_ + B_)),
                    "fB_err": float(math.sqrt(max(grad @ c @ grad, 0.0)))})
        i += k
    so = np.sqrt(np.diag(cov[-2:, -2:]))
    return {"per_epoch": out, "offset_err_arcsec": so.tolist(), "cond": float(np.linalg.cond(F))}


def profile_fraction(e, fgrid, free_shift=True):
    """chi2 as a function of f_B = B / (A + B), total flux and sky free, shift free or fixed.

    With f fixed the two components become one fixed-shape template, so the fit is
    a single-source fit with a mixed PSF. Returns chi2 per f and the best shifts.
    """
    out, shifts = [], []
    (xa, ya), (xb, yb) = e["comps"][:2]
    for f in fgrid:
        def chi(s, f=f):
            cols_a, _ = _columns(dict(e, comps=[(xa, ya)]), s, "single")
            cols_b, _ = _columns(dict(e, comps=[(xb, yb)]), s, "single")
            cols = [(1 - f) * cols_a[0] + f * cols_b[0]] + cols_a[1:]
            g = e["good"]
            X = np.stack([c[g] for c in cols], 1)
            w = 1.0 / e["var"][g]
            beta = np.linalg.lstsq(X * np.sqrt(w)[:, None], e["img"][g] * np.sqrt(w), rcond=None)[0]
            r = e["img"][g] - X @ beta
            return float(np.sum(r * r * w)) + 1e6 * max(0.0, math.hypot(*s) - MAX_SHIFT_PX)
        if free_shift:
            r = _nm(chi, shifts[-1] if shifts else [0.0, 0.0])
            out.append(float(r.fun))
            shifts.append(r.x.tolist())
        else:
            out.append(chi(np.zeros(2)))
            shifts.append([0.0, 0.0])
    return np.array(out), shifts


def profile_separation(e, rho_px, unit, free_shift=True):
    """chi2 of a two-source fit with B at A + rho * unit (px), both fluxes free, for each rho."""
    xa, ya = e["comps"][0]
    out, fb = [], []
    for rho in rho_px:
        comps = [(xa, ya), (xa + rho * unit[0], ya + rho * unit[1])]
        f = fit_epoch(e, "pair", free_shift, comps)
        out.append(f["chi2"])
        fb.append(float(f["beta"][1] / (f["beta"][0] + f["beta"][1])))
    return np.array(out), fb


def interval(grid, chi2, scale=1.0, delta=1.0):
    """Range of grid where (chi2 - min) / scale <= delta: the profile-likelihood interval (68% for delta=1)."""
    d = (np.asarray(chi2) - np.min(chi2)) / scale
    ok = np.asarray(grid)[d <= delta]
    return [float(ok.min()), float(ok.max())]
