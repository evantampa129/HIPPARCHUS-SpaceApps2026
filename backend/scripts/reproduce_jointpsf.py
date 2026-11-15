"""EXPERIMENTAL: joint multi-epoch ePSF fit of RW Aur, and can SPHEREx split A from B?

Writes submission/evidence/jointpsf_check.json and report/figures/jointpsf_identifiability.png,
jointpsf_ratios.png. Nothing published changes.

Data: the 10 RW Aur epochs used by the 8 published pairs (robustness.json), real cached
cutouts, the same 9x9 box and ePSF zone as reproduce_epsf.py. Gaia DR3 positions of A
(G = 12.18) and B (G = 13.04) are propagated to each epoch (RW_AUR_GAIA in reproduce_epsf.py).

Models (each with a constant sky per epoch):
  per-epoch single  one source, own pixel shift per epoch (the published ePSF fit)
  joint single      one source, one sky offset shared by all epochs
  per-epoch pair    A + B at the Gaia offset, own shift per epoch
  joint pair        A + B, one shared sky offset
  fixed pair        A + B at the Gaia positions through each epoch's WCS, no shift
Each in two settings: "published" (as epsf_check.json) and "field_stars+sky_scale"
(Gaia field stars fitted, VARIANCE x measured blank-sky scale^2), the best fix found
in the epsf diagnostics.

Identifiability: Fisher correlation of the A and B fluxes and the error of
f_B = B / (A + B); profile likelihood in f_B and in the A-B separation; and SIMULATED
epochs (real ePSF, real VARIANCE, Gaussian noise) with a known single star or a known
pair, fitted the same way, with and without a small PSF mismatch.

Decision rule (fixed before running): we say "SPHEREx separates A and B" only if, in
the real data, (1) the 68% profile interval of f_B (Delta chi2 <= chi2_red, i.e. errors
scaled for the model error) excludes both 0 and 1 in every epoch, (2) it is stable to
a 0.15 px shift of the assumed positions (the size of the WCS offsets we measured),
and (3) the SIMULATED fits recover a known pair and a known single star as different
(|mean f_B difference| > 3 x their scatter) with the PSF mismatch included.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import reproduce_epsf as R  # noqa: E402
from hipparchus import api, jointpsf as J, psf_photometry as P  # noqa: E402

warnings.simplefilter("ignore")
ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "submission" / "evidence"
OUT = EVID / "jointpsf_check.json"
FIGS = ROOT / "report" / "figures"
FGRID = np.round(np.linspace(0, 1, 21), 3)
RHO_ARCSEC = np.round(np.arange(0.2, 3.01, 0.2), 2)
WCS_JITTER_PX = 0.15
N_SIM, SEED = 25, 7
F_PAIR_TRUE = 0.314        # B/(A+B) from Gaia G (13.035 vs 12.184); only a test value, not SPHEREx's band
JITTER_SIM_PX = 0.1        # PSF mismatch for the SIMULATED test: truth blurred by a 0.1 px Gaussian


def sky_to_pix(ep, ra, dec):
    """Pixel shift per arcsec of an (east, north) offset at (ra, dec), from the WCS."""
    x0, y0 = ep.wcs.world_to_pixel_values(ra, dec)
    d = 1.0 / 3600
    xe, ye = ep.wcs.world_to_pixel_values(ra + d / math.cos(math.radians(dec)), dec)
    xn, yn = ep.wcs.world_to_pixel_values(ra, dec + d)
    return np.array([[xe - x0, xn - x0], [ye - y0, yn - y0]], float)


def load(rob):
    t = next(x for x in api.TARGETS if x["id"] == "rw_aur")
    paths = R.epoch_paths(t)
    oids = sorted({p["a"] for p in rob["targets"]["rw_aur"]["pairs"]} | {p["b"] for p in rob["targets"]["rw_aur"]["pairs"]})
    out = []
    for oid in oids:
        ep = R.load_epoch(paths[oid], oid, t)
        out.append((oid, ep, P.load_epsf(str(paths[oid]), ep.x, ep.y)))
    return out


def boxes(epochs, setting):
    E, meta = [], []
    from astropy.time import Time
    from hipparchus import catalogs
    for oid, ep, e in epochs:
        g = R.gaia_pixels(ep)
        yr = Time(ep.mjd, format="mjd").decimalyear
        ra, dec = catalogs.propagate(*R.RW_AUR_GAIA[0][1:5], 2016.0, yr)
        nb = R.field_neighbours(ep, "rw_aur") if setting != "published" else ()
        vs = P.blank_sky_scale(ep.image, ep.variance, ep.bad, ep.x, ep.y) ** 2 if setting != "published" else 1.0
        b = J.epoch_box(ep.image, ep.variance, ep.bad, ep.x, ep.y, e, [(g[0]["x"], g[0]["y"]), (g[1]["x"], g[1]["y"])],
                        nb, sky_to_pix(ep, float(ra), float(dec)), var_scale=vs)
        E.append(b)
        dx, dy = g[1]["x"] - g[0]["x"], g[1]["y"] - g[0]["y"]
        meta.append({"epoch": oid, "sep_px": math.hypot(dx, dy), "unit_AB": [dx / math.hypot(dx, dy), dy / math.hypot(dx, dy)],
                     "sep_arcsec": math.hypot(*np.linalg.solve(b["sky_to_pix"], [dx, dy])),
                     "n_field_stars": len(b["neigh"]), "var_scale": vs})
    return E, meta


def ratios(rob, oids, fluxes):
    """Each published pair re-measured with these fluxes: ratio and deviation from the aperture ratio."""
    ix = {o: k for k, o in enumerate(oids)}
    out = []
    for p in rob["targets"]["rw_aur"]["pairs"]:
        r = fluxes[ix[p["b"]]] / fluxes[ix[p["a"]]]
        out.append({"a": p["a"], "b": p["b"], "ratio": r, "ratio_aperture": p["ratio"], "dev": r / p["ratio"] - 1})
    d = [x["dev"] for x in out]
    return {"pairs": out, "max_abs_dev": max(map(abs, d)), "rms_dev": float(np.sqrt(np.mean(np.square(d))))}


def run_setting(rob, epochs, setting):
    t0 = time.perf_counter()
    oids = [o for o, _, _ in epochs]
    E, meta = boxes(epochs, setting)
    ps = [J.fit_epoch(e, "single") for e in E]
    pp = [J.fit_epoch(e, "pair") for e in E]
    js = J.fit_joint(E, "single")
    jp = J.fit_joint(E, "pair")
    fp = J.fit_joint(E, "pair", free=False)
    out = {"epochs": meta}
    models = {"per_epoch_single": ps, "per_epoch_pair": pp}
    for name, f in models.items():
        s = J.summary_per_epoch(f)
        out[name] = {"chi2_red": s["chi2_red"], "chi2_red_each": s["chi2_red_each"], "dof": s["dof"],
                     "shift_px": [x["shift_px"] for x in f]}
    for name, f in (("joint_single", js), ("joint_pair", jp), ("fixed_pair", fp)):
        out[name] = {"chi2_red": f["chi2_red"], "dof": f["dof"], "offset_arcsec": f["offset_arcsec"],
                     "chi2_red_each": [x["chi2"] / (x["n"] - x["k_linear"]) for x in f["epochs"]]}
    # ratio stability: total flux (A + B) for every model; A and B alone for the pair models
    for name, fl in (("per_epoch_single", ps), ("per_epoch_pair", pp), ("joint_single", js["epochs"]),
                     ("joint_pair", jp["epochs"]), ("fixed_pair", fp["epochs"])):
        out[name]["ratios_total"] = ratios(rob, oids, [J.total_flux(f)[0] for f in fl])
        if "pair" in name:
            for k, lab in ((0, "A"), (1, "B")):
                out[name][f"ratios_{lab}_only"] = ratios(rob, oids, [f["beta"][k] for f in fl])
            out[name]["fB"] = [float(f["beta"][1] / (f["beta"][0] + f["beta"][1])) for f in fl]
    # single vs pair: does B improve the fit? (10 extra linear parameters in the joint fits)
    d = js["chi2"] - jp["chi2"]
    out["single_vs_pair_joint"] = {"delta_chi2": d, "extra_params": len(E),
                                   "delta_chi2_scaled_by_chi2_red": d / jp["chi2_red"],
                                   "note": "Under a correct model Delta chi2 ~ chi2 with 10 dof (mean 10). We scale by "
                                           "chi2_red because the ePSF does not fit the core (model error)."}
    # Fisher: per epoch (shift free / shift known) and joint (shared offset)
    fi = []
    for e, f, m in zip(E, pp, meta):
        a = J.fisher(e, f["beta"], f["shift_px"], "pair", True)
        b = J.fisher(e, f["beta"], f["shift_px"], "pair", False)
        sc = math.sqrt(max(1.0, f["chi2"] / (f["n"] - f["k_linear"] - 2)))
        fi.append({"epoch": m["epoch"], "corr_AB_shift_free": a["corr_AB"], "corr_AB_shift_known": b["corr_AB"],
                   "fB": a["fB"], "fB_err_shift_free": a["fB_err"], "fB_err_shift_free_chi2_scaled": a["fB_err"] * sc,
                   "fB_err_shift_known": b["fB_err"], "fB_err_shift_known_chi2_scaled": b["fB_err"] * sc})
    fj = J.fisher_joint(E, jp)
    out["fisher_per_epoch"] = fi
    out["fisher_joint"] = {"per_epoch": fj["per_epoch"], "offset_err_arcsec": fj["offset_err_arcsec"],
                           "fB_err_chi2_scaled": [x["fB_err"] * math.sqrt(max(1, jp["chi2_red"])) for x in fj["per_epoch"]]}
    # profile likelihood in f_B: free shift; fixed at the Gaia/WCS positions; and those positions moved
    # by +-WCS_JITTER_PX along A->B (fixed shift), to see how much the answer is just astrometry
    prof, prof_fixed, jit = [], [], []
    for e, f, m in zip(E, pp, meta):
        c_free, _ = J.profile_fraction(e, FGRID, True)
        c_fix, _ = J.profile_fraction(e, FGRID, False)
        sc = max(1.0, f["chi2"] / (f["n"] - f["k_linear"] - 2))
        prof.append(c_free)
        prof_fixed.append(c_fix)
        best = {}
        for dj in (-WCS_JITTER_PX, 0.0, WCS_JITTER_PX):
            u = np.array(m["unit_AB"]) * dj
            c, _ = J.profile_fraction(dict(e, comps=[(x + u[0], y + u[1]) for x, y in e["comps"]]), FGRID, False)
            best[f"{dj:+.2f}"] = float(FGRID[int(np.argmin(c))])
        jit.append({"epoch": m["epoch"], "argmin_fB_fixed_positions_by_offset_px": best,
                    "interval68_free_shift_scaled": J.interval(FGRID, c_free, sc),
                    "interval68_free_shift_unscaled": J.interval(FGRID, c_free, 1.0),
                    "interval68_fixed_positions_scaled": J.interval(FGRID, c_fix, sc),
                    "delta_chi2_free_shift_range": float(c_free.max() - c_free.min()),
                    "chi2_red_scale": sc})
    out["profile_fB"] = {"grid": FGRID.tolist(), "per_epoch": jit,
                         "summed_free_shift_delta_chi2": (np.sum(prof, 0) - np.sum(prof, 0).min()).tolist(),
                         "_curves_free": [c.tolist() for c in prof]}
    # profile in separation along the Gaia position angle, both fluxes free, shift free; summed over epochs
    sep = []
    for e, m in zip(E, meta):
        px_per_arcsec = m["sep_px"] / m["sep_arcsec"]
        c, fb = J.profile_separation(e, RHO_ARCSEC * px_per_arcsec, m["unit_AB"], True)
        sep.append(c)
    tot = np.sum(sep, 0)
    out["profile_separation"] = {"rho_arcsec": RHO_ARCSEC.tolist(), "summed_delta_chi2": (tot - tot.min()).tolist(),
                                 "best_rho_arcsec_summed": float(RHO_ARCSEC[int(np.argmin(tot))]),
                                 "best_rho_arcsec_each": [float(RHO_ARCSEC[int(np.argmin(c))]) for c in sep],
                                 "gaia_sep_arcsec": float(np.mean([m["sep_arcsec"] for m in meta]))}
    out["seconds"] = time.perf_counter() - t0
    return out, E, pp


def simulated(E, pp, rng):
    """SIMULATED epochs on the real ePSF, VARIANCE, positions and S/N: known single star (f_B = 0) or
    known pair (f_B = F_PAIR_TRUE), fitted with the pair model and a free shift. Optionally the truth
    is blurred by a JITTER_SIM_PX Gaussian (a PSF mismatch of the size the diagnostics suggest)."""
    from scipy.ndimage import gaussian_filter
    out = {}
    for blur in (0.0, JITTER_SIM_PX):
        for ftrue in (0.0, F_PAIR_TRUE):
            fb, chi = [], []
            for e, f in zip(E, pp):
                F = float(f["beta"][0] + f["beta"][1])
                sky = float(f["beta"][-1])
                s = f["shift_px"]
                psf_t = gaussian_filter(e["psf"], blur * e["ovs"], mode="constant") if blur else e["psf"]
                (xa, ya), (xb, yb) = e["comps"][:2]
                truth = F * ((1 - ftrue) * P.render(psf_t, e["ovs"], xa + s[0], ya + s[1], e["xx"], e["yy"])
                             + ftrue * P.render(psf_t, e["ovs"], xb + s[0], yb + s[1], e["xx"], e["yy"])) + sky
                if e["neigh"]:
                    truth += sum(f["beta"][2 + k] * P.render(e["psf"], e["ovs"], x + s[0], y + s[1], e["xx"], e["yy"])
                                 for k, (x, y) in enumerate(e["neigh"]))
                for _ in range(N_SIM):
                    sim = dict(e, img=truth + rng.normal(0, np.sqrt(e["var"])))
                    g = J.fit_epoch(sim, "pair")
                    fb.append(float(g["beta"][1] / (g["beta"][0] + g["beta"][1])))
                    chi.append(g["chi2"] / (g["n"] - g["k_linear"] - 2))
            key = f"{'single' if ftrue == 0 else 'pair'}_truth_psf_{'exact' if blur == 0 else 'blur0.1px'}"
            fb = np.array(fb)
            out[key] = {"label": "SIMULATED", "fB_true": ftrue, "n": int(fb.size), "fB_mean": float(fb.mean()),
                        "fB_std": float(fb.std(ddof=1)), "fB_p16_p84": np.percentile(fb, [16, 84]).tolist(),
                        "chi2_red_median": float(np.median(chi))}
    for blur in ("exact", "blur0.1px"):
        a, b = out[f"single_truth_psf_{blur}"], out[f"pair_truth_psf_{blur}"]
        out[f"separation_in_scatter_units_psf_{blur}"] = abs(b["fB_mean"] - a["fB_mean"]) / math.hypot(a["fB_std"], b["fB_std"])
    return out


def decide(res, sim):
    """The rule in the docstring, applied mechanically to the field_stars+sky_scale setting."""
    s = res["field_stars+sky_scale"]
    why = []
    excl = [p for p in s["profile_fB"]["per_epoch"]
            if p["interval68_free_shift_scaled"][0] > 0 and p["interval68_free_shift_scaled"][1] < 1]
    if len(excl) < len(s["profile_fB"]["per_epoch"]):
        why.append(f"f_B interval (errors scaled by chi2_red) excludes 0 and 1 in only {len(excl)} of "
                   f"{len(s['profile_fB']['per_epoch'])} epochs")
    moves = [max(p["argmin_fB_fixed_positions_by_offset_px"].values()) - min(p["argmin_fB_fixed_positions_by_offset_px"].values())
             for p in s["profile_fB"]["per_epoch"]]
    if max(moves) > 0.1:
        why.append(f"with positions fixed, moving them by +-{WCS_JITTER_PX} px moves the best f_B by up to {max(moves):.2f}")
    k = sim["separation_in_scatter_units_psf_blur0.1px"]
    if k < 3:
        why.append(f"SIMULATED single vs pair with a 0.1 px PSF mismatch differ by only {k:.1f} x their scatter")
    return {"separates_A_and_B": not why, "verdict": "SPHEREx does not separate RW Aur A and B" if why else
            "SPHEREx separates RW Aur A and B", "failed_criteria": why}


def figures(res):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    s = res["field_stars+sky_scale"]
    fig, ax = plt.subplots(1, 3, figsize=(11, 3.3))
    a = ax[0]
    for c, p in zip(s["profile_fB"]["_curves_free"], s["profile_fB"]["per_epoch"]):
        c = np.array(c)
        a.plot(FGRID, (c - c.min()) / p["chi2_red_scale"], color="#2a78d6", lw=0.8, alpha=0.7)
    a.axhline(1, color="#52514e", ls=":", lw=1)
    a.axvline(F_PAIR_TRUE, color="#eb6834", ls="--", lw=1)
    a.text(F_PAIR_TRUE + 0.02, a.get_ylim()[1] * 0.9, "Gaia G ratio", fontsize=6, color="#eb6834")
    a.set_xlabel("f_B = B / (A + B)", fontsize=8)
    a.set_ylabel("Delta chi2 / chi2_red (per epoch)", fontsize=8)
    a.set_title("Profile likelihood in the B fraction\n(10 epochs, shift free)", fontsize=8)
    a.tick_params(labelsize=7)
    a = ax[1]
    for key, col in (("published", "#8a8986"), ("field_stars+sky_scale", "#0b0b0b")):
        p = res[key]["profile_separation"]
        a.plot(p["rho_arcsec"], p["summed_delta_chi2"], marker="o", ms=3, lw=1.2, color=col, label=key)
    a.axvline(s["profile_separation"]["gaia_sep_arcsec"], color="#eb6834", ls="--", lw=1)
    a.text(s["profile_separation"]["gaia_sep_arcsec"] + 0.05, a.get_ylim()[1] * 0.9, "Gaia A-B", fontsize=6, color="#eb6834")
    a.set_xlabel("assumed A-B separation (arcsec; 1 px = 6.15\")", fontsize=8)
    a.set_ylabel("summed Delta chi2 (unscaled)", fontsize=8)
    a.set_title("Profile likelihood in separation\n(both fluxes free, shift free)", fontsize=8)
    a.legend(fontsize=6, frameon=False)
    a.tick_params(labelsize=7)
    a = ax[2]
    x = np.arange(len(s["epochs"]))
    for key, col, mk in (("per_epoch_single", "#2a78d6", "o"), ("joint_single", "#1baf7a", "s"),
                         ("per_epoch_pair", "#eb6834", "^"), ("joint_pair", "#9b59b6", "v")):
        a.plot(x, s[key]["chi2_red_each"], marker=mk, ms=4, lw=1, color=col,
               label=f"{key.replace('_', ' ')} (pooled {s[key]['chi2_red']:.2f})")
    a.axhline(1, color="#52514e", ls=":", lw=1)
    a.set_xticks(x, [m["epoch"][-9:] for m in s["epochs"]], rotation=60, fontsize=6)
    a.set_ylabel("reduced chi2", fontsize=8)
    a.set_title("Per-epoch vs joint fits\n(field stars + sky scale)", fontsize=8)
    a.legend(fontsize=5.5, frameon=False)
    a.tick_params(labelsize=7)
    fig.suptitle("RW Aur: can SPHEREx split A and B? (real pixels, EXPERIMENTAL)", fontsize=9)
    fig.tight_layout()
    fig.savefig(FIGS / "jointpsf_identifiability.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(1, 1, figsize=(6.5, 3.2))
    x = np.arange(8)
    for k, (key, lab, col, mk) in enumerate((("per_epoch_single", "ratios_total", "#2a78d6", "o"),
                                             ("joint_single", "ratios_total", "#1baf7a", "s"),
                                             ("joint_pair", "ratios_total", "#9b59b6", "v"),
                                             ("joint_pair", "ratios_A_only", "#eb6834", "^"),
                                             ("joint_pair", "ratios_B_only", "#d6a12a", "D"))):
        d = [p["dev"] * 100 for p in s[key][lab]["pairs"]]
        ax.plot(x + (k - 2) * 0.08, d, marker=mk, ms=4, lw=0, color=col,
                label=f"{key.replace('_', ' ')}, {lab.replace('ratios_', '').replace('_', ' ')}")
    ax.axhline(0, color="#52514e", lw=0.8)
    ax.set_yscale("symlog", linthresh=5)
    ax.set_xticks(x, [f"{p['a'][-9:]}\n{p['b'][-9:]}" for p in s["joint_pair"]["ratios_total"]["pairs"]], fontsize=5)
    ax.set_ylabel("ePSF ratio / aperture ratio - 1 (%)", fontsize=8)
    ax.set_title("RW Aur pair ratios: totals are stable, the A/B split is not (EXPERIMENTAL)", fontsize=8)
    ax.legend(fontsize=6, frameon=False, ncol=2)
    ax.tick_params(labelsize=7)
    fig.tight_layout()
    fig.savefig(FIGS / "jointpsf_ratios.png", dpi=150)
    plt.close(fig)


def main():
    t0 = time.perf_counter()
    rob = json.loads((EVID / "robustness.json").read_text())
    epochs = load(rob)
    res, keep = {}, {}
    for setting in ("published", "field_stars+sky_scale"):
        res[setting], E, pp = run_setting(rob, epochs, setting)
        keep[setting] = (E, pp)
        s = res[setting]
        print(setting, {k: round(s[k]["chi2_red"], 2) for k in
                        ("per_epoch_single", "joint_single", "per_epoch_pair", "joint_pair", "fixed_pair")})
    sim = simulated(*keep["published"], np.random.default_rng(SEED))
    print("SIMULATED", {k: (v if isinstance(v, float) else (round(v["fB_mean"], 3), round(v["fB_std"], 3)))
                        for k, v in sim.items()})
    dec = decide(res, sim)
    figures(res)
    for s in res.values():
        s["profile_fB"].pop("_curves_free")
    pub = json.loads((EVID / "epsf_check.json").read_text())["targets"]["rw_aur"]["fits"]
    report = {
        "status": "EXPERIMENTAL - R&D only, not used by any published number",
        "settings": {"fit_box_px": 2 * J.FIT_HALF + 1, "background": "constant per epoch", "weights": "1/VARIANCE",
                     "max_shift_px": J.MAX_SHIFT_PX, "fB_grid": FGRID.tolist(), "rho_grid_arcsec": RHO_ARCSEC.tolist(),
                     "wcs_jitter_px": WCS_JITTER_PX, "n_sim_per_epoch": N_SIM, "seed": SEED,
                     "fB_true_SIMULATED": F_PAIR_TRUE, "psf_mismatch_SIMULATED_px": JITTER_SIM_PX,
                     "gaia": "RW_AUR_GAIA in reproduce_epsf.py (DR3, propagated to each epoch)",
                     "dof_note": "Our chi2_red subtracts the shift parameters from the dof; epsf_check.json does not, "
                                 "so ours are ~2.5% higher for the same fit."},
        "published_per_epoch_chi2_red_for_reference": {k: v["chi2_red"] for k, v in pub.items() if v.get("ok")},
        "results": res,
        "simulated_identifiability": sim,
        "decision_rule": __doc__.split("Decision rule (fixed before running):")[1].strip(),
        "decision": dec,
        "benchmark": {"seconds": time.perf_counter() - t0,
                      "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024},
    }
    report["interpretation"] = interpretation(res, sim, dec)
    OUT.write_text(json.dumps(report, indent=1, default=float) + "\n")
    print(json.dumps(dec, indent=1))
    print(report["interpretation"])
    print("wrote", OUT, report["benchmark"])


def interpretation(res, sim, dec):
    s, pub = res["field_stars+sky_scale"], res["published"]
    fi = s["fisher_per_epoch"]
    cf = [f["corr_AB_shift_free"] for f in fi]
    ck = [f["corr_AB_shift_known"] for f in fi]
    fb = s["per_epoch_pair"]["fB"]
    jit = [p["argmin_fB_fixed_positions_by_offset_px"] for p in s["profile_fB"]["per_epoch"]]
    sv = s["single_vs_pair_joint"]
    se = s["profile_separation"]
    ex, bl = sim["single_truth_psf_exact"], sim["single_truth_psf_blur0.1px"]
    pe, pb = sim["pair_truth_psf_exact"], sim["pair_truth_psf_blur0.1px"]
    return (
        f"Plain answer: {dec['verdict']}. RW Aur B sits {s['epochs'][0]['sep_px']:.2f} px "
        f"({se['gaia_sep_arcsec']:.2f}\") from A, a fifth of the ~1.3 px PSF core. "
        f"Identifiability: with the position free the A and B fluxes are correlated at "
        f"{min(cf):.3f} to {max(cf):.3f} per epoch ({min(ck):.2f} to {max(ck):.2f} even with the position "
        f"known); only A + B is measured. The formal f_B errors look small "
        f"({min(f['fB_err_shift_free_chi2_scaled'] for f in fi):.2f}-{max(f['fB_err_shift_free_chi2_scaled'] for f in fi):.2f}) "
        f"because RW Aur is very bright, but the best f_B per epoch runs from {min(fb):.2f} to {max(fb):.2f} "
        f"(physical range 0-1), and with the positions fixed, moving them by +-{WCS_JITTER_PX} px along the "
        f"A-B line moves the best f_B to {max(j[f"{WCS_JITTER_PX:+.2f}"] for j in jit):.1f} one way and to "
        f">= {min(j[f"{-WCS_JITTER_PX:+.2f}"] for j in jit):.2f} the other way, in every epoch: the 'split' is set by astrometry at the 0.15 px level, not by the light. "
        f"Adding B lowers the joint chi2 by {sv['delta_chi2']:.0f} ({sv['delta_chi2_scaled_by_chi2_red']:.0f} after "
        f"scaling by chi2_red) for {sv['extra_params']} parameters, but SIMULATED epochs show why that is not a "
        f"detection of B: a single star fitted with the pair model gives f_B = {ex['fB_mean']:.2f} +- {ex['fB_std']:.2f} "
        f"(exact PSF) and {bl['fB_mean']:.2f} +- {bl['fB_std']:.2f} (PSF off by a 0.1 px blur), a true pair "
        f"(f_B = {F_PAIR_TRUE}) gives {pe['fB_mean']:.2f} +- {pe['fB_std']:.2f} and {pb['fB_mean']:.2f} +- {pb['fB_std']:.2f}; "
        f"the two cases differ by {sim['separation_in_scatter_units_psf_blur0.1px']:.1f} x their scatter "
        f"(n = {ex['n']} per case). The second component mostly soaks up ePSF shape error. "
        f"The separation profile is not a robust measurement either: summed over epochs it is lowest at "
        f"{se['best_rho_arcsec_summed']:.1f}\" (Gaia {se['gaia_sep_arcsec']:.2f}\") with field stars fitted, "
        f"but per epoch the minimum runs over {min(se['best_rho_arcsec_each']):.1f}-{max(se['best_rho_arcsec_each']):.1f}\" "
        f"and without field stars the summed minimum is at the {pub['profile_separation']['best_rho_arcsec_summed']:.1f}\" grid edge. "
        f"Joint vs per-epoch: one sky offset shared by all epochs fits worse "
        f"(chi2_red {s['joint_single']['chi2_red']:.2f} vs {s['per_epoch_single']['chi2_red']:.2f} with field stars; "
        f"{pub['joint_single']['chi2_red']:.2f} vs {pub['per_epoch_single']['chi2_red']:.2f} as published), so the "
        f"per-epoch position offsets are real (WCS error between visits), not noise, and a joint position "
        f"buys nothing. Ratio stability: the total-flux (A + B) ratios of the 8 published pairs agree with the "
        f"aperture ratios to <= {100 * s['per_epoch_single']['ratios_total']['max_abs_dev']:.1f}% (per-epoch) and "
        f"<= {100 * s['joint_pair']['ratios_total']['max_abs_dev']:.1f}% (joint pair) in every model, while "
        f"A-only and B-only ratios move by up to {100 * s['per_epoch_pair']['ratios_A_only']['max_abs_dev']:.0f}% and "
        f"{100 * s['per_epoch_pair']['ratios_B_only']['max_abs_dev']:.0f}% (per-epoch pair) or "
        f"{100 * s['joint_pair']['ratios_A_only']['max_abs_dev']:.0f}% and {100 * s['joint_pair']['ratios_B_only']['max_abs_dev']:.0f}% "
        f"(joint pair). So: the published blended (A + B) ratios stand; any statement about which component "
        f"varied needs data that resolve the pair. Nothing published changes.")


if __name__ == "__main__":
    main()
