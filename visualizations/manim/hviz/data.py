"""Load the HIPPARCHUS evidence files and check units and fields before any scene uses them.

Every number on screen comes from here. We read the JSON as published, check
the fields we rely on (names carry their unit: *_um, *_arcsec, mjd, *_deg),
and refuse to draw if something is missing or out of a physical range.
"""

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
EVID = ROOT / "submission" / "evidence"
PIXELS = HERE / "data" / "rw_aur_pixels.json"
PAIR = HERE / "data" / "rw_aur_pair.json"


class EvidenceError(ValueError):
    pass


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@lru_cache(None)
def load(name):
    p = EVID / name
    if not p.exists():
        raise EvidenceError(f"missing evidence file {p}")
    return json.loads(p.read_text())


def get(d, path):
    """d['a']['b'][0] as get(d, 'a.b.0'), with a readable error."""
    cur = d
    for k in path.split("."):
        try:
            cur = cur[int(k)] if isinstance(cur, list) else cur[k]
        except (KeyError, IndexError, ValueError, TypeError):
            raise EvidenceError(f"field {path!r} not found") from None
    return cur


# We only check plausible physical ranges; the backend tests check the science.
_RANGES = {
    "_um": (0.7, 5.2),           # SPHEREx covers 0.75-5.0 um
    "bandwidth_um": (0.005, 0.2),
    "dlambda_um": (0.0, 4.5),
    "mjd": (60000.0, 62000.0),   # 2023-2028
    "mjd_mid": (60000.0, 62000.0),
    "ra": (0.0, 360.0),
    "dec": (-90.0, 90.0),
}


def check_units(rec, where=""):
    for k, v in rec.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        # An exact field name wins over the generic unit suffix.
        rng = _RANGES.get(k) or next((r for s, r in _RANGES.items()
                                      if s.startswith("_") and k.endswith(s)), None)
        if rng and (math.isnan(v) or not rng[0] <= v <= rng[1]):
            raise EvidenceError(f"{where}{k}={v} outside [{rng[0]}, {rng[1]}]")
    return rec


def require(rec, fields, where=""):
    for f in fields:
        if f not in rec or rec[f] is None:
            raise EvidenceError(f"{where}missing field {f!r}")
    return check_units(rec, where)


# ---------------- per-topic accessors ----------------

TARGET_FILES = {"rw_aur": "rw_aur_spherex-d1.json", "barnard": "barnard_spherex-d6.json",
                "wise0855": "wise0855_spherex-d6.json"}
TARGET_NAMES = {"rw_aur": "RW Aur", "barnard": "Barnard's Star", "wise0855": "WISE 0855"}


def target(tid):
    d = load(TARGET_FILES[tid])
    require(d, ["ra", "dec", "n_epochs", "n_usable", "epochs", "comparisons"], f"{tid}: ")
    for e in d["epochs"]:
        require(e, ["obs_id", "mjd", "wavelength_um", "bandwidth_um", "usable"], f"{tid} epoch: ")
    for c in d["comparisons"]:
        require(c, ["a", "b", "lambda_a_um", "lambda_b_um", "flux_ratio", "significance"], f"{tid} pair: ")
        for side in ("flux_a", "flux_b"):
            f = c[side]
            # A faint star can measure below zero after sky subtraction; the error can't.
            if not (math.isfinite(f["flux"]) and f["flux_err"] > 0):
                raise EvidenceError(f"{tid}: bad flux or non-positive error in {side}")
    return d


def compat():
    d = load("compat_check.json")
    lim = get(d, "overlap_at_rule_limit")
    if not math.isclose(lim["tophat"], 0.5, abs_tol=1e-9) or not 0.5 < lim["gaussian"] < 0.6:
        raise EvidenceError("unexpected overlap at rule limit")
    for tid, g in d["graphs"].items():
        for n in g["nodes"]:
            require(n, ["id", "mjd", "wavelength_um", "bandwidth_um", "usable"], f"graph {tid}: ")
        for e in g["edges"]:
            require(e, ["a", "b", "dlambda_um", "overlap_tophat", "overlap_gaussian"], f"graph {tid}: ")
    return d


def robustness():
    d = load("robustness.json")
    for tid in ("rw_aur", "wise0855"):
        for c in get(d, f"targets.{tid}.claims"):
            require(c, ["claim", "verdict", "n_checks", "n_holding", "settings_grid",
                        "leave_one_pair_out", "wavelength_rule"], f"robustness {tid}: ")
    return d


