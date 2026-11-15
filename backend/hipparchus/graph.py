"""Evidence graph: every result linked back to the archive records it came from.

Nodes are the dataset releases (with their DOI), the archive queries (with the
checksum of each raw answer), the observations, the downloaded cutouts (with
their checksum), the checked epochs, and the compared or refused pairs. An
edge says "was derived from". A judge can follow any number back to the exact
FITS file and the archive answer that listed it.
"""

from __future__ import annotations


def build(result: dict) -> dict:
    nodes, edges = {}, []

    def node(nid, kind, **attrs):
        nodes.setdefault(nid, {"id": nid, "kind": kind, **attrs})
        return nid

    for q in result.get("archive_queries", []):
        ds = node(f"dataset:{q['release']}", "dataset", release=q["release"])
        qid = node(f"query:{q['sha256'][:16]}", "archive_query", url=q["url"], sha256=q["sha256"])
        edges.append((qid, ds))
    query_of = {q["release"]: f"query:{q['sha256'][:16]}" for q in result.get("archive_queries", [])}

    for e in result["epochs"]:
        o = e["provenance"]["obs"]
        c = e["provenance"]["cutout"]
        nodes.setdefault(f"dataset:{o['release']}", {"id": f"dataset:{o['release']}", "kind": "dataset", "release": o["release"]})
        nodes[f"dataset:{o['release']}"]["doi"] = o.get("doi")
        oid = node(f"obs:{o['obs_id']}", "observation", access_url=o["access_url"], doi=o.get("doi"))
        edges.append((oid, query_of.get(o["release"], f"dataset:{o['release']}")))
        cid = node(f"cutout:{c['sha256'][:16]}", "cutout", url=c["url"], sha256=c["sha256"])
        edges.append((cid, oid))
        eid = node(f"epoch:{e['obs_id']}", "epoch", usable=e["usable"],
                   issues=[i["code"] for i in e["issues"]], wavelength_um=e["wavelength_um"])
        edges.append((eid, cid))

    for kind, pairs in (("comparison", result.get("comparisons", [])), ("null_test", result.get("null_tests", []))):
        for p in pairs:
            pid = node(f"pair:{p['a']}>{p['b']}", kind, significance=p.get("significance"),
                       flux_ratio=p.get("flux_ratio"), changed=p.get("changed"))
            edges += [(pid, f"epoch:{p['a']}"), (pid, f"epoch:{p['b']}")]

    return {"nodes": list(nodes.values()), "edges": [{"from": a, "to": b} for a, b in edges]}


def broken_edges(graph: dict) -> list[dict]:
    """Edges that point at a node that does not exist. Must be empty."""
    ids = {n["id"] for n in graph["nodes"]}
    return [e for e in graph["edges"] if e["from"] not in ids or e["to"] not in ids]


def unsourced(graph: dict) -> list[str]:
    """Result nodes that do not lead back to a dataset with a DOI. Must be empty."""
    out_edges = {}
    for e in graph["edges"]:
        out_edges.setdefault(e["from"], []).append(e["to"])
    nodes = {n["id"]: n for n in graph["nodes"]}

    def reaches_doi(nid, seen=()):
        n = nodes.get(nid)
        if n is None or nid in seen:
            return False
        if n["kind"] == "dataset":
            return bool(n.get("doi"))
        return any(reaches_doi(t, seen + (nid,)) for t in out_edges.get(nid, []))

    return [n["id"] for n in graph["nodes"] if n["kind"] in ("comparison", "null_test", "epoch")
            and not reaches_doi(n["id"])]
