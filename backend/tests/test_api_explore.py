"""Explorer endpoints, with no network: outgoing requests are replaced by fakes."""

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hipparchus import api, api_explore, compare, quality

FX = Path(__file__).parent / "fixtures"
RW_AUR = (76.956, 30.401)

# We mount the router on its own app, so these tests do not depend on how api.py wires it.
app = FastAPI()
app.include_router(api_explore.router)
client = TestClient(app)

SESAME_RW = """<?xml version="1.0" encoding="UTF-8"?><Sesame><Target option="SNV"><name>RW Aur</name>
<Resolver name="S=Simbad"><oname>V* RW Aur</oname><otype>TT*</otype>
<jradeg>76.95652603458</jradeg><jdedeg>30.40143817389</jdedeg>
<pm><v>21.58</v><pmRA>7.23</pmRA><pmDE>-20.33</pmDE></pm></Resolver></Target></Sesame>"""
SESAME_NONE = """<?xml version="1.0"?><Sesame><Target><name>x</name><INFO> *** Nothing found *** </INFO></Target></Sesame>"""


class _Fake:
    def __init__(self, text="", status=200, url="https://cds.unistra.fr/x"):
        self.text, self.status_code, self.url = text, status, url
        self.content = text.encode()


@pytest.fixture(autouse=True)
def _clear_caches():
    api_explore._RESOLVE_CACHE.clear()
    api_explore._HIPS_CACHE.clear()


def test_resolver_rejects_bad_names(monkeypatch):
    monkeypatch.setattr(api_explore, "_fetch", lambda *a, **k: pytest.fail("must not reach the network"))
    assert client.get("/explore/resolve", params={"name": ""}).status_code == 422
    assert client.get("/explore/resolve", params={"name": "x" * 65}).status_code == 422
    assert client.get("/explore/resolve", params={"name": "<script>"}).status_code == 422
    assert client.get("/explore/resolve", params={"name": "a;rm -rf"}).status_code == 422


def test_resolver_parses_moves_and_caches(monkeypatch):
    calls = []
    monkeypatch.setattr(api_explore, "_fetch", lambda url, t: calls.append(url) or _Fake(SESAME_RW))
    r = client.get("/explore/resolve", params={"name": "RW  Aur"}).json()
    assert r["oname"] == "V* RW Aur" and r["epoch"] == 2026.0
    # 26 years of proper motion (~0.5") stays far below one 6.15" pixel.
    assert abs(r["ra"] - 76.95652603458) < 1e-3 and abs(r["dec"] - 30.40143817389) < 1e-3
    assert r["dec"] < r["dec_j2000"]  # pmDE is negative
    assert client.get("/explore/resolve", params={"name": "rw aur"}).json()["cached"] is True
    assert len(calls) == 1


def test_proper_motion_puts_barnard_where_spherex_saw_it():
    # SIMBAD J2000 position and proper motion of Barnard's Star; the preset is the 2025.9 position.
    ra, dec = api_explore.propagate(269.45207696, 4.69336497, -801.551, 10362.394)
    assert abs(dec - 4.7667) < 0.003 and abs(ra - 269.4463) < 0.003


def test_resolver_not_found_and_outage(monkeypatch):
    monkeypatch.setattr(api_explore, "_fetch", lambda url, t: _Fake(SESAME_NONE))
    assert client.get("/explore/resolve", params={"name": "nothing here"}).status_code == 404

    def boom(url, t):
        raise httpx.ConnectTimeout("slow")
    monkeypatch.setattr(api_explore, "_fetch", boom)
    r = client.get("/explore/resolve", params={"name": "RW Aur"})
    assert r.status_code == 504 and "RA/Dec" in r.json()["detail"]

    monkeypatch.setattr(api_explore, "_fetch", lambda url, t: _Fake("bad", 502))
    assert client.get("/explore/resolve", params={"name": "RW Aur"}).status_code == 502


def test_resolver_refuses_unknown_redirect_host(monkeypatch):
    monkeypatch.setattr(api_explore, "_fetch", lambda url, t: _Fake(SESAME_RW, url="https://evil.example/x"))
    assert client.get("/explore/resolve", params={"name": "RW Aur"}).status_code == 502


