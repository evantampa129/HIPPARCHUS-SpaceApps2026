"""Run the audit and stability checks on the three demonstration targets.

Writes submission/evidence/robustness.json. Uses the cached real SPHEREx
cutouts (run reproduce_evidence.py first on a fresh checkout). Compares the
production numbers with the published evidence files, so any change in a
measurement shows up here.
"""

import argparse
import json
import resource
import sys
import time
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hipparchus import api, archive, compare as C, pipeline, robustness as R, validation  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "submission" / "evidence"
OUT = EVID / "robustness.json"


def cached_query(ra, dec, **_):
    """The complete archive listing saved in data/manifests (committed to git).

    The audit must run on exactly the exposures behind the published results,
    and IRSA sometimes answers for only one of the two releases ("partial").
    """
    m = json.loads(archive._manifest_path(ra, dec).read_text())
    m["archive_status"] = "cached"
    return m


archive.query = cached_query


# The claim each target's published result makes, as a test on a set of pairs.
def claim_rw(rows):
    return bool(rows) and all(r["ratio"] > 1 for r in rows) and max(r["sig"] for r in rows) >= C.DETECTION_SIGMA


def claim_none(rows):
    return all(abs(r["sig"]) < C.DETECTION_SIGMA for r in rows)


def claim_rw_strong(rows):
    return any(r["ratio"] >= 1.5 and r["sig"] >= C.DETECTION_SIGMA for r in rows)


# Both RW Aur statements appear in the published text, so both are tested.
CLAIMS = {"rw_aur": [("brightened by at least x1.5 at >= 5 sigma in some pair", claim_rw_strong),
                     ("every valid pair brighter later, at least one >= 5 sigma", claim_rw)],
          "wise0855": [("no pair changes by >= 5 sigma", claim_none)]}


def published(tid, detector):
    p = EVID / f"{tid}_{detector.lower()}.json"
    d = json.loads(p.read_text())
    return {(c["a"], c["b"]): c for c in d.get("comparisons", d.get("result", {}).get("comparisons", []))}


def pair_rows(comps, ep):
    """Production numbers plus ensemble, systematic error, PSF and wavelength info per pair."""
    rows = []
    for c in comps:
        A, a, b = c["_arrays"], ep[c["a"]], ep[c["b"]]
        ens = R.ensemble(A, a.x, a.y)
        rows.append({"a": c["a"], "b": c["b"], "dt_days": c["dt_days"],
                     "dlambda_um": abs(c["lambda_b_um"] - c["lambda_a_um"]),
                     "half_channel_um": 0.5 * min(a.bandwidth_um, b.bandwidth_um),
                     "fwhm_px": [validation.fwhm_px(a), validation.fwhm_px(b)],
                     "ratio": c["flux_ratio"], "sig": c["significance"],
                     "fa": c["flux_a"]["flux"], "fb": c["flux_b"]["flux"], "err": c["delta_flux_err"],
                     "control": c["control_star"] and c["control_star"]["ratio"],
                     "ensemble": {k: v for k, v in ens.items() if k != "ratios"},
                     "ensemble_ratios": ens.get("ratios", []),
                     "max_abs_z": c["max_abs_z"]})
    floor = R.systematic_floor(rows)
    for r in rows:
        # Under "no change" both epochs carry the flux fa, and a calibration
        # error of `floor` (fractional) moves epoch b by floor * fa.
        r["sig_with_systematics"] = (None if floor is None else
                                     (r["fb"] - r["fa"]) / float(np.hypot(r["err"], floor * r["fa"])))
        e = r["ensemble"]["median"]
        r["ratio_over_ensemble"] = r["ratio"] / e if e else None
    return rows, floor


def dlambda_variants(epochs, claims):
    """Re-pair the usable epochs with a stricter and a looser wavelength rule."""
    out = {}
    usable = [e for e in epochs if e.usable]
    for frac in (0.25, 0.5, 0.75):
        C.MAX_DLAMBDA_FRACTION = frac
        rows = []
        for a, b in combinations(usable, 2):
            v = C.compatibility(a, b)
            if v.comparable and v.kind == "comparison":
                c = C.compare(a, b)
                if c["verdict"]["comparable"]:
                    rows.append({"ratio": c["flux_ratio"], "sig": c["significance"]})
        out[str(frac)] = {"n_pairs": len(rows), "claim_holds": {txt: fn(rows) for txt, fn in claims},
                          "max_abs_sig": max((abs(r["sig"]) for r in rows), default=None)}
    C.MAX_DLAMBDA_FRACTION = 0.5
    return out


