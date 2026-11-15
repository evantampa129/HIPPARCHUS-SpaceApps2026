"""Spectral-response overlap and the observation compatibility graph.

Two diagnostics that sit on top of the pairing rule in compare.py, without
changing it:

* For every pair of epochs we model the spectral response of each exposure at
  the star and compute how much the two responses overlap. Our rule
  (|dλ| <= half a channel) is a cut on wavelength distance; the overlap says
  how much of the same light the two exposures actually collect.
* Per target and detector we build a graph: epochs are nodes, pairs we
  compare are edges, and every pair we refuse keeps its reasons.

Everything here reads the evidence files only, so it never touches pixels and
never changes a published number.
"""

from __future__ import annotations

import itertools
import math
from collections import Counter

from hipparchus.compare import MAX_DLAMBDA_FRACTION, SAME_VISIT_DAYS

# We do not have the measured per-pixel response curves, so we try two simple
# shapes for one channel, both centred on the wavelength at the star and with
# the channel width as their full width: a top-hat and a Gaussian with
# FWHM = width. The measured SPHEREx LVF response is in Hui et al. 2026
# (doi:10.3847/1538-4365/ae522c); we did not use it, so we report both shapes
# and let them bracket the answer.
SHAPES = ("gaussian", "tophat")
FWHM_TO_SIGMA = 1.0 / (2.0 * math.sqrt(2.0 * math.log(2.0)))


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def overlap(l1: float, w1: float, l2: float, w2: float, shape: str = "gaussian") -> float:
    """Overlap coefficient ∫ min(R1, R2) dλ of two unit-area responses (0..1)."""
    if shape == "tophat":
        lo, hi = max(l1 - w1 / 2, l2 - w2 / 2), min(l1 + w1 / 2, l2 + w2 / 2)
        inter = max(0.0, hi - lo)
        # Each top-hat has height 1/w, so the smaller curve is the taller one;
        # inside the intersection the minimum is 1/max(w).
        return inter / max(w1, w2)
    if shape != "gaussian":
        raise ValueError(shape)
    s1, s2 = w1 * FWHM_TO_SIGMA, w2 * FWHM_TO_SIGMA
    d = abs(l1 - l2)
    if abs(s1 - s2) < 1e-12 * max(s1, s2):
        # Equal widths: the curves cross half-way, so the overlap is closed-form.
        return 2.0 * _phi(-d / (2.0 * s1))
    # Unequal widths: we integrate min() numerically on a fine grid; this is
    # fast enough for a few thousand pairs.
    lo = min(l1 - 8 * s1, l2 - 8 * s2)
    hi = max(l1 + 8 * s1, l2 + 8 * s2)
    n = 4000
    step = (hi - lo) / n
    tot = 0.0
    for i in range(n):
        x = lo + (i + 0.5) * step
        g1 = math.exp(-0.5 * ((x - l1) / s1) ** 2) / (s1 * math.sqrt(2 * math.pi))
        g2 = math.exp(-0.5 * ((x - l2) / s2) ** 2) / (s2 * math.sqrt(2 * math.pi))
        tot += min(g1, g2)
    return tot * step


def overlap_at_rule_limit(shape: str = "gaussian") -> float:
    """Overlap of two equal channels exactly at our |dλ| = half-channel limit."""
    return overlap(0.0, 1.0, MAX_DLAMBDA_FRACTION, 1.0, shape)


def _reject_codes(ep: dict) -> list[str]:
    return [i["code"] for i in ep.get("issues", []) if i.get("severity") == "reject"]


def pair_table(evidence: dict) -> list[dict]:
    """Every pair of epochs with Δλ, the rule verdict and both overlaps."""
    eps = evidence["epochs"]
    done = {(c["a"], c["b"]) for c in evidence.get("comparisons", [])}
    done |= {(c["b"], c["a"]) for c in evidence.get("comparisons", [])}
    rows = []
    for a, b in itertools.combinations(eps, 2):
        la, lb = a["wavelength_um"], b["wavelength_um"]
        wa, wb = a["bandwidth_um"], b["bandwidth_um"]
        dlam = abs(la - lb)
        rule_ok = dlam <= MAX_DLAMBDA_FRACTION * min(wa, wb)
        codes = sorted(set(_reject_codes(a) + _reject_codes(b)))
        if not rule_ok:
            codes.append("wavelength_mismatch")
        same_visit = abs(a["mjd"] - b["mjd"]) < SAME_VISIT_DAYS
        rows.append({
            "a": a["obs_id"], "b": b["obs_id"],
            "dlambda_um": dlam,
            "dlambda_over_channel": dlam / min(wa, wb),
            "rule_pass": rule_ok,
            "overlap_gaussian": overlap(la, wa, lb, wb, "gaussian"),
            "overlap_tophat": overlap(la, wa, lb, wb, "tophat"),
            "same_visit": same_visit,
            "refusal_codes": codes,
            "published_comparison": (a["obs_id"], b["obs_id"]) in done,
        })
    return rows


def confusion(rows: list[dict], threshold: float, shape: str = "gaussian") -> dict:
    """Rule pass/fail against 'overlap >= threshold', over all pairs."""
    key = f"overlap_{shape}"
    c = Counter((r["rule_pass"], r[key] >= threshold) for r in rows)
    return {"rule_pass_overlap_high": c[(True, True)], "rule_pass_overlap_low": c[(True, False)],
            "rule_fail_overlap_high": c[(False, True)], "rule_fail_overlap_low": c[(False, False)]}


def graph(evidence: dict, rows: list[dict] | None = None) -> dict:
    """Nodes = epochs, edges = the comparisons we published, refusals kept with reasons."""
    rows = rows if rows is not None else pair_table(evidence)
    by_pair = {(r["a"], r["b"]): r for r in rows}
    by_pair.update({(r["b"], r["a"]): r for r in rows})
    nodes = [{"id": e["obs_id"], "mjd": e["mjd"], "wavelength_um": e["wavelength_um"],
              "bandwidth_um": e["bandwidth_um"], "usable": e["usable"],
              "reasons": _reject_codes(e)} for e in evidence["epochs"]]
    edges = []
    for c in evidence.get("comparisons", []):
        r = by_pair[(c["a"], c["b"])]
        edges.append({"a": c["a"], "b": c["b"], "dlambda_um": r["dlambda_um"],
                      "overlap_gaussian": r["overlap_gaussian"], "overlap_tophat": r["overlap_tophat"],
                      "flux_ratio": c.get("flux_ratio"), "significance": c.get("significance")})
    # Connected components with a tiny union-find; isolated nodes count too.
    parent = {n["id"]: n["id"] for n in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edges:
        parent[find(e["a"])] = find(e["b"])
    comp = Counter(find(n["id"]) for n in nodes)
    in_edges = Counter()
    for e in edges:
        in_edges[find(e["a"])] += 1
    nontrivial = [k for k in comp if in_edges[k]]
    refused = Counter(code for r in rows for code in set(r["refusal_codes"]))
    return {
        "nodes": nodes, "edges": edges,
        "summary": {
            "n_nodes": len(nodes), "n_usable": sum(n["usable"] for n in nodes),
            "n_pairs": len(rows), "n_edges": len(edges),
            "n_components_with_edges": len(nontrivial),
            "largest_component": max((comp[k] for k in nontrivial), default=0),
            "n_isolated_nodes": sum(1 for k in comp if not in_edges[k]),
            "refusals_by_code": dict(refused),
        },
    }
