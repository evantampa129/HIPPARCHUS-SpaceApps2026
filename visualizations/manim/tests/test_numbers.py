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


def _top(raw):
    return max(raw("rw_aur_spherex-d1.json")["comparisons"], key=lambda c: c["flux_ratio"])


def test_m11_largest_ratio_pair(raw):
    from m11_change_real import numbers
    n = numbers()
    assert not n["conceptual"]
    top = _top(raw)
    ep = {e["obs_id"]: e for e in raw("rw_aur_spherex-d1.json")["epochs"]}
    assert (n["a"], n["b"]) == (top["a"], top["b"])
    assert n["flux_a"] == top["flux_a"]["flux"] and n["flux_b"] == top["flux_b"]["flux"]
    assert n["ratio"] == top["flux_ratio"] and round(n["ratio"], 2) == 2.56
    assert n["date_a"] == ep[top["a"]]["date_obs"][:10] and n["date_b"] == ep[top["b"]]["date_obs"][:10]
    assert f'{top["flux_a"]["flux"]:.2f} → {top["flux_b"]["flux"]:.2f}' in n["line"]
    assert f'{top["lambda_a_um"]:.3f} µm' in n["heads"][0] and f'{top["lambda_b_um"]:.3f} µm' in n["heads"][1]


def test_m12_wcs_maps_star_to_evidence_position(raw):
    from m12_wcs import numbers
    n = numbers()
    d = raw("rw_aur_spherex-d1.json")
    assert (n["ra"], n["dec"]) == (d["ra"], d["dec"])
    # The interpolated real WCS puts the star's pixel back on the evidence RA/Dec (< 0.01 arcsec).
    assert abs(n["ra_interp"] - d["ra"]) * 3600 < 0.01 and abs(n["dec_interp"] - d["dec"]) * 3600 < 0.01
    assert "TAN" in n["ctype"][0] and "TAN" in n["ctype"][1]
    assert 5.5 < n["scale_arcsec"] < 6.5  # SPHEREx native pixels are ~6.2 arcsec
    assert f'{d["ra"]:.3f}°' in n["sky_text"] and f'{d["dec"]:.3f}°' in n["sky_text"]


def test_m13_uncertainty(raw):
    from m13_uncertainty import numbers, sigma_parts
    n = numbers()
    top = _top(raw)
    rob = raw("robustness.json")["targets"]["rw_aur"]
    rp = next(p for p in rob["pairs"] if (p["a"], p["b"]) == (top["a"], top["b"]))
    assert n["floor"] == rob["systematic_floor"] and round(100 * n["floor"], 1) == 12.5
    assert n["sig"] == top["significance"] and round(n["sig"]) == 175
    assert n["sig_sys"] == rp["sig_with_systematics"] and round(n["sig_sys"]) == 12
    # The animation ends exactly on the published values: formal at floor 0, systematic at the floor.
    assert close(sigma_parts(n, 0.0)[1], top["delta_flux_err"], rel=1e-9)
    assert close(sigma_parts(n, 0.0)[2], top["significance"], rel=1e-9)
    assert close(sigma_parts(n, n["floor"])[2], rp["sig_with_systematics"], rel=1e-9)
    assert f'{top["delta_flux"]:.2f}' in n["lines"][1] and f'{100*rob["systematic_floor"]:.1f}%' in n["lines"][3]
    assert f'{rp["sig_with_systematics"]:.1f}σ' in n["final"][0]


def test_m14_barnard(raw):
    from m14_barnard_refusal import numbers
    n = numbers()
    b = raw("barnard_spherex-d6.json")
    assert (n["n"], n["n_usable"], n["usable_counted"]) == (b["n_epochs"], b["n_usable"], 0) == (58, 0, 0)
    assert len(n["per_epoch"]) == 58 and all(n["per_epoch"])  # every epoch has at least one reason
    flagged = sum(any(i["code"] == "flagged_pixels" for i in e["issues"]) for e in b["epochs"])
    assert max(n["tally"].values()) <= flagged
    for name, k in n["tally"].items():
        if name.isupper():
            assert k == sum(f"{name} (" in i["message"] for e in b["epochs"] for i in e["issues"])
    assert n["usable_text"] == "usable: 0/58" and n["why"] == b["target"]["why"]


def test_m15_identity_has_no_data():
    import m15_identity as m
    assert m.EVIDENCE == [] and m.M15Identity.LABELS == ("CONCEPTUAL",)
