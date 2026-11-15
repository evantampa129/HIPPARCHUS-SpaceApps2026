"""One registry for every number we quote in public.

Each claim is computed from the evidence files, formatted once, and listed with
the outputs that quote it (README, Judge Mode, report, portal texts). The drift
test rebuilds every claim and checks that each listed output still contains the
exact string, so a re-run that changes a number cannot leave a stale copy
somewhere else.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EV = ROOT / "submission" / "evidence"

DOIS = {"DR1": "10.26131/IRSA678", "QR3": "10.26131/IRSA662"}

# Output files a claim can be quoted in, by short name.
CHANNELS = {
    "readme": "README.md",
    "site": "docs/index.html",
    "report": "report/HIPPARCHUS_AETHENOVA_FINAL.tex",
    "portal": "submission/portal_texts.md",
}


def _load(name: str) -> dict:
    return json.loads((EV / name).read_text())


def _sha(name: str) -> str:
    return hashlib.sha256((EV / name).read_bytes()).hexdigest()


def _rw_best(ev):
    return max(ev["comparisons"], key=lambda c: c["flux_ratio"])


def _null_scatter(v):
    return v["all_targets"]["null_test"]["std"]


def _inj(v, snr):
    return next(r["recovered_fraction"] for r in v["all_targets"]["injection_SIMULATED"]
                if r["snr_injected"] == snr)


# We keep the claim table as plain data: (id, status, evidence file, how to get
# the value, how to print it, channels, claim text, caveat). The formatter is
# the single place where rounding happens.
SPEC = [
    ("rw_aur.flux_ratio", "validated_real_observation", "rw_aur_spherex-d1.json",
     lambda e: _rw_best(e)["flux_ratio"], lambda x: f"{x:.2f}",
     ["readme", "site", "report", "portal"],
     "RW Aur is about 2.56 times brighter at 0.76 µm about a year later (largest ratio among the compared pairs).",
     "RW Aur A+B is unresolved by SPHEREx; ratio includes both components."),
    ("rw_aur.formal_sigma", "validated_real_observation", "rw_aur_spherex-d1.json",
     lambda e: _rw_best(e)["significance"], lambda x: f"{x:.0f}",
     ["readme", "site", "report", "portal"],
     "Formal significance of the largest change.",
     "Formal only; about 12σ once a 12.5% calibration floor is added."),
    ("rw_aur.valid_pairs", "validated_real_observation", "rw_aur_spherex-d1.json",
     lambda e: len(e["comparisons"]), lambda x: f"{x}",
     ["readme", "site", "report", "portal"],
     "Number of RW Aur pairs that pass every check.", ""),
    ("rw_aur.all_pairs", "validated_real_observation", "rw_aur_spherex-d1.json",
     lambda e: e["n_epochs"] * (e["n_epochs"] - 1) // 2, lambda x: f"{x}",
     ["readme", "site", "report", "portal"],
     "Number of RW Aur epoch pairs considered.", ""),
    ("barnard.epochs", "validated_real_observation", "barnard_spherex-d6.json",
     lambda e: e["n_epochs"], lambda x: f"{x}",
     ["readme", "site", "report", "portal"],
     "Barnard's Star epochs found; none usable (saturation flags), so the comparison is refused.", ""),
    ("barnard.usable", "validated_real_observation", "barnard_spherex-d6.json",
     lambda e: e["n_usable"], lambda x: f"{x}", [],
     "Usable Barnard's Star epochs.", ""),
    ("wise0855.valid_pairs", "validated_real_observation", "wise0855_spherex-d6.json",
     lambda e: len(e["comparisons"]), lambda x: f"{x}",
     ["readme", "site", "report", "portal"],
     "WISE 0855 valid pairs.", "Low sensitivity: cannot prove constancy."),
    ("wise0855.max_sigma", "validated_real_observation", "wise0855_spherex-d6.json",
     lambda e: max(abs(c["significance"]) for c in e["comparisons"]), lambda x: f"{x:.1f}",
     ["readme", "site", "report", "portal"],
     "Largest WISE 0855 change in σ; no ≥5σ change.", ""),
    ("robustness.rw_aur_settings", "validated_real_observation", "robustness.json",
     lambda e: (e["targets"]["rw_aur"]["claims"][0]["n_holding"], e["targets"]["rw_aur"]["claims"][0]["n_checks"]),
     lambda x: f"{x[0]}/{x[1]}", ["readme", "site", "report", "portal"],
     "RW Aur '≥1.5× at ≥5σ' holds across the analysis settings (24/24).",
     "Rule-based stability labels, not probabilities."),
    ("validation.null_scatter", "validated_real_observation", "validation.json",
     _null_scatter, lambda x: f"{x:.2f}", ["readme", "site", "report", "portal"],
     "Blank-sky null-test scatter (ideal 1).", ""),
    ("validation.injection_snr5", "synthetic_test", "validation.json",
     lambda v: _inj(v, 5), lambda x: f"{100 * x:.0f}%", ["readme", "portal"],
     "SIMULATED injection recovery at S/N 5.", "SIMULATED sources on real backgrounds."),
    ("validation.injection_snr7", "synthetic_test", "validation.json",
     lambda v: _inj(v, 7), lambda x: f"{100 * x:.0f}%", ["readme", "portal"],
     "SIMULATED injection recovery at S/N 7.", "SIMULATED sources on real backgrounds."),
    ("kleopatra.rms_ra", "experimental_real_observation", "motion_check.json",
     lambda m: m["residuals_vs_horizons_spherex_arcsec"]["all_detections_near_prediction"]["rms_ra_cosdec"],
     lambda x: f"{x:.2f}", ["readme", "site", "report", "portal"],
     "Kleopatra RA·cosDec rms offset from JPL Horizons (observer SPHEREx), arcsec.",
     "Known asteroid; method validation only, not a discovery."),
    ("kleopatra.rms_dec", "experimental_real_observation", "motion_check.json",
     lambda m: m["residuals_vs_horizons_spherex_arcsec"]["all_detections_near_prediction"]["rms_dec"],
     lambda x: f"{x:.2f}", ["readme", "site", "report", "portal"],
     "Kleopatra Dec rms offset from JPL Horizons (observer SPHEREx), arcsec.", ""),
    ("kleopatra.outlier_flagged", "validated_real_observation", "motion_check.json",
     lambda m: (m["pipeline_flag_finding"]["n_with_outlier"], m["pipeline_flag_finding"]["n_exposures"]),
     lambda x: f"{x[0]} of {x[1]}", ["site", "report", "portal"],
     "Exposures where the SPHEREx pipeline flags the asteroid as OUTLIER.", ""),
]


def build() -> dict:
    cache: dict[str, dict] = {}
    claims = []
    for cid, status, src, get, fmt, chans, text, caveat in SPEC:
        ev = cache.setdefault(src, _load(src))
        value = get(ev)
        claims.append({
            "id": cid, "status": status, "claim": text, "caveat": caveat,
            "value": list(value) if isinstance(value, tuple) else value,
            "display": fmt(value) if value is not None else None,
            "evidence": f"submission/evidence/{src}", "evidence_sha256": _sha(src),
            "datasets": DOIS, "quoted_in": [CHANNELS[c] for c in chans],
        })
    return {
        "note": ("Built by backend/scripts/make_claims_registry.py from the evidence files. "
                 "backend/tests/test_claims_drift.py fails if a number changes here or "
                 "disappears from an output that quotes it."),
        "statuses": ["validated_real_observation", "experimental_real_observation",
                     "synthetic_test", "conceptual_explanation", "future_work"],
        "claims": claims,
    }
