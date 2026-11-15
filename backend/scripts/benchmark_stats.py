"""Second look at the benchmark: correlated pairs, false positives, and the calibration floor.

run_benchmark.py scores every object with the detection rule fixed before the run
(formal |significance| >= 5). This script does not change that rule or any score. It reads
the cached per-object results and adds what the Wilson intervals there cannot give:

* Pairs of one object share exposures, so pair-level rates are not binomial. We resample
  objects (cluster bootstrap) instead of pairs to get honest intervals.
* For every false-positive pair we list the exposures involved, to see whether one bad
  exposure explains several flagged pairs.
* A SECONDARY, clearly labelled check: the same pairs judged with the 12.5% calibration
  floor that robustness.json measured on RW Aur field stars before this benchmark existed.
  It is reported next to the primary result, never instead of it.

Run after run_benchmark.py:  python scripts/benchmark_stats.py
Writes submission/benchmark/stats.json.
"""
from __future__ import annotations

import json
import math
import random
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "submission" / "benchmark"
CACHE = ROOT / "data" / "cache" / "benchmark" / "results"
SEED = 20261117
N_BOOT = 5000


def pairs_of(oid: str) -> list[dict] | None:
    f = CACHE / f"{oid}.json"
    if not f.exists():
        return None
    return json.loads(f.read_text()).get("comparisons", [])


def floor_sig(c: dict, floor: float) -> float:
    """Significance with a fractional calibration floor on the earlier flux, as in reproduce_robustness.py."""
    r = c.get("flux_ratio")
    d, e = c["delta_flux"], c["delta_flux_err"]
    if not r or r <= 0 or r == 1:
        return c["significance"]
    fa = d / (r - 1)                       # earlier flux, from delta = fa * (r - 1)
    return d / math.hypot(e, floor * abs(fa))


def cluster_boot(groups: list[list], stat, n=N_BOOT, seed=SEED) -> dict:
    """95% percentile interval of stat over objects resampled with replacement."""
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        sample = [g for _ in groups for g in [groups[rng.randrange(len(groups))]]]
        v = stat(sample)
        if v is not None:
            vals.append(v)
    vals.sort()
    if not vals:
        return {"lo": None, "hi": None}
    return {"lo": vals[int(0.025 * len(vals))], "hi": vals[int(0.975 * len(vals)) - 1], "n_boot": len(vals)}


def main() -> dict:
    res = json.loads((BENCH / "results.json").read_text())
    man = json.loads((BENCH / "manifest.json").read_text())
    floor = json.loads((ROOT / "submission" / "evidence" / "robustness.json").read_text())
    floor = next(v for v in _walk(floor, "systematic_floor") if isinstance(v, (int, float)))
    objs = {o["id"]: o for o in man["objects"]}
    out = {"label": "REAL SPHEREx data; secondary analysis of run_benchmark.py results, detection rule unchanged",
           "detection_rule": "formal |significance| >= 5 (fixed before the run)",
           "calibration_floor": floor, "bootstrap": {"resample": "objects", "n": N_BOOT, "seed": SEED},
           "splits": {}}
    for split in ("held_out", "calibration", "all"):
        sel = [o for o in objs.values() if split == "all" or o["split"] == split]
        stable, variable = [], []
        for o in sel:
            ps = pairs_of(o["id"])
            if not ps:
                continue
            if o["category"] == "stable_control":
                stable.append((o["id"], ps))
            elif o["category"] == "known_variable":
                variable.append((o["id"], ps))
        frac = lambda g: (sum(c["changed"] for _, ps in g for c in ps) / n) if (n := sum(len(ps) for _, ps in g)) else None  # noqa: E731
        bias = lambda g: statistics.median(c["flux_ratio"] - 1 for _, ps in g for c in ps) if g else None  # noqa: E731
        fp_pairs = [{"object": oid, "a": c["a"], "b": c["b"], "flux_ratio": c["flux_ratio"],
                     "significance": c["significance"], "significance_with_floor": floor_sig(c, floor),
                     "dlambda_nm": 1000 * abs(c["lambda_b_um"] - c["lambda_a_um"])}
                    for oid, ps in stable for c in ps if c["changed"]]
        exps = [e for p in fp_pairs for e in (p["a"], p["b"])]
        s = {
            "stable_objects_with_pairs": [oid for oid, _ in stable],
            "stable_objects_flagged": sorted({p["object"] for p in fp_pairs}),
            "pair_fpr": {"k": len(fp_pairs), "n": sum(len(ps) for _, ps in stable), "rate": frac(stable),
                         "ci95_cluster_bootstrap": cluster_boot(stable, frac) if stable else None},
            "false_positive_pairs": fp_pairs,
            "exposures_in_fp_pairs": {"n_pairs": len(fp_pairs), "n_distinct_exposures": len(set(exps)),
                                      "repeated": sorted({e for e in exps if exps.count(e) > 1})},
            "photometric_bias_stable": {"median_ratio_minus_1": bias(stable),
                                        "ci95_cluster_bootstrap": cluster_boot(stable, bias) if stable else None},
            "variable_pair_detection": {"k": sum(c["changed"] for _, ps in variable for c in ps),
                                        "n": sum(len(ps) for _, ps in variable), "rate": frac(variable),
                                        "ci95_cluster_bootstrap": cluster_boot(variable, frac) if variable else None},
            "secondary_with_floor": {
                "what": f"SECONDARY: same pairs, |significance| >= 5 after adding the {floor:.3f} calibration floor",
                "stable_pairs_flagged": sum(abs(floor_sig(c, floor)) >= 5 for _, ps in stable for c in ps),
                "stable_objects_flagged": sorted({oid for oid, ps in stable for c in ps if abs(floor_sig(c, floor)) >= 5}),
                "variable_objects_detected": sorted({oid for oid, ps in variable for c in ps if abs(floor_sig(c, floor)) >= 5}),
                "variable_objects_with_pairs": [oid for oid, _ in variable],
            },
        }
        out["splits"][split] = s
    out["primary_metrics_held_out"] = res["metrics"]["held_out"]
    (BENCH / "stats.json").write_text(json.dumps(out, indent=1, default=float) + "\n")
    return out


def _walk(x, key):
    if isinstance(x, dict):
        for k, v in x.items():
            if k == key:
                yield v
            yield from _walk(v, key)
    elif isinstance(x, list):
        for v in x:
            yield from _walk(v, key)


if __name__ == "__main__":
    o = main()
    for sp, s in o["splits"].items():
        print(sp, "pairFPR", s["pair_fpr"]["k"], "/", s["pair_fpr"]["n"], s["pair_fpr"]["ci95_cluster_bootstrap"],
              "| flagged stable", s["stable_objects_flagged"], "of", len(s["stable_objects_with_pairs"]),
              "| floor:", s["secondary_with_floor"]["stable_objects_flagged"],
              s["secondary_with_floor"]["variable_objects_detected"])