def test_hips_reports_irsa_502_honestly(monkeypatch):
    monkeypatch.setattr(api_explore, "_fetch", lambda url, t: _Fake("<html>bad gateway</html>", 502))
    d = client.get("/explore/hips").json()
    assert d["spherex_available"] is False
    sx = d["layers"][0]
    assert sx["label"] == "SPHEREx (NASA/IPAC IRSA)" and sx["status"]["http_status"] == 502
    assert "502" in sx["status"]["message"]
    assert d["judge_mode_url"].startswith("https://")
    # The channel list still comes back, from the saved copy, and says so.
    assert len(d["channels_um"]) == 102 and "saved" in d["channels_source"]


def test_hips_ok_parses_cube(monkeypatch):
    props = ("hips_order = 5\nhips_pixel_scale = 0.0035786\ndataproduct_type = cube\nhips_cube_depth = 102\n"
             "data_cube_crval3_arr = " + " ".join(str(v) for v in api_explore.SPHEREX_CHANNELS_UM_SAVED) + "\n")
    monkeypatch.setattr(api_explore, "_fetch", lambda url, t: _Fake(props))
    d = client.get("/explore/hips").json()
    assert d["spherex_available"] and d["channels_source"] == "live HiPS properties"
    sx = d["layers"][0]
    # HiPS pixels (12.9") are coarser than the native 6.15": the legend must not claim more.
    assert sx["hips_pixel_arcsec"] > d["native_pixel_arcsec"]
    assert all(layer["kind"] == "context" and "not SPHEREx" in layer["label"] for layer in d["layers"][1:])


@pytest.fixture
def analysis():
    a = quality.load(str(FX / "rwaur_d1_2025.fits"), "2025W36_1A_0233_3", *RW_AUR)
    b = quality.load(str(FX / "rwaur_d1_2026.fits"), "2026W37_1A_0234_3", *RW_AUR)
    c = compare.compare(a, b)
    c["pair_id"] = 0
    aid = "0123456789abcdef"
    full = {"ra": RW_AUR[0], "dec": RW_AUR[1], "detector": "SPHEREx-D1", "_epochs": [a, b],
            "epochs": [{"obs_id": e.obs_id, "provenance": {"obs": {"release": "DR1", "doi": "10.26131/IRSA678"},
                                                            "cutout": {"sha256": "abc"}}} for e in (a, b)],
            "comparisons": [c], "null_tests": [], "refused_pairs": {}}
    with api._LOCK:
        api._RESULTS[aid] = {"full": full, "public": {}}
    yield aid, c
    with api._LOCK:
        api._RESULTS.pop(aid, None)


def test_spectrum_is_per_epoch_and_matches_the_comparison(analysis):
    aid, c = analysis
    d = client.get(f"/explore/spectrum/{aid}").json()
    assert d["coadded"] is False and len(d["points"]) == 2
    p0 = d["points"][0]
    # Epoch a is measured on its own grid, exactly as in the comparison.
    assert p0["flux"] == pytest.approx(c["flux_a"]["flux"], rel=1e-4)
    assert p0["flux_mjy"] == pytest.approx(p0["flux"] * p0["sr_per_pixel"] * 1e9, rel=1e-3)
    assert "MJy/sr summed" in d["units"]["native"] and "NOT" in d["units"]["converted"]


def test_pixels_endpoints(analysis):
    aid, _ = analysis
    e = client.get(f"/explore/pixels/{aid}/epoch/2025W36_1A_0233_3").json()
    assert e["shape"] == [len(e["image"]), len(e["image"][0])] and e["unit"] == "MJy/sr"
    assert 6.0 < e["pixel_arcsec"] < 6.3 and e["aperture_radius_px"] == quality.APERTURE_PX
    p = client.get(f"/explore/pixels/{aid}/pair/0").json()
    assert {"a", "b", "diff", "z", "masked"} <= set(p) and p["meta_b"]["obs_id"] == "2026W37_1A_0234_3"
    assert client.get(f"/explore/pixels/{aid}/pair/5").status_code == 404
    assert client.get(f"/explore/pixels/{aid}/epoch/nope").status_code == 404
    assert client.get("/explore/pixels/NOT-AN-ID/pair/0").status_code == 422
    assert client.get("/explore/spectrum/ffffffffffffffff").status_code == 404
