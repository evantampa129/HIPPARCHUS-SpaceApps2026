"""The loader reads the evidence correctly and refuses bad input."""

import math

import numpy as np
import pytest

from hviz import data as D


def test_all_targets_load_and_validate():
    for tid in ("rw_aur", "barnard", "wise0855"):
        D.target(tid)
    D.compat(), D.robustness(), D.motion(), D.epsf()


def test_unit_check_rejects_out_of_range():
    with pytest.raises(D.EvidenceError):
        D.check_units({"wavelength_um": 12.0})       # outside SPHEREx
    with pytest.raises(D.EvidenceError):
        D.check_units({"bandwidth_um": 1.0})         # a channel is ~1-2% of lambda
    with pytest.raises(D.EvidenceError):
        D.check_units({"mjd": 51544.0})              # year 2000: before SPHEREx
    with pytest.raises(D.EvidenceError):
        D.require({"a": 1}, ["b"])


def test_overlap_port_matches_evidence_edges():
    c = D.compat()
    for tid in ("rw_aur", "wise0855"):
        nodes = {n["id"]: n for n in c["graphs"][tid]["nodes"]}
        for e in c["graphs"][tid]["edges"]:
            a, b = nodes[e["a"]], nodes[e["b"]]
            args = (a["wavelength_um"], a["bandwidth_um"], b["wavelength_um"], b["bandwidth_um"])
            assert math.isclose(D.overlap(*args, "tophat"), e["overlap_tophat"], rel_tol=1e-9)
            assert math.isclose(D.overlap(*args, "gaussian"), e["overlap_gaussian"], rel_tol=1e-6)


def test_pixel_extract_is_the_evidence_cutout(raw):
    p = D.pixels()
    assert p is not None, "run tools/extract_pixels.py with the backend venv"
    ev = {e["obs_id"]: e for e in raw("rw_aur_spherex-d1.json")["epochs"]}[p["obs_id"]]
    assert p["cutout_sha256"] == ev["provenance"]["cutout"]["sha256"]
    comp = next(c for c in raw("rw_aur_spherex-d1.json")["comparisons"] if c["a"] == p["obs_id"])
    assert math.isclose(p["photometry"]["flux"], comp["flux_a"]["flux"], rel_tol=1e-9)
    fit = raw("epsf_check.json")["targets"]["rw_aur"]["fits"][p["obs_id"]]
    assert math.isclose(p["epsf"]["chi2_red"], fit["chi2_red"], rel_tol=1e-9)
    r = np.array([[np.nan if v is None else v for v in row] for row in p["epsf"]["residual_sigma"]])
    assert math.isclose(np.nansum(r ** 2) / p["epsf"]["dof"], fit["chi2_red"], rel_tol=1e-6)


def test_pair_extract_is_the_evidence_pair(raw):
    p = D.pair()
    assert p is not None, "run tools/extract_pair.py with the backend venv"
    top = max(raw("rw_aur_spherex-d1.json")["comparisons"], key=lambda c: c["flux_ratio"])
    assert (p["a"], p["b"]) == (top["a"], top["b"])
    assert math.isclose(p["flux"]["significance"], top["significance"], rel_tol=1e-9)
    a, b = np.array(p["stamp_a"], dtype=float), np.array(p["stamp_b"], dtype=float)
    d = np.array(p["stamp_diff"], dtype=float)
    assert np.allclose(b - a, d, atol=1e-9)  # the difference is exactly b - a (each minus its own sky)