def main(wavelength_source: str | None = None, out: Path = OUT):
    t_all = time.perf_counter()
    report = {"settings": {"wavelength_source": wavelength_source or "wcs",
                           "apertures_px": R.APERTURES, "annuli_px": R.ANNULI, "masks": R.MASKS,
                           "calibrations": R.CALIBRATIONS, "detection_sigma": C.DETECTION_SIGMA,
                           "ensemble": {"min_snr": R.ENSEMBLE_MIN_SNR, "min_sep_px": R.ENSEMBLE_MIN_SEP,
                                        "isolation_px": R.ISOLATION_PX},
                           "rule": "robust = claim holds in every valid configuration; sensitive = in at "
                                   "least half; inconclusive = fewer than half. Not a probability."},
              "simulations": {"reprojection_noise": R.reprojection_noise_mc(300),
                              "psf_width_change": [R.psf_mismatch_bias(fa, fb, r)
                                                   for fa, fb in ((1.3, 1.8), (1.5, 2.0)) for r in R.APERTURES]},
              "targets": {}}
    for t in api.TARGETS:
        t0 = time.perf_counter()
        res = pipeline.analyze(t["ra"], t["dec"], t["detector"], wavelength_source=wavelength_source)
        secs = time.perf_counter() - t0
        ep = {e.obs_id: e for e in res["_epochs"]}
        comps = res["comparisons"]
        pub = published(t["id"], t["detector"])
        # Agreement with the published evidence (made before this audit).
        diffs = []
        for c in comps:
            p = pub.get((c["a"], c["b"]))
            diffs.append(None if p is None else {
                "ratio": abs(c["flux_ratio"] - p["flux_ratio"]), "sig": abs(c["significance"] - p["significance"]),
                "max_abs_z_old": p.get("max_abs_z"), "max_abs_z_new": c["max_abs_z"]})
        agree = {"n_published": len(pub), "n_now": len(comps),
                 "same_pairs": sorted(pub) == sorted((c["a"], c["b"]) for c in comps),
                 "max_ratio_change": max((d["ratio"] for d in diffs if d), default=None),
                 "max_sig_change": max((d["sig"] for d in diffs if d), default=None),
                 "max_abs_z_old_new": [(d["max_abs_z_old"], d["max_abs_z_new"]) for d in diffs if d],
                 "refused_pairs": res["refused_pairs"]}
        entry = {"analysis_seconds": secs, "agreement_with_published": agree,
                 "trials": R.trials(len(comps)) if comps else None}
        if comps:
            rows, floor = pair_rows(comps, ep)
            entry["pairs"] = rows
            entry["systematic_floor"] = floor
            claims = CLAIMS.get(t["id"], [])
            # Stability grid: every configuration across all pairs.
            grid = defaultdict(list)
            for c in comps:
                for r in R.stability(c["_arrays"], ep[c["a"]].x, ep[c["a"]].y):
                    if r["valid"]:
                        k = (r["r_ap"], tuple(r["annulus"]), r["mask"], r["calibration"])
                        grid[k].append(r)
            configs = []
            for k, rs in grid.items():
                # A configuration that loses pairs (bad pixels in a bigger
                # aperture or a grown mask) is shown but not used for the verdict.
                full = len(rs) == len(comps)
                configs.append({"r_ap": k[0], "annulus": list(k[1]), "mask": k[2], "calibration": k[3],
                                "n_pairs": len(rs), "complete": full,
                                "strongest_ratio": max(r["ratio"] for r in rs) if rs else None,
                                "max_abs_sig": max(abs(r["sig"]) for r in rs) if rs else None,
                                "claim_holds": {txt: fn(rs) for txt, fn in claims} if full else None})
            entry["stability"] = configs
            dl = dlambda_variants(res["_epochs"], claims)
            entry["wavelength_rule_variants"] = dl
            entry["claims"] = []
            for txt, fn in claims:
                held = [c["claim_holds"][txt] for c in configs if c["claim_holds"] is not None]
                loo = [fn([r for j, r in enumerate(rows) if j != i]) for i in range(len(rows))] if len(rows) > 1 else []
                sys_ok = (fn([{"ratio": r["ratio"], "sig": r["sig_with_systematics"]} for r in rows])
                          if floor is not None else None)
                dls = [v["claim_holds"][txt] for v in dl.values() if v["n_pairs"]]
                checks = held + loo + ([sys_ok] if sys_ok is not None else []) + dls
                entry["claims"].append({
                    "claim": txt, "verdict": R.classify(txt, checks),
                    "n_checks": len(checks), "n_holding": sum(checks),
                    "settings_grid": [sum(held), len(held)], "leave_one_pair_out": [sum(loo), len(loo)],
                    "with_systematic_floor": sys_ok, "wavelength_rule": [sum(dls), len(dls)],
                    "failing_settings": [(c["r_ap"], c["annulus"], c["mask"], c["calibration"])
                                         for c in configs if c["claim_holds"] and not c["claim_holds"][txt]]})
            entry["verdict"] = "; ".join(f'{c["claim"]}: {c["verdict"]}' for c in entry["claims"])
        else:
            entry["verdict"] = "refused (no usable epoch; not a choice of analysis settings)"
        report["targets"][t["id"]] = entry
        print(t["id"], entry["verdict"],
              "| floor", entry.get("systematic_floor"), "| agree", agree["same_pairs"],
              agree["max_ratio_change"], agree["max_sig_change"], f"| {secs:.1f}s")
    report["benchmark"] = {"total_seconds": time.perf_counter() - t_all,
                           "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024}
    out.write_text(json.dumps(report, indent=1, default=lambda o: None if o is None else float(o)) + "\n")
    print("wrote", out, report["benchmark"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    # Default "wcs" rewrites the published robustness.json; another source must
    # go to another file (--out), so a trial run never overwrites published evidence.
    ap.add_argument("--wavelength-source", default="wcs", choices=("wcs", "wcs_nosip", "cwave"))
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    if a.wavelength_source != "wcs" and a.out is None:
        ap.error("--out is required with a non-default --wavelength-source")
    main(a.wavelength_source, a.out or OUT)
