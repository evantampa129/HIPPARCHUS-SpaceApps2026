"""API tests that need no network: they use the cached manifests and fixtures."""

from fastapi.testclient import TestClient

from hipparchus import api

client = TestClient(api.app)


def test_targets_are_labelled():
    t = client.get("/targets").json()
    assert {x["id"] for x in t} >= {"rw_aur", "barnard"}
    assert all("why" in x for x in t)


def test_bad_coordinates_are_rejected():
    assert client.get("/observations", params={"ra": 400, "dec": 0}).status_code == 422
    assert client.get("/analyze", params={"ra": 10, "dec": 0, "detector": "D9"}).status_code == 422


def test_public_strips_arrays_and_nan():
    import numpy as np
    out = api._public({"a": 1, "_arrays": [1], "x": float("nan"), "y": np.float64(2.5)})
    assert out == {"a": 1, "x": None, "y": 2.5}


def test_unknown_analysis_is_404():
    assert client.get("/analysis/nope/evidence.json").status_code == 404
