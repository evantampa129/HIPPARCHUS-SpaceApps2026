"""Mini reports: every number comes from the evidence, and the routes serve them."""

import json
import shutil

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hipparchus import api_repro, bundle, minireport

EVID = bundle.EVIDENCE
SECTIONS = ["Question", "Data", "Filtering and refusals", "Measurement", "Uncertainty", "Controls",
            "Limitations", "Links"]


def test_every_case_has_all_sections_and_the_banner():
    for case in bundle.CASES:
        h = minireport.render_html(case)
        assert minireport.BANNER in h
        for s in SECTIONS:
            assert f"<h2>{s}</h2>" in h, (case, s)


def test_verdicts_follow_the_evidence():
    rw = json.loads((EVID / "rw_aur_spherex-d1.json").read_text())
    n = len(rw["comparisons"])
    k = sum(c["changed"] for c in rw["comparisons"])
    assert f"{k} of {n} valid pairs" in minireport.render_html("rw_aur")
    assert "No pair passed the checks" in minireport.render_html("barnard")
    assert "SIMULATED" in minireport.render_html("kleopatra")


def test_numbers_are_read_not_typed(tmp_path):
    d = tmp_path / "ev"
    shutil.copytree(EVID, d)
    p = d / "wise0855_spherex-d6.json"
    ev = json.loads(p.read_text())
    ev["n_epochs"] = 12345
    p.write_text(json.dumps(ev))
    assert "12345 exposures" in minireport.render_html("wise0855", d)


def test_figures_are_png():
    for case in bundle.CASES:
        figs = minireport.figures(case)
        assert figs and all(b.startswith(b"\x89PNG") for b in figs.values())


def test_routes_serve_cached_artifacts():
    app = FastAPI()
    app.include_router(api_repro.router)
    c = TestClient(app)
    r = c.get("/report/rw_aur.html")
    assert r.status_code == 200 and "published-evidence" in r.headers["x-hipparchus-source"]
    assert minireport.BANNER in r.text
    z = c.get("/reproduce/kleopatra.zip")
    assert z.status_code == 200 and z.content[:2] == b"PK"
    assert c.get("/reproduce/nope.zip").status_code == 404
    assert c.get("/report/nope.html").status_code == 404
    assert {x["case"] for x in c.get("/reproduce").json()} == set(bundle.CASES)
