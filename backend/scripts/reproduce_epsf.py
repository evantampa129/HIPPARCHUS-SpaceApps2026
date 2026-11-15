"""EXPERIMENTAL: check the published aperture ratios with an independent ePSF fit.

Writes submission/evidence/epsf_check.json and report/figures/epsf_residuals.png.
Uses only cached real SPHEREx cutouts and the pairs already in robustness.json
(run reproduce_robustness.py first). Barnard's Star has no usable epoch and is
not fitted: its pixels are saturated, and no fit can fix that.

Agreement rule (fixed before looking at the result):
  z = (ln R_epsf - ln R_aperture) / sqrt(s_epsf^2 + s_ap^2), s = fractional errors
  compatible |z| < 3, discrepant |z| >= 5, inconclusive otherwise or if a fit failed.
Both methods read the same photons, so their errors are positively correlated
and this denominator is too large: "discrepant" is conservative, "compatible"
is lenient. That is stated with the result, not hidden.
"""

import json
import math
import resource
import sys
import time
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hipparchus import api, archive, cutouts, psf_photometry as P, quality  # noqa: E402

warnings.simplefilter("ignore")
ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "submission" / "evidence"
OUT = EVID / "epsf_check.json"
FIG = ROOT / "report" / "figures" / "epsf_residuals.png"
FREE_POSITION_SNR = 20  # bright stars: let the position move (<1 px); faint ones stay at the WCS position


def epoch_paths(t):
    m = json.loads(archive._manifest_path(t["ra"], t["dec"]).read_text())
    out = {}
    for o in m["observations"]:
        if o["detector"] == t["detector"]:
            p = cutouts.CACHE_DIR / f'{cutouts._key(o["access_url"], t["ra"], t["dec"], cutouts.DEFAULT_SIZE_DEG)}.fits'
            if p.exists():
                out[o["obs_id"]] = p
    return out


def fit_epoch(path, obs_id, t):
    ep = quality.load(str(path), obs_id, t["ra"], t["dec"])
    e = P.load_epsf(str(path), ep.x, ep.y)
    if e is None:
        return ep, None, {"ok": False, "reason": "no usable EPSF extension"}
    f = P.fit(ep.image, ep.variance, ep.bad, ep.x, ep.y, e)
    if f["ok"] and f["amp"] / f["amp_err"] >= FREE_POSITION_SNR:
        f = P.fit(ep.image, ep.variance, ep.bad, ep.x, ep.y, e, fit_position=True)
    if f["ok"]:
        # Standard practice: when chi2_red > 1 the model is imperfect, so the
        # amplitude error is scaled up by sqrt(chi2_red) (never down).
        f["amp_err_scaled"] = f["amp_err"] * math.sqrt(max(1.0, f["chi2_red"]))
    return ep, e, f


