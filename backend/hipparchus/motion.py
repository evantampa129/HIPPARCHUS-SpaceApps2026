"""Detect point sources in SPHEREx cutouts and link the ones that move.

Track B is a validation experiment: it checks whether the pipeline can follow
a KNOWN Solar System body across exposures. Nothing in this module decides
what a linked track is; it only says that a set of detections is consistent
with one source moving at a steady rate on the sky.

Steps
  detect()      matched filter with the cutout's own VARIANCE and flag mask,
                local S/N peaks, PSF-fit centroids, pixel -> RA/Dec via the WCS.
  to_plane()    RA/Dec -> tangent-plane offsets (arcsec, "RA cos Dec" and Dec).
  flag_static() sources seen at the same place at clearly different times.
  link()        KD-tree pair search with a speed window, extension to the
                other epochs, robust polynomial fit of position against time.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage, optimize
from scipy.spatial import cKDTree

FWHM_TO_SIGMA = 1.0 / (2.0 * np.sqrt(2.0 * np.log(2.0)))


@dataclass
class Detection:
    """One point source found in one cutout."""

    epoch: int           # index of the cutout in the list given to the caller
    mjd: float
    x: float             # 0-based pixel position in that cutout
    y: float
    ra: float            # deg
    dec: float
    err_arcsec: float    # 1-sigma position error per axis
    snr: float           # matched-filter S/N at the peak
    flux: float          # PSF amplitude (image units x pixel), for ranking only


def psf_kernel(sigma_px: float) -> np.ndarray:
    """Unit-sum circular Gaussian sampled on a (2h+1)^2 grid."""
    h = max(2, int(np.ceil(3.0 * sigma_px)))
    y, x = np.mgrid[-h:h + 1, -h:h + 1]
    k = np.exp(-(x ** 2 + y ** 2) / (2.0 * sigma_px ** 2))
    return k / k.sum()


def background(image: np.ndarray, bad: np.ndarray, box: int = 15) -> np.ndarray:
    """Running median over `box` pixels, with flagged pixels filled first."""
    # We fill flagged pixels with the global median before filtering, because a
    # median filter has no notion of a mask and NaNs would spread over the box.
    good = ~bad & np.isfinite(image)
    fill = np.median(image[good]) if good.any() else 0.0
    return ndimage.median_filter(np.where(good, image, fill), size=box, mode="reflect")


def matched_filter(image, variance, bad, sigma_px):
    """Return (snr, flux, noise_scale) maps for a point source at every pixel.

    flux = sum(P d / v) / sum(P^2 / v),  snr = sum(P d / v) / sqrt(sum(P^2 / v)).
    Flagged pixels get zero weight instead of being interpolated.
    """
    ok = ~bad & np.isfinite(image) & np.isfinite(variance) & (variance > 0)
    w = np.where(ok, 1.0 / np.where(ok, variance, 1.0), 0.0)
    d = np.where(ok, image, 0.0)
    k = psf_kernel(sigma_px)
    num = ndimage.correlate(d * w, k, mode="constant")
    den = ndimage.correlate(w, k * k, mode="constant")
    with np.errstate(invalid="ignore", divide="ignore"):
        snr = np.where(den > 0, num / np.sqrt(den), 0.0)
        flux = np.where(den > 0, num / den, 0.0)
    # We rescale the S/N by the robust width of its own distribution, but only
    # upwards: if the VARIANCE plane underestimates the real scatter (correlated
    # noise, residual zodi structure), an S/N cut would otherwise let noise in.
    vals = snr[ok & (den > 0)]
    scale = 1.0
    if vals.size > 50:
        mad = 1.4826 * np.median(np.abs(vals - np.median(vals)))
        scale = max(1.0, float(mad))
    return snr / scale, flux, scale


def fit_centroid(image, variance, bad, x0, y0, sigma_px, half=3):
    """Least-squares fit of a fixed-width Gaussian + constant around (x0, y0).

    Returns (x, y, amp, err_x, err_y) or None if the fit is not usable.
    """
    ny, nx = image.shape
    xi, yi = int(round(x0)), int(round(y0))
    ys, xs = slice(max(0, yi - half), min(ny, yi + half + 1)), slice(max(0, xi - half), min(nx, xi + half + 1))
    yy, xx = np.mgrid[ys, xs]
    d, v, m = image[ys, xs], variance[ys, xs], ~bad[ys, xs] & np.isfinite(image[ys, xs]) & (variance[ys, xs] > 0)
    if m.sum() < 8:
        return None
    xx, yy, d, s = xx[m].astype(float), yy[m].astype(float), d[m], np.sqrt(v[m])

    def model(p):
        a, cx, cy, b = p
        return a * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma_px ** 2)) + b

    p0 = [max(d.max() - np.median(d), 1e-6), float(x0), float(y0), float(np.median(d))]
    try:
        r = optimize.least_squares(lambda p: (model(p) - d) / s, p0, method="lm")
    except (ValueError, np.linalg.LinAlgError):
        return None
    a, cx, cy, _ = r.x
    # We refuse a centroid that wandered more than 1.5 px from the S/N peak:
    # that means the fit latched onto a neighbour or a gradient, not this peak.
    if not r.success or a <= 0 or np.hypot(cx - x0, cy - y0) > 1.5:
        return None
    dof = max(1, d.size - 4)
    chi2r = float(np.sum(r.fun ** 2) / dof)
    try:
        cov = np.linalg.inv(r.jac.T @ r.jac) * max(1.0, chi2r)
    except np.linalg.LinAlgError:
        return None
    return float(cx), float(cy), float(a), float(np.sqrt(cov[1, 1])), float(np.sqrt(cov[2, 2]))


def pixel_scale_arcsec(wcs) -> float:
    from astropy.wcs.utils import proj_plane_pixel_scales
    return float(np.mean(proj_plane_pixel_scales(wcs.celestial)) * 3600.0)


def detect(image, variance, bad, wcs, mjd, epoch=0, fwhm_arcsec=9.0, nsigma=5.0,
           edge_px=3, bkg_box=15) -> list[Detection]:
    """Point sources above `nsigma` in one cutout, with WCS positions."""
    scale = pixel_scale_arcsec(wcs)
    sigma_px = fwhm_arcsec / scale * FWHM_TO_SIGMA
    img = image - background(image, bad, bkg_box)
    snr, flux, noise_scale = matched_filter(img, variance, bad, sigma_px)
    peak = (snr == ndimage.maximum_filter(snr, size=3)) & (snr >= nsigma)
    # We drop peaks touching a flagged pixel: a hot pixel or a saturated core
    # next to the peak would bias the centroid in a direction we cannot model.
    peak &= ~ndimage.binary_dilation(bad, iterations=1)
    ny, nx = img.shape
    peak[:edge_px, :] = peak[-edge_px:, :] = False
    peak[:, :edge_px] = peak[:, -edge_px:] = False
    out = []
    for y0, x0 in zip(*np.nonzero(peak)):
        c = fit_centroid(img, variance * noise_scale ** 2, bad, x0, y0, sigma_px)
        if c is None:
            continue
        cx, cy, a, ex, ey = c
        ra, dec = (float(v) for v in wcs.celestial.pixel_to_world_values(cx, cy))
        out.append(Detection(epoch, float(mjd), cx, cy, ra % 360.0, dec,
                             float(np.hypot(ex, ey) / np.sqrt(2) * scale), float(snr[y0, x0]), a))
    return out


def to_plane(ra, dec, ra0, dec0):
    """Gnomonic projection about (ra0, dec0); returns (xi, eta) in arcsec.

    xi grows with RA and is already multiplied by cos(Dec), so both axes are
    true angles on the sky and a straight line in (xi, eta) is a great circle.
    """
    ra, dec, ra0, dec0 = (np.radians(np.asarray(v, float)) for v in (ra, dec, ra0, dec0))
    cosc = np.sin(dec0) * np.sin(dec) + np.cos(dec0) * np.cos(dec) * np.cos(ra - ra0)
    xi = np.cos(dec) * np.sin(ra - ra0) / cosc
    eta = (np.cos(dec0) * np.sin(dec) - np.sin(dec0) * np.cos(dec) * np.cos(ra - ra0)) / cosc
    return np.degrees(xi) * 3600.0, np.degrees(eta) * 3600.0


def from_plane(xi, eta, ra0, dec0):
    """Inverse of to_plane; returns (ra, dec) in degrees."""
    x, y = np.radians(np.asarray(xi, float) / 3600.0), np.radians(np.asarray(eta, float) / 3600.0)
    ra0, dec0 = np.radians(ra0), np.radians(dec0)
    rho = np.hypot(x, y)
    c = np.arctan(rho)
    with np.errstate(invalid="ignore", divide="ignore"):
        dec = np.where(rho > 0, np.arcsin(np.cos(c) * np.sin(dec0) + y * np.sin(c) * np.cos(dec0) / np.where(rho > 0, rho, 1)), dec0)
    ra = ra0 + np.arctan2(x * np.sin(c), rho * np.cos(dec0) * np.cos(c) - y * np.sin(dec0) * np.sin(c))
    return np.degrees(ra) % 360.0, np.degrees(dec)


def flag_static(t, xi, eta, radius_arcsec, min_dt_hours, min_count=1):
    """True for detections that reappear within `radius` at a clearly different time.

    "Clearly different" means at least `min_dt_hours` apart: a mover slower than
    radius/min_dt would look static, so the caller sets min_dt from the slowest
    speed it wants to find.
    """
    t = np.asarray(t, float)
    pts = np.column_stack([xi, eta])
    tree = cKDTree(pts)
    static = np.zeros(len(t), bool)
    for i, nb in enumerate(tree.query_ball_point(pts, r=radius_arcsec)):
        dt = np.abs(t[nb] - t[i]) * 24.0
        static[i] = np.count_nonzero(dt >= min_dt_hours) >= min_count
    return static


@dataclass
class TrackFit:
    coef_xi: np.ndarray        # polynomial coefficients, highest power first (np.polyfit order)
    coef_eta: np.ndarray
    cov_xi: np.ndarray
    cov_eta: np.ndarray
    t_ref: float               # MJD the polynomial is centred on
    inliers: np.ndarray        # bool per input point
    resid_xi: np.ndarray       # arcsec, all points
    resid_eta: np.ndarray
    rms_arcsec: float          # per-axis rms of inliers
    chi2_red: float

    def at(self, mjd):
        h = (np.asarray(mjd, float) - self.t_ref) * 24.0
        return np.polyval(self.coef_xi, h), np.polyval(self.coef_eta, h)

    @property
    def rate_arcsec_per_hour(self) -> tuple[float, float, float, float]:
        """(d xi/dt, d eta/dt, err_xi, err_eta) at t_ref."""
        return (float(self.coef_xi[-2]), float(self.coef_eta[-2]),
                float(np.sqrt(self.cov_xi[-2, -2])), float(np.sqrt(self.cov_eta[-2, -2])))


def fit_track(t, xi, eta, err, order=1, clip=4.0, n_iter=5, t_ref=None) -> TrackFit | None:
    """Weighted polynomial fit of position vs time with iterative outlier rejection.

    Time is in hours from `t_ref` (default: weighted mean time), positions in
    arcsec. A point is rejected when its residual exceeds `clip` times the
    larger of its own error and the robust scatter of the current fit.
    """
    t, xi, eta, err = (np.asarray(v, float) for v in (t, xi, eta, err))
    if t_ref is None:
        t_ref = float(np.average(t, weights=1 / err ** 2))
    h = (t - t_ref) * 24.0
    keep = np.ones(len(t), bool)
    for _ in range(n_iter):
        if np.count_nonzero(keep) < order + 2 or np.unique(h[keep]).size < order + 1:
            return None
        w = 1.0 / err[keep]
        cx, cvx = np.polyfit(h[keep], xi[keep], order, w=w, cov="unscaled")
        ce, cve = np.polyfit(h[keep], eta[keep], order, w=w, cov="unscaled")
        rx, re = xi - np.polyval(cx, h), eta - np.polyval(ce, h)
        r = np.hypot(rx, re) / np.sqrt(2)
        robust = 1.4826 * np.median(r[keep])
        # We clip against max(own error, robust scatter): with only the formal
        # errors one underestimated error would throw out a good point, and with
        # only the scatter an unusually tight fit would reject points that sit
        # well within their own errors.
        new = r <= clip * np.maximum(err, robust)
        if np.array_equal(new, keep):
            break
        keep = new
    if np.count_nonzero(keep) < order + 2:
        return None
    dof = max(1, 2 * (np.count_nonzero(keep) - (order + 1)))
    chi2 = float(np.sum((rx[keep] ** 2 + re[keep] ** 2) / err[keep] ** 2) / dof)
    # We inflate the covariance by chi2_red when it exceeds 1, the usual
    # correction when the quoted errors are too small for the real scatter.
    s = max(1.0, chi2)
    return TrackFit(cx, ce, cvx * s, cve * s, t_ref, keep, rx, re,
                    float(np.sqrt(np.mean((rx[keep] ** 2 + re[keep] ** 2) / 2))), chi2)


@dataclass
class Track:
    members: np.ndarray        # indices into the detection arrays given to link()
    fit: TrackFit
    n_epochs: int              # cutouts contributing one detection each
    n_visits: int              # groups of epochs closer than visit_gap_hours
    speed_arcsec_per_hour: float


def visits(t, gap_hours=0.5) -> np.ndarray:
    """Label each time with its visit: times closer than `gap_hours` share one.

    SPHEREx takes a few dithered exposures within minutes, then moves on for
    hours. A short burst of exposures says little about motion, so tracks are
    judged by how many separate visits they span.
    """
    t = np.asarray(t, float)
    order = np.argsort(t)
    lab = np.empty(len(t), int)
    lab[order] = np.concatenate([[0], np.cumsum(np.diff(t[order]) * 24.0 > gap_hours)])
    return lab


def link(t, xi, eta, err, *, v_min, v_max, tol_arcsec, epoch=None, min_visits=3,
         min_dt_hours=1.0, order=1, visit_gap_hours=0.5, max_tracks=10, max_seeds=25,
         exclude=None, vet=None, rejected=None) -> list[Track]:
    """Group detections into tracks of one source moving at v_min..v_max arcsec/hour.

    t in MJD, positions in arcsec on one tangent plane, `epoch` the cutout each
    detection came from (default: one epoch per distinct time). `exclude` marks
    detections (e.g. static sources) that may not take part. A detection is
    used by at most one track; tracks are taken greedily, longest first.

    `vet` (opt-in, default None = no vetting, as in motion_check.json) is a dict
    {"radius_arcsec": r, "min_dt_hours": dt}: every candidate is then passed
    through degenerate_track() before it can win, and a degenerate one is
    dropped. If `rejected` is a list, each dropped candidate is appended to it
    as {"members": indices, "check": degenerate_track() result}.
    """
    t, xi, eta, err = (np.asarray(v, float) for v in (t, xi, eta, err))
    epoch = np.unique(t, return_inverse=True)[1] if epoch is None else np.asarray(epoch)
    vis = visits(t, visit_gap_hours)
    free = np.ones(len(t), bool) if exclude is None else ~np.asarray(exclude, bool)
    tracks: list[Track] = []
    while len(tracks) < max_tracks:
        idx = np.nonzero(free)[0]
        groups = {e: idx[epoch[idx] == e] for e in np.unique(epoch[idx])}
        trees = {e: cKDTree(np.column_stack([xi[g], eta[g]])) for e, g in groups.items()}
        t_of = {e: t[g[0]] for e, g in groups.items()}
        eps = sorted(groups, key=t_of.get)
        t_eps = np.array([t_of[e] for e in eps])
        seeds = {}
        for a in range(len(eps)):
            ga = groups[eps[a]]
            for b in range(a + 1, len(eps)):
                dt_h = (t_of[eps[b]] - t_of[eps[a]]) * 24.0
                # We need a real time baseline to define a velocity: two dithers a
                # few minutes apart give a speed dominated by centroid noise.
                if dt_h < min_dt_hours:
                    continue
                gb = groups[eps[b]]
                # We search only inside the disk a source at v_max could reach:
                # this is what keeps the pair count small in a crowded field.
                hits = trees[eps[b]].query_ball_point(np.column_stack([xi[ga], eta[ga]]),
                                                      r=v_max * dt_h + tol_arcsec)
                for ka, nbs in enumerate(hits):
                    i = ga[ka]
                    for kb in nbs:
                        j = gb[kb]
                        vx, vy = (xi[j] - xi[i]) / dt_h, (eta[j] - eta[i]) / dt_h
                        if not (v_min <= np.hypot(vx, vy) <= v_max):
                            continue
                        h = (t_eps - t[i]) * 24.0
                        m = _collect(eps, groups, trees, xi[i] + vx * h, eta[i] + vy * h, tol_arcsec, (i, j), epoch)
                        nv = len(np.unique(vis[m]))
                        if nv >= min(3, min_visits):
                            seeds[tuple(m)] = nv
        if not seeds:
            break
        best = None
        for m in sorted(seeds, key=seeds.get, reverse=True)[:max_seeds]:
            g = _grow(np.array(m), t, xi, eta, err, eps, groups, trees, t_of, tol_arcsec, order, epoch)
            if g is None:
                continue
            members, f = g
            if vet is not None:
                # We vet each candidate here, before the ranking, and not the
                # winner afterwards: a degenerate candidate must not take the
                # detections away from a real track that ranks below it.
                d = degenerate_track(t[members], xi[members], eta[members], f.coef_xi.size - 1,
                                     vet["radius_arcsec"], vet["min_dt_hours"],
                                     err=err[members], rate=f.rate_arcsec_per_hour[:2])
                if d is not None:
                    if rejected is not None and not any(np.array_equal(members, r["members"]) for r in rejected):
                        rejected.append({"members": members, "check": d})
                    continue
            nv = len(np.unique(vis[members]))
            key = (nv, len(members), -f.rms_arcsec)
            if best is None or key > best[0]:
                best = (key, members, f)
        if best is None or best[0][0] < min_visits:
            break
        _, members, f = best
        vx, vy, _, _ = f.rate_arcsec_per_hour
        if not (v_min <= np.hypot(vx, vy) <= v_max):
            free[members] = False
            continue
        tracks.append(Track(members, f, len(members), best[0][0], float(np.hypot(vx, vy))))
        free[members] = False
    return tracks


def _collect(eps, groups, trees, px, py, tol, seed, epoch):
    """Nearest free detection within `tol` of each predicted position, one per epoch."""
    out = list(seed)
    taken = {epoch[k] for k in seed}
    for e, x, y in zip(eps, px, py):
        if e in taken:
            continue
        d, k = trees[e].query([x, y], distance_upper_bound=tol)
        if np.isfinite(d):
            out.append(groups[e][k])
    return np.array(sorted(out))


def _grow(members, t, xi, eta, err, eps, groups, trees, t_of, tol, order, epoch, n_iter=4):
    """Refit and re-collect until the member list stops changing."""
    f = None
    for _ in range(n_iter):
        n_t = len(np.unique(t[members]))
        # We let the polynomial order rise only when there are spare points:
        # a quadratic through three points always "fits" and predicts nothing.
        f = fit_track(t[members], xi[members], eta[members], err[members],
                      order=max(1, min(order, n_t - 3)))
        if f is None:
            return None
        px, py = f.at(np.array([t_of[e] for e in eps]))
        new = _collect(eps, groups, trees, px, py, tol, (), epoch)
        if new.size == 0:
            return None
        if np.array_equal(new, members):
            break
        members = new
    f = fit_track(t[members], xi[members], eta[members], err[members],
                  order=max(1, min(order, len(np.unique(t[members])) - 3)))
    if f is None:
        return None
    members = members[f.inliers]
    f = fit_track(t[members], xi[members], eta[members], err[members],
                  order=max(1, min(order, len(np.unique(t[members])) - 3)))
    return None if f is None else (members, f)


def inject_point_source(image, wcs, ra, dec, amplitude, fwhm_arcsec):
    """Add a SIMULATED Gaussian point source at (ra, dec). Returns a new image.

    `amplitude` is the peak value in image units. The real noise of the cutout
    stays as it is; the source's own photon noise is not added, which makes the
    SIMULATED source slightly easier than a real one of the same flux.
    """
    sigma_px = fwhm_arcsec / pixel_scale_arcsec(wcs) * FWHM_TO_SIGMA
    x, y = (float(v) for v in wcs.celestial.world_to_pixel_values(ra % 360.0, dec))
    ny, nx = image.shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    return image + amplitude * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma_px ** 2))


def amplitude_for_snr(variance, bad, wcs, x, y, snr, fwhm_arcsec):
    """Peak amplitude that gives a matched-filter S/N of `snr` at pixel (x, y)."""
    sigma_px = fwhm_arcsec / pixel_scale_arcsec(wcs) * FWHM_TO_SIGMA
    ny, nx = variance.shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    p = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma_px ** 2))
    ok = ~bad & np.isfinite(variance) & (variance > 0)
    # We invert the matched-filter S/N of a model a*p, which is a * sqrt(sum(p^2 / v)).
    return float(snr / np.sqrt(np.sum(p[ok] ** 2 / variance[ok])))


# ---------------------------------------------------------------------------
# Track vetting. These checks were added after the Kleopatra run produced a
# second, unexplained 5-visit track. They do not change detect() or link();
# they are applied to a track afterwards and say why it may not be a mover.
# ---------------------------------------------------------------------------

def position_groups(xi, eta, radius_arcsec):
    """Label points that sit within `radius` of each other (friends-of-friends).

    A real mover spreads its detections along a path. A false track built from
    a few static sources, each detected only in a short burst of exposures,
    collapses into a few tight groups instead.
    """
    pts = np.column_stack([xi, eta])
    lab = -np.ones(len(pts), int)
    tree = cKDTree(pts)
    n = 0
    for i in range(len(pts)):
        if lab[i] >= 0:
            continue
        stack, lab[i] = [i], n
        while stack:
            for j in tree.query_ball_point(pts[stack.pop()], r=radius_arcsec):
                if lab[j] < 0:
                    lab[j] = n
                    stack.append(j)
        n += 1
    return lab


def degenerate_track(t, xi, eta, order, radius_arcsec, min_dt_hours, err=None, rate=None, nsigma=5.0):
    """Why a linked track may be an artefact of the fit, or None if it looks fine.

    Returns a dict when the members fall into at most `order + 1` position
    groups and no group spans `min_dt_hours`: a polynomial of that order passes
    exactly through order + 1 points, so such a "track" is guaranteed to fit and
    says nothing about motion. Each group is then reported with its time span.

    With `err` (arcsec per point) and `rate` ((d xi/dt, d eta/dt) in arcsec/h,
    the track's own fitted rate) a group also has to LOOK static: if its points
    are fitted better by the track's motion than by a fixed position, by more
    than nsigma^2 in chi2, the group shows motion and the track is not
    degenerate. Without this, a fast mover seen in three short visits, e.g.
    (433) Eros at 72"/h, is rejected: each visit is one tight group, yet the
    object visibly moves inside it.
    """
    t = np.asarray(t, float)
    xi, eta = np.asarray(xi, float), np.asarray(eta, float)
    lab = position_groups(xi, eta, radius_arcsec)
    groups = []
    for g in np.unique(lab):
        m = lab == g
        row = {"n": int(m.sum()), "mjd_min": float(t[m].min()), "mjd_max": float(t[m].max()),
               "span_hours": float((t[m].max() - t[m].min()) * 24.0),
               "xi": float(np.mean(xi[m])), "eta": float(np.mean(eta[m]))}
        if err is not None and rate is not None and m.sum() >= 2:
            w = 1.0 / np.asarray(err, float)[m] ** 2
            h = (t[m] - np.average(t[m], weights=w)) * 24.0
            # We compare two models with the same number of free parameters (a
            # mean position each): fixed, or moving at the track's rate. No new
            # rate is fitted, so a few noisy points cannot invent motion.
            def chi2(vx, vy):
                rx, ry = xi[m] - vx * h, eta[m] - vy * h
                return float(np.sum(w * ((rx - np.average(rx, weights=w)) ** 2 + (ry - np.average(ry, weights=w)) ** 2)))
            row["chi2_static_minus_moving"] = chi2(0.0, 0.0) - chi2(*rate)
        groups.append(row)
    moving = [g for g in groups if g.get("chi2_static_minus_moving", 0.0) > nsigma ** 2]
    if len(groups) <= order + 1 and all(g["span_hours"] < min_dt_hours for g in groups) and not moving:
        return {"n_position_groups": len(groups), "fit_order": order, "groups": groups}
    return None


def forced_snr(image, variance, bad, x, y, sigma_px, bkg_box=15):
    """Matched-filter S/N and PSF amplitude at a FIXED pixel position.

    Used to ask "is there something at this sky position in this exposure?"
    without a detection threshold: a static source shows a positive S/N in most
    exposures at the wavelengths where it is bright, a mover does not.
    """
    img = image - background(image, bad, bkg_box)
    snr, flux, _ = matched_filter(img, variance, bad, sigma_px)
    xi_, yi_ = int(round(x)), int(round(y))
    ny, nx = img.shape
    if not (0 <= xi_ < nx and 0 <= yi_ < ny):
        return None
    return float(snr[yi_, xi_]), float(flux[yi_, xi_])


def peak_sharpness(image, variance, x, y, sigma_px):
    """Peak pixel S/N divided by the mean S/N of its 4 nearest neighbours.

    For a point source sampled by the PSF this ratio is close to
    1 / exp(-1 / (2 sigma_px^2)) (about 3.5 for SPHEREx's sigma ~0.62 px).
    A single hot pixel or a cosmic-ray hit gives a much larger ratio because
    its neighbours are at the noise level. Returns (ratio, expected_ratio).
    """
    xi_, yi_ = int(round(x)), int(round(y))
    s = image / np.sqrt(np.where(variance > 0, variance, np.nan))
    peak = s[yi_, xi_]
    nb = np.nanmean([s[yi_ + 1, xi_], s[yi_ - 1, xi_], s[yi_, xi_ + 1], s[yi_, xi_ - 1]])
    expected = float(np.exp(1.0 / (2.0 * sigma_px ** 2)))
    return float(peak / nb) if nb > 0 else float("inf"), expected
