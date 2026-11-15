"""Spectral-overlap and compatibility-graph checks (offline, evidence files only)."""

import json
from pathlib import Path

import pytest

from hipparchus import compat

EV = Path(__file__).resolve().parents[2] / "submission" / "evidence"


def test_overlap_identical_and_disjoint():
    for s in compat.SHAPES:
        assert compat.overlap(1.0, 0.02, 1.0, 0.02, s) == pytest.approx(1.0, abs=1e-6)
    assert compat.overlap(1.0, 0.02, 1.1, 0.02, "tophat") == 0.0
    assert compat.overlap(1.0, 0.02, 1.1, 0.02, "gaussian") < 1e-6


def test_rule_limit_matches_closed_form():
    # At |dλ| = half a channel a top-hat keeps exactly half; a Gaussian with
    # FWHM = channel keeps 2Φ(-0.589) ≈ 0.556.
    assert compat.overlap_at_rule_limit("tophat") == pytest.approx(0.5)
    assert compat.overlap_at_rule_limit("gaussian") == pytest.approx(0.556, abs=1e-3)


def test_unequal_widths_numeric_close_to_equal_case():
    # SIMULATED: nearly equal widths must give nearly the closed-form value.
    a = compat.overlap(1.0, 0.0200, 1.01, 0.0201, "gaussian")
    b = compat.overlap(1.0, 0.0200, 1.01, 0.0200, "gaussian")
    assert a == pytest.approx(b, abs=5e-3)


def test_overlap_symmetric():
    for s in compat.SHAPES:
        assert compat.overlap(1.0, 0.02, 1.012, 0.025, s) == pytest.approx(
            compat.overlap(1.012, 0.025, 1.0, 0.02, s), abs=1e-6)


@pytest.mark.parametrize("fname,n_edges", [("rw_aur_spherex-d1.json", 8), ("wise0855_spherex-d6.json", 27),
                                           ("barnard_spherex-d6.json", 0)])
def test_graph_rebuilds_published_pairs(fname, n_edges):
    ev = json.loads((EV / fname).read_text())
    rows = compat.pair_table(ev)
    g = compat.graph(ev, rows)
    assert g["summary"]["n_edges"] == n_edges
    assert g["summary"]["n_pairs"] == len(ev["epochs"]) * (len(ev["epochs"]) - 1) // 2
    # The refusal counts we rebuild from the epochs equal the published ones.
    assert g["summary"]["refusals_by_code"] == ev["refused_pairs"]
    # Every published pair passes the top-hat overlap >= 0.5 that our rule implies.
    assert all(e["overlap_tophat"] >= 0.5 - 1e-9 for e in g["edges"])