def simulated_checks(t, n_pos=4, seed=7):
    """SIMULATED stars injected into the real WISE 0855 cutouts (real sky, real noise).

    Positions are blank spots away from the target. For each: a fit with no star
    (noise only: false positives), then the same spot with an ePSF star of known
    flux added (bias and error calibration), and a 0.3 px position error
    (astrometric sensitivity). Aperture photometry on the same native pixels is
    done alongside for comparison.
    """
    from hipparchus.compare import photometry
    rng = np.random.default_rng(seed)
    out = {"label": "SIMULATED", "noise_only_pulls": [], "injected": [], "astrometry_0p3px_ratio": []}
    for oid, path in sorted(epoch_paths(t).items()):
        ep = quality.load(str(path), oid, t["ra"], t["dec"])
        if not ep.usable:
            continue
        ny, nx = ep.image.shape
        yy, xx = np.mgrid[0:ny, 0:nx].astype(float)
        for _ in range(n_pos):
            for _try in range(20):
                x0, y0 = rng.uniform(6, nx - 7), rng.uniform(6, ny - 7)
                if math.hypot(x0 - ep.x, y0 - ep.y) > 8 and not ep.bad[int(y0) - 3:int(y0) + 4, int(x0) - 3:int(x0) + 4].any():
                    break
            else:
                continue
            e = P.load_epsf(str(path), x0, y0)
            if e is None:
                continue
            f0 = P.fit(ep.image, ep.variance, ep.bad, x0, y0, e)
            if not f0["ok"]:
                continue
            out["noise_only_pulls"].append(f0["amp"] / f0["amp_err"])
            flux = 10 * f0["amp_err"]  # an S/N ~ 10 star
            img = ep.image + flux * P.render(e["psf"], e["ovs"], x0, y0, xx, yy)
            f1 = P.fit(img, ep.variance, ep.bad, x0, y0, e)
            ap = photometry(img, ep.variance, ep.bad, x0, y0)
            ap0 = photometry(ep.image, ep.variance, ep.bad, x0, y0)
            f2 = P.fit(img, ep.variance, ep.bad, x0 + 0.3, y0, e)
            for snr in (10, 50, 200):
                F = snr * f0["amp_err"]
                im2 = ep.image + F * P.render(e["psf"], e["ovs"], x0, y0, xx, yy)
                g = P.fit(im2, ep.variance, ep.bad, x0, y0, e)
                a2 = photometry(im2, ep.variance, ep.bad, x0, y0)
                if g["ok"] and g["amp"] > 0 and a2["flux"] > 0:
                    out.setdefault("pair_noise", []).append({
                        "snr": snr, "d": math.log(a2["flux"]) - math.log(g["amp"]),
                        "quad": math.hypot(a2["flux_err"] / a2["flux"], g["amp_err"] / g["amp"])})
            if f1["ok"]:
                out["injected"].append({"flux": flux, "amp": f1["amp"], "amp_err": f1["amp_err"],
                                        "pull": (f1["amp"] - f0["amp"] - flux) / flux,
                                        "aperture_minus_blank": ap["flux"] - ap0["flux"]})
            if f1["ok"] and f2["ok"]:
                out["astrometry_0p3px_ratio"].append(f2["amp"] / f1["amp"])
    pulls = np.array(out["noise_only_pulls"])
    inj = out["injected"]
    rec = np.array([(r["amp"] - r["flux"]) / r["flux"] for r in inj])
    ipull = np.array([r["pull"] for r in inj])  # fractional, should be ~1e-15
    apfrac = np.array([r["aperture_minus_blank"] / r["flux"] for r in inj])
    corr = {}
    for snr in (10, 50, 200):
        rr = [r for r in out.get("pair_noise", []) if r["snr"] == snr]
        if len(rr) > 10:
            d = np.array([r["d"] for r in rr])
            # < 1 means the two methods' errors are positively correlated: the true
            # scatter of their difference is smaller than the quadrature sum.
            corr[str(snr)] = float(np.std(d) / np.median([r["quad"] for r in rr]))
    out["difference_scatter_over_quadrature"] = corr
    out.pop("pair_noise", None)
    out["summary"] = {
        "n_noise_only": len(pulls), "noise_only_pull_std": float(np.std(pulls)),
        "noise_only_false_ge5": int(np.sum(np.abs(pulls) >= 5)), "noise_only_false_ge3": int(np.sum(np.abs(pulls) >= 3)),
        "n_injected": len(inj), "median_fractional_bias": float(np.median(rec)),
        # The model is linear in the amplitude, so an injected star must add exactly
        # its flux to the blank-sky fit; this checks the code, not the noise.
        "max_linearity_error": float(np.max(np.abs(ipull)) if len(ipull) else 0),
        "aperture_fraction_of_injected_flux": float(np.median(apfrac)),
        "astrometry_0p3px_median_ratio": float(np.median(out["astrometry_0p3px_ratio"]))}
    return out


def label(z):
    if z is None or not math.isfinite(z):
        return "inconclusive"
    return "compatible" if abs(z) < 3 else "discrepant" if abs(z) >= 5 else "inconclusive"


