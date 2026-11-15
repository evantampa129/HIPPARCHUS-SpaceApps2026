"""Benchmark scoring and the polite retry logic, with no network."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("run_benchmark", ROOT / "backend" / "scripts" / "run_benchmark.py")
rb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rb)

MANIFEST = json.loads(rb.MANIFEST.read_text())


def test_wilson_reference_values():
    w = rb.wilson(5, 10)
    assert w["rate"] == 0.5 and abs(w["lo"] - 0.2366) < 1e-3 and abs(w["hi"] - 0.7634) < 1e-3
    w = rb.wilson(0, 10)
    assert w["lo"] == 0.0 and abs(w["hi"] - 0.2775) < 1e-3
    assert rb.wilson(0, 0)["rate"] is None


def test_manifest_is_well_formed():
    cats = set(MANIFEST["expected_outcome"])
    ids = [o["id"] for o in MANIFEST["objects"]]
    assert len(ids) == len(set(ids))
    for o in MANIFEST["objects"]:
        assert o["category"] in cats and o["split"] in {"dev", "calibration", "held_out"}
        if o["source"] == "archive":
            assert o["detector"].startswith("SPHEREx-D") and o["split"] != "dev"
    assert {o["category"] for o in MANIFEST["objects"]} == cats


def test_dev_objects_score_from_published_evidence():
    got = {o["id"]: rb.outcome(o, rb.from_evidence(o)) for o in MANIFEST["objects"] if o["source"] == "published_evidence"}
    assert got["rw_aur"] == "TP"
    assert got["barnard"] == "refused_ok"
    assert got["wise0855"] == "TN"
    assert got["kleopatra"] == "recovered"


def _r(pairs):
    return {"status": "measured", "n_valid_pairs": len(pairs), "n_changed": sum(p["changed"] for p in pairs), "pairs": pairs}


def test_metrics_on_hand_made_results():
    # hand-made outcomes, only to test the arithmetic
    objs = [{"id": "v1", "category": "known_variable", "split": "held_out"},
            {"id": "v2", "category": "known_variable", "split": "held_out"},
            {"id": "s1", "category": "stable_control", "split": "held_out"},
            {"id": "s2", "category": "stable_control", "split": "held_out"},
            {"id": "x1", "category": "saturated", "split": "held_out"},
            {"id": "b1", "category": "stable_control", "split": "held_out"}]
    p = lambda ratio, sig: {"ratio": ratio, "sig": sig, "changed": abs(sig) >= 5, "control_ratio": 1.0}  # noqa: E731
    res = {"v1": _r([p(1.5, 40)]), "v2": _r([p(1.0, 1)]), "s1": _r([p(1.01, 0.5), p(0.99, -0.4)]),
           "s2": _r([p(1.2, 9)]), "x1": _r([]), "b1": {"status": rb.BLOCKED}}
    m = rb.metrics(objs, res)
    assert (m["completeness"]["k"], m["completeness"]["n"]) == (1, 2)
    assert (m["precision"]["k"], m["precision"]["n"]) == (1, 2)
    assert (m["false_positive_rate_objects_stable"]["k"], m["false_positive_rate_objects_stable"]["n"]) == (1, 2)
    assert m["false_positive_rate_pairs_stable"]["n"] == 3
    assert m["saturated_refusal_rate"]["rate"] == 1.0
    assert m["photometric_bias_stable_pairs"]["n"] == 3
    assert abs(m["photometric_bias_stable_pairs"]["median"] - 0.01) < 1e-9
    assert m["objects_by_status"]["stable_control"][rb.BLOCKED] == 1


class _Fake502:
    def __init__(self):
        self.calls = 0

    def get(self, url, **k):
        self.calls += 1
        return httpx.Response(502, request=httpx.Request("GET", url))


def test_unreachable_archive_is_marked_blocked_with_urls_and_times():
    c = _Fake502()
    budget = rb.Budget(100)   # enough for 10+20+40 s of (fake) pauses, not for the 80 s one
    with pytest.raises(rb.Blocked) as e:
        rb.polite_get("https://irsa.example/SIA?x=1", budget, sleep=lambda s: None, client=c)
    att = e.value.attempts
    assert c.calls == len(att) >= 2
    assert all(a["url"] == "https://irsa.example/SIA?x=1" and a["status"] == 502 and "T" in a["utc"] for a in att)


def test_offline_run_never_touches_the_network(tmp_path):
    with pytest.raises(FileNotFoundError):
        rb.sia_query(10.0, 10.0, rb.Budget(1), online=False, cache=tmp_path)
