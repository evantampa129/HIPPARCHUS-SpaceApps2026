"""Every number a scene shows equals the value in the evidence files."""

import math

import pytest


def close(a, b, rel=1e-12):
    return math.isclose(a, b, rel_tol=rel, abs_tol=1e-12)


def test_m01_positions(raw):
    from m01_ancient_sky import numbers
    n = numbers()
    for tid, f in (("rw_aur", "rw_aur_spherex-d1.json"), ("barnard", "barnard_spherex-d6.json"),
                   ("wise0855", "wise0855_spherex-d6.json")):
        d = raw(f)
        assert (n[tid]["ra"], n[tid]["dec"]) == (d["ra"], d["dec"])
        assert f'{d["ra"]:.3f}°' in n[tid]["text"]


def test_m02_rule_and_pairs(raw):
    from m02_filters import numbers
    n = numbers()
    c = raw("compat_check.json")
    assert n["limit_tophat"] == c["overlap_at_rule_limit"]["tophat"] == 0.5
    assert close(n["limit_gauss"], c["overlap_at_rule_limit"]["gaussian"])
    assert "50%" in n["rule_text"] and "55.6%" in n["rule_text"]
    edges = c["graphs"]["rw_aur"]["edges"]
    m = min(edges, key=lambda e: e["overlap_tophat"])
    assert close(n["good"]["top"], m["overlap_tophat"]) and close(n["good"]["top"], c["targets"]["rw_aur"]["published_min_overlap"]["tophat"])
    assert n["good"]["ok"] and not n["bad"]["ok"]
    # The refused example really fails the rule and stays below the 50% limit.
    assert n["bad"]["dl_nm"] > n["bad"]["half_nm"] and n["bad"]["top"] < 0.5
    assert f'{100*m["overlap_tophat"]:.1f}%' in n["good"]["text"][1]


def test_m03_aperture(raw):
    from m03_aperture import numbers
    n = numbers()
    assert not n["conceptual"]
    comp = next(c for c in raw("rw_aur_spherex-d1.json")["comparisons"] if c["a"] == n["obs_id"])
    assert n["flux"] == comp["flux_a"]["flux"] and n["flux_err"] == comp["flux_a"]["flux_err"]
    cfg = raw("rw_aur_spherex-d1.json")["config"]
    assert n["aperture_px"] == cfg["aperture_radius_px"] == 2.0
    assert list(n["annulus_px"]) == cfg["sky_annulus_px"] == [4.0, 7.0]
    assert len(n["inside"]) == comp["flux_a"]["n_pix"] == n["n_pix"]
    assert n["n_bad"] == 0
    assert f'{comp["flux_a"]["flux"]:.2f} ± {comp["flux_a"]["flux_err"]:.2f}' in n["lines"][3]


def test_m04_epsf(raw):
    from m04_epsf import numbers
    n = numbers()
    e = raw("epsf_check.json")
    assert "EXPERIMENTAL" in e["status"]
    assert n["chi2_epoch"] == e["targets"]["rw_aur"]["fits"][n["obs_id"]]["chi2_red"]
    v = e["diagnostics"]["variants"]
    assert n["chi2_median"] == v["published"]["rw_aur"]["chi2_red"]["median"]
    assert n["chi2_best_median"] == v["field_stars+sky_scale"]["rw_aur"]["chi2_red"]["median"]
    assert (n["within_2pct"], n["n_ratios"]) == (8, 8)
    assert f'{n["chi2_epoch"]:.1f}' in n["lines"][0] and "8/8 within 2%" in n["lines"][2]


def test_m05_fingerprint_counts(raw):
    from m05_fingerprint import numbers
    n = numbers()
    r = raw("robustness.json")["targets"]
    claims = r["rw_aur"]["claims"] + r["wise0855"]["claims"]
    assert [row["score"] for row in n["rows"]] == ["24/24", "18/24", "34/34"]
    for row, c in zip(n["rows"], claims):
        assert len(row["cells"]) == c["n_checks"]
        assert sum(ok for _, ok in row["cells"]) == c["n_holding"]
        assert row["verdict"] == c["verdict"]
    assert n["tagline"] == "rule-based labels, not probabilities"


def test_m06_kleopatra(raw):
    from m06_kleopatra import numbers
    n = numbers()
    m = raw("motion_check.json")
    rate = m["fitted_motion"]["measured_rate_arcsec_h"]
    # Our refit reproduces the published fitted rates.
    assert math.isclose(n["rate_fit"][0], rate["ra_cosdec"], rel_tol=1e-6)
    assert math.isclose(n["rate_fit"][1], rate["dec"], rel_tol=1e-6)
    res = m["residuals_vs_horizons_spherex_arcsec"]["linked_track_members"]
    assert n["n"] == res["n"] == len(n["t"]) == 31
    assert f'{res["rms_ra_cosdec"]:.2f}″' in n["lines"][1] and f'{res["rms_dec"]:.2f}″' in n["lines"][1]
    assert n["visits"] == 7


def test_m07_is_simulated_only():
    import m07_shift_stack as m
    assert m.EVIDENCE == [] and set(m.LABELS) == {"CONCEPTUAL", "SIMULATED"}
    n = m.numbers()
    assert n["best"] == m.TRUE_V  # the sketch recovers what we put in, nothing more


def test_m08_flow(raw):
    from m08_falsification import numbers
    n = numbers()
    b = raw("barnard_spherex-d6.json")
    assert (n["barnard"]["usable"], n["barnard"]["n"]) == (b["n_usable"], b["n_epochs"]) == (0, 58)
    assert "0/58" in n["barnard"]["cells"][3]
    rw = n["rw_aur"]
    assert round(rw["ratio"], 2) == 2.56 and rw["pairs"] == 8 and rw["n_pairs"] == 1540
    assert round(rw["sig"]) == 175 and round(rw["sig_floor"]) == 12
    assert "×2.56" in rw["cells"][3] and "8/1540" in rw["cells"][1]


def test_m09_graph(raw):
    from m09_compat_graph import numbers
    n = numbers()
    g = raw("compat_check.json")["graphs"]
    for tid in ("rw_aur", "barnard", "wise0855"):
        assert len(n[tid]["nodes"]) == g[tid]["summary"]["n_nodes"]
        assert len(n[tid]["edges"]) == g[tid]["summary"]["n_edges"]
    assert n["rw_aur"]["caption"].startswith("56 epochs · 18 usable · 8 edges of 1540")


def test_m10_per_epoch_fluxes(raw):
    from m10_spectral_time import numbers
    n = numbers()
    comps = raw("rw_aur_spherex-d1.json")["comparisons"]
    shown = sorted(v["flux"] for rec in n["flux"].values() for v in rec["values"])
    want = sorted([c["flux_a"]["flux"] for c in comps] + [c["flux_b"]["flux"] for c in comps])
    assert shown == want  # every per-pair flux, nothing invented, nothing averaged away
    assert n["n_epochs"] == 56