def main():
    t0 = time.perf_counter()
    rob = json.loads((EVID / "robustness.json").read_text())
    report = {"status": "EXPERIMENTAL - not used by any published number",
              "method": {"fit_box_px": 2 * P.FIT_HALF + 1, "free_position_snr": FREE_POSITION_SNR,
                         "background": "constant", "weights": "1/VARIANCE", "grid": "native, no reprojection",
                         "error_scaling": "amp_err * sqrt(max(1, chi2_red))"},
              "agreement_rule": __doc__.split("Agreement rule (fixed before looking at the result):")[1].strip(),
              "targets": {}}
    figs = []
    for t in api.TARGETS:
        tid = t["id"]
        pairs = rob["targets"][tid].get("pairs") or []
        if not pairs:
            report["targets"][tid] = {"verdict": "not fitted: no usable epoch (saturated / flagged pixels)"}
            print(tid, "not fitted")
            continue
        paths = epoch_paths(t)
        need = sorted({p["a"] for p in pairs} | {p["b"] for p in pairs})
        fits_, meta = {}, {}
        for oid in need:
            ep, e, f = fit_epoch(paths[oid], oid, t)
            fits_[oid] = f
            meta[oid] = {"zone": e and e["zone"], "zone_dist_px": e and e["dist_px"],
                         "epsf_sha256": e and e["sha256"], "epsf_source": e and e["source"],
                         "detcoord": e and e["detcoord"]}
            if f["ok"] and tid == "rw_aur" and len(figs) < 2:
                figs.append((tid, oid, f))
        rows = []
        for p in pairs:
            fa, fb = fits_[p["a"]], fits_[p["b"]]
            row = {"a": p["a"], "b": p["b"], "ratio_aperture": p["ratio"], "sig_aperture": p["sig"]}
            if fa["ok"] and fb["ok"]:
                row["sig_epsf"] = (fb["amp"] - fa["amp"]) / math.hypot(fa["amp_err_scaled"], fb["amp_err_scaled"])
                row["snr_epsf"] = [fa["amp"] / fa["amp_err_scaled"], fb["amp"] / fb["amp_err_scaled"]]
            snr_ok = (fa["ok"] and fb["ok"] and min(row.get("snr_epsf", [0])) >= 5
                      and min(p["fa"], p["fb"]) / p["err"] * math.sqrt(2) >= 5)
            if snr_ok:
                ra_ = fb["amp"] / fa["amp"]
                s_psf = math.hypot(fa["amp_err_scaled"] / fa["amp"], fb["amp_err_scaled"] / fb["amp"])
                s_ap = math.hypot(p["err"] / p["fa"], p["err"] / p["fb"]) / math.sqrt(2)
                z = (math.log(ra_) - math.log(p["ratio"])) / math.hypot(s_psf, s_ap)
                row |= {"ratio_epsf": ra_, "chi2_red": [fa["chi2_red"], fb["chi2_red"]], "shift_px": [fa["shift_px"], fb["shift_px"]],
                        "aperture_over_epsf_flux": [p["fa"] / fa["amp"], p["fb"] / fb["amp"]],
                        "z_agreement": z, "agreement": label(z),
                        "warnings": fa["warnings"] + fb["warnings"]}
            else:
                # A flux ratio means nothing below S/N 5; the claim is then checked on significances.
                row |= {"agreement": "inconclusive",
                        "reason": "; ".join(f["reason"] for f in (fa, fb) if not f["ok"]) or "S/N < 5 in an epoch"}
            rows.append(row)
        counts = {k: sum(r["agreement"] == k for r in rows) for k in ("compatible", "inconclusive", "discrepant")}
        report["targets"][tid] = {"n_pairs": len(rows), "agreement_counts": counts, "pairs": rows, "epochs": meta,
                                  "fits": {k: {kk: v for kk, v in f.items()
                                               if kk not in ("residual", "model", "data")} for k, f in fits_.items()}}
        sigs = [r["sig_epsf"] for r in rows if "sig_epsf" in r]
        report["targets"][tid]["claims_with_epsf"] = {
            "max_abs_sig_epsf": max(map(abs, sigs), default=None),
            "n_pairs_ge_5sigma_epsf": sum(abs(v) >= 5 for v in sigs),
            "n_pairs_brighter_epsf": sum(v > 0 for v in sigs), "n_fitted": len(sigs)}
        print(tid, counts, report["targets"][tid]["claims_with_epsf"])
    # Combined label from the stability audit and the ePSF check. Fixed rule:
    #   SUPPORTED VARIABILITY: a robust aperture claim of change, every pair
    #     compatible between methods, and the change >= 5 sigma with the ePSF too;
    #   LIKELY ARTIFACT: a >= 5 sigma aperture change that the ePSF calls discrepant
    #     or does not reproduce;
    #   INSUFFICIENT DATA: no usable epoch;  INCONCLUSIVE: anything else
    #     (including "no change seen" at low S/N, which is not proof of constancy).
    for t in api.TARGETS:
        r, tr = report["targets"][t["id"]], rob["targets"][t["id"]]
        if "pairs" not in r:
            r["label"] = "INSUFFICIENT DATA"
            continue
        robust_change = any(c["verdict"] == "robust" and "brightened" in c["claim"] for c in tr.get("claims", []))
        c = r["agreement_counts"]
        ap5 = any(abs(p["sig_aperture"]) >= 5 for p in r["pairs"])
        if robust_change and c["compatible"] == r["n_pairs"] and r["claims_with_epsf"]["n_pairs_ge_5sigma_epsf"] > 0:
            r["label"] = "SUPPORTED VARIABILITY"
        elif ap5 and (c["discrepant"] > 0 or r["claims_with_epsf"]["n_pairs_ge_5sigma_epsf"] == 0):
            r["label"] = "LIKELY ARTIFACT"
        else:
            r["label"] = "INCONCLUSIVE"
        print(t["id"], r["label"])
    sim = simulated_checks(next(t for t in api.TARGETS if t["id"] == "wise0855"))
    report["simulated_injection"] = sim
    k = min(sim["difference_scatter_over_quadrature"].values())  # the strictest (smallest) factor
    for r in report["targets"]["rw_aur"]["pairs"]:
        if "z_agreement" in r:
            r["z_correlated"] = r["z_agreement"] / k
            r["agreement_correlated"] = label(r["z_correlated"])
    report["correlation_factor_used"] = k
    rc = report["targets"]["rw_aur"]
    rc["agreement_counts_correlated"] = {x: sum(p.get("agreement_correlated") == x for p in rc["pairs"])
                                        for x in ("compatible", "inconclusive", "discrepant")}
    print("correlated:", sim["difference_scatter_over_quadrature"], rc["agreement_counts_correlated"],
          [round(p["z_correlated"], 2) for p in rc["pairs"]])
    print("SIMULATED", sim["summary"])
    report["benchmark"] = {"seconds": time.perf_counter() - t0,
                           "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024}
    OUT.write_text(json.dumps(report, indent=1, default=float) + "\n")
    if figs:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(len(figs), 3, figsize=(7.5, 2.6 * len(figs)))
        for k, (tid, oid, f) in enumerate(figs):
            for j, (img, title) in enumerate(((f["data"], "data"), (f["model"], "ePSF model"),
                                              (f["residual"] / np.nanstd(f["residual"]), "residual / rms"))):
                a = ax[k, j]
                a.imshow(img, origin="lower", cmap="RdBu_r" if j == 2 else "magma",
                         vmin=-3 if j == 2 else None, vmax=3 if j == 2 else None)
                a.set_title(f"{oid[-12:]} {title}", fontsize=7)
                a.set_xticks([]), a.set_yticks([])
        fig.suptitle("RW Aur: ePSF fit on native SPHEREx pixels (EXPERIMENTAL)", fontsize=9)
        fig.tight_layout()
        fig.savefig(FIG, dpi=150)
    print("wrote", OUT, report["benchmark"])


if __name__ == "__main__":
    main()
