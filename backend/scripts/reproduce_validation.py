"""Checks of the method on the three real targets, written to submission/evidence/.

    cd backend && python scripts/reproduce_validation.py

* null test at blank positions (are the error bars right?)
* injection-recovery with SIMULATED stars (what can be detected?)
* spectral context: target brightness against wavelength for every usable epoch
* evidence graph of every result back to its dataset DOI
* timings of the analysis and of the API answers (p50/p95)

We go through the API, as the web app does, so the timings are the ones a user
sees. Cutouts come from the verified cache; we query the archive listing live.
"""

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from hipparchus import api, graph, validation as V  # noqa: E402
from hipparchus.compare import photometry  # noqa: E402

OUT = ROOT / "submission" / "evidence"


def pct(xs):
    return {"n": len(xs), "p50_ms": float(np.percentile(xs, 50)), "p95_ms": float(np.percentile(xs, 95))}


def main():
    client = TestClient(api.app)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "code_commit": commit,
              "note": "Injected sources are SIMULATED and appear only in the 'injection' sections.",
              "targets": [], "all_targets": {}}
    all_z, all_inj, lat = [], [], {"epoch_png": [], "pair_png": [], "evidence_json": []}

    for t in api.TARGETS:
        t0 = time.perf_counter()
        pub = client.get("/analyze", params={"ra": t["ra"], "dec": t["dec"], "detector": t["detector"]}).json()
        analyze_s = time.perf_counter() - t0
        aid = pub["analysis_id"]
        full = api._RESULTS[aid]["full"]
        ep = {e.obs_id: e for e in full["_epochs"]}

        z, inj = [], []
        for c in full["comparisons"]:
            a = ep[c["a"]]
            z += V.null_test(c, a.x, a.y)
            inj += V.injection_recovery(c, a.x, a.y, V.fwhm_px(a))
        all_z += z
        all_inj += inj

        # Brightness against wavelength. SPHEREx sees the star at a different
        # wavelength in each visit, so this is a coarse spectrum with each point
        # dated; points at the same wavelength but different dates show variability.
        spectrum = []
        for e in full["_epochs"]:
            if e.usable:
                p = photometry(e.image, e.variance, e.bad, e.x, e.y)
                spectrum.append({"obs_id": e.obs_id, "date_obs": e.date_obs, "wavelength_um": e.wavelength_um,
                                 "bandwidth_um": e.bandwidth_um, "flux": p["flux"], "flux_err": p["flux_err"]})

        g = graph.build(pub)
        (OUT / f"graph_{t['id']}_{t['detector'].lower()}.json").write_text(json.dumps(g, indent=1))

        # API latency for the requests the app makes after the analysis.
        usable = [e.obs_id for e in full["_epochs"]][:10]
        for i in range(30):
            o = usable[i % len(usable)]
            s = time.perf_counter(); client.get(f"/analysis/{aid}/epoch/{o}.png")
            lat["epoch_png"].append((time.perf_counter() - s) * 1000)
            s = time.perf_counter(); client.get(f"/analysis/{aid}/evidence.json")
            lat["evidence_json"].append((time.perf_counter() - s) * 1000)
            if full["comparisons"]:
                s = time.perf_counter(); client.get(f"/analysis/{aid}/pair/0/{['a', 'b', 'diff', 'z'][i % 4]}.png")
                lat["pair_png"].append((time.perf_counter() - s) * 1000)

        report["targets"].append({
            "id": t["id"], "name": t["name"], "detector": t["detector"],
            "analysis_seconds_warm_cache": analyze_s, "epochs": pub["n_epochs"], "valid_pairs": len(pub["comparisons"]),
            "null_test": V.null_summary(z),
            "injection_SIMULATED": V.recovery_curve(inj),
            "spectrum": spectrum,
            "graph": {"nodes": len(g["nodes"]), "edges": len(g["edges"]),
                      "broken_edges": len(graph.broken_edges(g)), "unsourced_results": len(graph.unsourced(g))},
        })
        print(t["name"], f"{analyze_s:.1f}s", report["targets"][-1]["null_test"])

    report["all_targets"] = {"null_test": V.null_summary(all_z), "injection_SIMULATED": V.recovery_curve(all_inj),
                             "api_latency": {k: pct(v) for k, v in lat.items() if v}}
    (OUT / "validation.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report["all_targets"], indent=1))


if __name__ == "__main__":
    main()