def motion():
    d = load("motion_check.json")
    for e in d["exposures"]:
        require(e, ["obs_id", "mjd_mid"], "motion: ")
        check_units(e["horizons_spherex"], "motion horizons: ")
        if e.get("measured"):
            check_units({k: e["measured"][k] for k in ("ra", "dec")}, "motion measured: ")
            r = math.hypot(e["measured"]["resid_ra_cosdec_arcsec"], e["measured"]["resid_dec_arcsec"])
            if r > 30:
                raise EvidenceError(f"residual {r} arcsec is not plausible for a matched detection")
    return d


def epsf():
    d = load("epsf_check.json")
    if "EXPERIMENTAL" not in d["status"]:
        raise EvidenceError("ePSF check is expected to be marked EXPERIMENTAL")
    return d


def pixels():
    """Real RW Aur pixels extracted by tools/extract_pixels.py, checked against the evidence."""
    if not PIXELS.exists():
        return None
    d = json.loads(PIXELS.read_text())
    ev = {e["obs_id"]: e for e in target("rw_aur")["epochs"]}[d["obs_id"]]
    if ev["provenance"]["cutout"]["sha256"] != d["cutout_sha256"]:
        raise EvidenceError("pixel extract does not come from the evidence cutout")
    cache = ROOT / "data" / "cache" / d["cutout_file"]
    # If the FITS cache is here we re-hash the file too; on a fresh clone it isn't.
    if cache.exists() and sha256(cache) != d["cutout_sha256"]:
        raise EvidenceError("cached cutout changed since the extract")
    return d


def pair():
    """The largest-ratio RW Aur pair (tools/extract_pair.py), checked against the evidence."""
    if not PAIR.exists():
        return None
    d = json.loads(PAIR.read_text())
    ev = target("rw_aur")
    top = max(ev["comparisons"], key=lambda c: c["flux_ratio"])
    if (d["a"], d["b"]) != (top["a"], top["b"]):
        raise EvidenceError("pair extract is not the largest-ratio published pair")
    epochs = {e["obs_id"]: e for e in ev["epochs"]}
    for oid in (d["a"], d["b"]):
        if epochs[oid]["provenance"]["cutout"]["sha256"] != d["cutout_sha256"][oid]:
            raise EvidenceError(f"pair extract for {oid} does not come from the evidence cutout")
        cache = ROOT / "data" / "cache" / d["cutout_file"][oid]
        if cache.exists() and sha256(cache) != d["cutout_sha256"][oid]:
            raise EvidenceError(f"cached cutout {oid} changed since the extract")
    for k, side in (("a", "flux_a"), ("b", "flux_b")):
        if not math.isclose(d["flux"][k], top[side]["flux"], rel_tol=1e-9):
            raise EvidenceError(f"pair extract flux {k} differs from the evidence")
    return d


# ---------------- spectral overlap (same formulas as backend/hipparchus/compat.py) ----

FWHM_TO_SIGMA = 1.0 / (2.0 * math.sqrt(2.0 * math.log(2.0)))


def overlap(l1, w1, l2, w2, shape="gaussian"):
    if shape == "tophat":
        lo, hi = max(l1 - w1 / 2, l2 - w2 / 2), min(l1 + w1 / 2, l2 + w2 / 2)
        return max(0.0, hi - lo) / max(w1, w2)
    s1, s2 = w1 * FWHM_TO_SIGMA, w2 * FWHM_TO_SIGMA
    lo, hi = min(l1 - 8 * s1, l2 - 8 * s2), max(l1 + 8 * s1, l2 + 8 * s2)
    n = 4000
    step = (hi - lo) / n
    tot = 0.0
    for i in range(n):
        x = lo + (i + 0.5) * step
        g1 = math.exp(-0.5 * ((x - l1) / s1) ** 2) / (s1 * math.sqrt(2 * math.pi))
        g2 = math.exp(-0.5 * ((x - l2) / s2) ** 2) / (s2 * math.sqrt(2 * math.pi))
        tot += min(g1, g2)
    return tot * step


def evidence_files_used(names):
    return [{"file": f"submission/evidence/{n}", "sha256": sha256(EVID / n)} for n in names]
