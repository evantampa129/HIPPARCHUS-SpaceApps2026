"""Offline tests for backend/scripts/compare_irsa_tools.py.

Every input here is SIMULATED (hand-written tables, fake HTTP responses); no
network access and no IRSA data are needed.
"""

import importlib.util
import io
import json
import urllib.error
from pathlib import Path

import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compare_irsa_tools.py"


@pytest.fixture(scope="module")
def cit():
    spec = importlib.util.spec_from_file_location("compare_irsa_tools", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# SIMULATED MOST 'Brief' output: same layout as IRSA's IPAC table, made-up rows.
SIMULATED_MOST = """\\catalog = "spherex"
\\object_name = "216 Kleopatra (A880 GB)"
\\element_epoch = "60843.0000   (2025-Jun-17 00:00:00.0000)"
|    ra_obj|   dec_obj|  dist_ctr|  vmag|match|      observationid|productid|       mjd_start|         mjd_end|   uri|
|    double|    double|    double|double|  int|               char|     char|          double|          double|  char|
 201.400000  -8.212500     1.3653  13.07     1   SIM_0001_1            D3      60843.4970000    60843.4983000  ibe/data/spherex/dr1/level2/x.fits
 201.400000  -8.212500     1.3785  13.07     1   SIM_0001_1            D6      60843.4970000    60843.4983000  ibe/data/spherex/dr1/level2/y.fits
 201.410000  -8.200000     0.5000  13.07     1   SIM_0009_1            D2      60844.0000000    60844.0013000  ibe/data/spherex/dr1/level2/z.fits
"""


def test_parse_most_ipac_simulated(cit):
    header, rows = cit.parse_most_ipac(SIMULATED_MOST)
    assert header["catalog"] == "spherex"
    assert header["object_name"].startswith("216 Kleopatra")
    assert len(rows) == 3
    assert rows[0]["observationid"] == "SIM_0001_1"
    assert cit.most_key(rows[1]) == ("SIM_0001_1", "SPHEREx-D6")
    assert rows[2]["ra_obj"] == pytest.approx(201.41)


def _sim_exposure(obs_id, det, ra, dec, measured=True):
    e = {"obs_id": obs_id, "detector": det, "mjd_mid": 60843.49765,
         "horizons_spherex": {"ra": ra, "dec": dec},
         "horizons_geocentric": {"ra": ra - 1.0 / 3600, "dec": dec},
         "quality_issues_at_prediction": [] if measured else ["off_edge"],
         "measured": {"ra": ra, "dec": dec + 0.5 / 3600} if measured else None}
    return e


def test_match_most_overlap_and_offsets_simulated(cit):
    _, rows = cit.parse_most_ipac(SIMULATED_MOST)
    ours = [_sim_exposure("SIM_0001_1", "SPHEREx-D3", 201.4, -8.2125),
            _sim_exposure("SIM_0001_1", "SPHEREx-D6", 201.4, -8.2125),
            _sim_exposure("SIM_0002_1", "SPHEREx-D3", 201.42, -8.19, measured=False)]
    m = cit.match_most(rows, ours)
    assert (m["n_most"], m["n_ours"], m["n_both"]) == (3, 3, 2)
    assert m["only_most"] == [{"obs_id": "SIM_0009_1", "detector": "SPHEREx-D2"}]
    assert m["only_ours"][0]["obs_id"] == "SIM_0002_1"
    assert m["only_ours"][0]["we_measured_it"] is False
    p = m["per_image"][0]
    assert p["most_minus_horizons_spherex_mid"]["total"] == pytest.approx(0.0, abs=1e-6)
    # Geocentric RA was put 1 arcsec (of RA) west, so MOST - geo is +cos(dec) arcsec.
    assert p["most_minus_horizons_geocentric_mid"]["dra"] == pytest.approx(np.cos(np.radians(8.2125)), rel=1e-4)
    assert p["most_minus_measured"]["ddec"] == pytest.approx(-0.5, abs=1e-6)


def test_sky_offset_wraps_ra(cit):
    o = cit.sky_offset_arcsec(0.0001, 0.0, 359.9999, 0.0)
    assert o["dra"] == pytest.approx(0.72, rel=1e-6)


def test_mjd_to_most_time(cit):
    assert cit.mjd_to_most_time(60843.4) == "2025 06 17 09:36:00"
    url = cit.most_query_url("Kleopatra", 60843.4, 60846.7)
    assert "catalog=spherex" in url and "obs_begin=2025+06+17+09%3A36%3A00" in url


def test_parse_horizons_csv_simulated(cit):
    result = ("header\n$$SOE\n 2025-Jun-17 11:55:56.473, , , 201.400084308, -8.212447945,\n"
              " 2025-Jun-17 11:58:05.000,*, , 201.400100000, -8.212300000,\n$$EOE\nfooter")
    assert cit.parse_horizons_csv(result) == [(201.400084308, -8.212447945), (201.4001, -8.2123)]


def test_robust_stats(cit):
    s = cit.robust_stats([1.0, 2.0, 3.0, 100.0, None, float("nan")])
    assert s["n"] == 4 and s["median"] == 2.5
    assert s["robust_sigma"] == pytest.approx(1.4826 * 1.0)
    assert cit.robust_stats([])["n"] == 0


def test_our_epoch_fluxes_prefers_native_grid(cit):
    ev = {"comparisons": [  # SIMULATED
        {"a": "E2", "b": "E1", "flux_a": {"flux": 5.0, "flux_err": 0.1, "sky": 0.0},
         "flux_b": {"flux": 9.9, "flux_err": 0.1, "sky": 0.0}},
        {"a": "E1", "b": "E3", "flux_a": {"flux": 10.0, "flux_err": 0.1, "sky": 0.0},
         "flux_b": {"flux": float("nan"), "flux_err": 0.1, "sky": 0.0}},
    ]}
    f = cit.our_epoch_fluxes(ev)
    assert f["E1"]["flux"] == 10.0 and f["E1"]["grid"] == "native"
    assert f["E2"]["grid"] == "native"
    assert "E3" not in f   # NaN fluxes are never carried into the comparison


def test_parent_pixel_and_units(cit):
    hdr = {"CRPIX1A": -451.0, "CRPIX2A": -1510.0}   # SIMULATED, values as in a real cutout header
    assert cit.parent_pixel(hdr, 0.0, 0.0) == (452.0, 1511.0)
    # 1 MJy/sr over a (6.15 arcsec)^2 pixel is 1e9 mJy * 37.8225 * (pi/648000)^2.
    assert cit.mjysr_sum_to_mjy(1.0, 6.15 ** 2) == pytest.approx(0.8889, rel=1e-3)


def test_compare_pairs_simulated(cit):
    ev = {"comparisons": [{"a": "A", "b": "B", "flux_ratio": 2.0, "significance": 50.0, "changed": True,
                           "verdict": {"kind": "comparison"}}]}
    sdt = {"A": {"flux_mjy": [1.0, 1.2], "var_mjy2": [0.0004, 0.0009], "omega_fix": 1.0},
           "B": {"flux_mjy": [2.0, 2.4], "var_mjy2": [0.0004, 0.0009], "omega_fix": 1.0}}
    (p,) = cit.compare_pairs(ev, sdt, 2.0, omega_fix=False)
    assert p["sdt_ratio"] == pytest.approx(2.0)
    assert p["sdt_significance"] == pytest.approx(1.0 / np.hypot(0.02, 0.02))
    assert p["sdt_changed"] and p["ours_changed"]


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_retries_502_then_caches(cit, tmp_path, monkeypatch):
    monkeypatch.setattr(cit, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(cit, "ROOT", tmp_path)
    monkeypatch.setitem(cit._BUDGET, "spent_s", 0.0)
    calls, slept = [], []

    def opener(req, timeout):  # SIMULATED IRSA: two 502s, then the body
        calls.append(req.full_url)
        if len(calls) < 3:
            raise urllib.error.HTTPError(req.full_url, 502, "Bad Gateway", {}, None)
        return _Resp(b"SIMULATED BODY")

    url = "https://irsa.example/SIMULATED?x=1"
    r = cit.fetch(url, ".txt", opener=opener, sleep=slept.append, backoff=(1, 2, 4))
    assert r["status"] == 200 and not r["cached"]
    assert [a["status"] for a in r["attempts"]] == [502, 502, 200]
    assert slept == [1, 2]
    assert (tmp_path / r["path"]).read_bytes() == b"SIMULATED BODY"
    r2 = cit.fetch(url, ".txt", opener=opener, sleep=slept.append)
    assert r2["cached"] and len(calls) == 3


def test_fetch_gives_up_and_records_status(cit, tmp_path, monkeypatch):
    monkeypatch.setattr(cit, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(cit, "ROOT", tmp_path)
    monkeypatch.setitem(cit._BUDGET, "spent_s", 0.0)

    def opener(req, timeout):  # SIMULATED outage
        raise urllib.error.HTTPError(req.full_url, 502, "Bad Gateway", {}, None)

    r = cit.fetch("https://irsa.example/SIMULATED-down", opener=opener, sleep=lambda s: None, backoff=(1, 1))
    assert r["status"] == 502 and r["path"] is None and len(r["attempts"]) == 3
    meta = json.loads(next((tmp_path / "cache" / "http").glob("*.meta.json")).read_text())
    assert meta["status"] == 502 and all("t_utc" in a for a in meta["attempts"])

    # A 404 is not worth retrying.
    def gone(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
    r = cit.fetch("https://irsa.example/SIMULATED-404", opener=gone, sleep=lambda s: None, backoff=(1, 1))
    assert r["status"] == 404 and len(r["attempts"]) == 1


def test_fetch_respects_retry_budget(cit, tmp_path, monkeypatch):
    monkeypatch.setattr(cit, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(cit, "ROOT", tmp_path)
    monkeypatch.setitem(cit._BUDGET, "spent_s", 0.0)
    slept = []

    def opener(req, timeout):  # SIMULATED outage
        raise urllib.error.HTTPError(req.full_url, 503, "Unavailable", {}, None)

    r = cit.fetch("https://irsa.example/SIMULATED-budget", opener=opener, sleep=slept.append,
                  backoff=(10, 20, 40), budget_s=25)
    assert slept == [10] and len(r["attempts"]) == 2
