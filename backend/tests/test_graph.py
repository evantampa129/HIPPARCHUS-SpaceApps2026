"""The evidence graph must lead every result back to a dataset DOI."""

import json
from pathlib import Path

from hipparchus import graph

EV = Path(__file__).resolve().parents[2] / "submission" / "evidence" / "rw_aur_spherex-d1.json"


def test_real_evidence_graph_is_complete():
    g = graph.build(json.loads(EV.read_text()))
    assert graph.broken_edges(g) == []
    assert graph.unsourced(g) == []
    assert any(n["kind"] == "comparison" for n in g["nodes"])


def test_bad_edge_and_missing_source_are_caught():
    g = graph.build(json.loads(EV.read_text()))
    g["edges"].append({"from": "pair:x>y", "to": "epoch:does-not-exist"})
    assert len(graph.broken_edges(g)) == 1
    # We cut every link from cutouts to observations: no epoch can reach a DOI any more.
    g["edges"] = [e for e in g["edges"] if not e["from"].startswith("cutout:")]
    assert graph.unsourced(g)
