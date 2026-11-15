from fastapi.testclient import TestClient

from hipparchus.api import app


def test_health():
    # TestClient calls the app in-process, so this test needs no running server
    # and no network. That keeps it usable in CI and when IRSA is offline.
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
