"""Survey benchmark: the change test on objects we did not use to build it.

    cd backend
    python scripts/run_benchmark.py resolve    # one-off, network: coordinates from CDS Sesame
    python scripts/run_benchmark.py            # offline: score what is already cached
    python scripts/run_benchmark.py --online   # query IRSA and download cutouts (slow, GBs)

The object list, classes and dev/calibration/held-out split live in
submission/benchmark/manifest.json and were fixed before any run. Dev objects
are scored from the published evidence, never recomputed. Everything the
archive did not give us is marked BLOCKED_BY_EXTERNAL_SERVICE with the exact
URLs and timestamps; nothing is filled in. No simulated data is used here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from hipparchus import archive, cutouts, pipeline  # noqa: E402

MANIFEST = ROOT / "submission" / "benchmark" / "manifest.json"
OUT_DIR = ROOT / "submission" / "benchmark"
CACHE = archive.DATA_DIR / "cache" / "benchmark"
BLOCKED = "BLOCKED_BY_EXTERNAL_SERVICE"
SESAME = "https://cds.unistra.fr/cgi-bin/nph-sesame/-oxp/SNV"
EPOCH = 2026.0  # middle of the SPHEREx data we use (DR1 + QR3)

# IRSA SIA was answering 502 for hours at a time while we worked, so we wait
# longer and longer between tries, and stop for good once the budget is spent.
WAITS_S = (10, 20, 40, 80, 160, 300)
DEFAULT_BUDGET_S = 30 * 60


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- statistics

def wilson(k: int, n: int, z: float = 1.96) -> dict:
    """Rate k/n with its 95% Wilson score interval (sane at small n and at 0 or n)."""
    if n == 0:
        return {"k": k, "n": 0, "rate": None, "lo": None, "hi": None}
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return {"k": k, "n": n, "rate": p, "lo": max(0.0, c - h), "hi": min(1.0, c + h)}


def robust_bias(values: list[float]) -> dict:
    """Median of (ratio - 1) with a normal-equivalent error of the median."""
    if not values:
        return {"n": 0, "median": None, "err": None}
    med = statistics.median(values)
    mad = statistics.median(abs(v - med) for v in values)
    # 1.4826 MAD ~ sigma; the median's error is ~1.253 sigma / sqrt(n)
    err = 1.253 * 1.4826 * mad / math.sqrt(len(values)) if len(values) > 1 else None
    return {"n": len(values), "median": med, "err": err}


# ---------------------------------------------------------------- network

class Blocked(Exception):
    def __init__(self, url: str, attempts: list[dict]):
        super().__init__(f"{url}: gave up after {len(attempts)} attempts")
        self.url, self.attempts = url, attempts


class Budget:
    """One time budget shared by every retry of a run."""

    def __init__(self, seconds: float):
        self.deadline = time.monotonic() + seconds

    def left(self) -> float:
        return self.deadline - time.monotonic()


def polite_get(url: str, budget: Budget, timeout: float = 120.0, sleep=time.sleep,
               client: httpx.Client | None = None) -> bytes:
    """GET with growing pauses. Every attempt is logged with its UTC time."""
    attempts = []
    k = 0
    get = client.get if client else httpx.get
    while True:
        rec = {"url": url, "utc": now()}
        try:
            r = get(url, timeout=timeout, follow_redirects=True)
            rec["status"] = r.status_code
            if r.status_code == 200:
                return r.content
            # a 4xx other than 429 will not fix itself by waiting
            if 400 <= r.status_code < 500 and r.status_code != 429:
                attempts.append(rec)
                raise Blocked(url, attempts)
        except httpx.HTTPError as e:
            rec["error"] = f"{type(e).__name__}: {e}"
        attempts.append(rec)
        wait = WAITS_S[min(k, len(WAITS_S) - 1)]
        k += 1
        if budget.left() < wait:
            raise Blocked(url, attempts)
        sleep(wait)


def sia_url(ra: float, dec: float, collection: str) -> str:
    params = {"COLLECTION": collection, "POS": f"CIRCLE {ra} {dec} 0.001", "RESPONSEFORMAT": "VOTABLE"}
    return str(httpx.Request("GET", archive.SIA_URL, params=params).url)


def sia_query(ra: float, dec: float, budget: Budget, online: bool, cache: Path = CACHE) -> dict:
    """Same answer shape as archive.query, but every raw VOTable is kept under
    data/cache/benchmark/sia, so a rerun does not depend on IRSA being up."""
    d = cache / "sia"
    d.mkdir(parents=True, exist_ok=True)
    obs, sources = [], []
    for coll in archive.COLLECTIONS:
        url = sia_url(ra, dec, coll)
        path = d / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".xml")
        if path.exists():
            content, status = path.read_bytes(), "cached"
        elif not online:
            raise FileNotFoundError(f"not cached (offline run): {url}")
        else:
            content, status = polite_get(url, budget), "live"
            path.write_bytes(content)
        obs += archive._parse(content, coll)
        sources.append({"release": coll, "url": url, "sha256": hashlib.sha256(content).hexdigest(),
                        "status": status})
    seen = {}
    for o in obs:
        seen.setdefault((o.obs_id, o.detector), o)
    ordered = sorted(seen.values(), key=lambda o: o.mjd_start)
    from dataclasses import asdict
    return {"archive_status": "live", "sources": sources, "errors": [],
            "observations": [asdict(o) | {"mjd_mid": o.mjd_mid, "utc_mid": o.utc_mid} for o in ordered]}


# ---------------------------------------------------------------- coordinates

def resolve(name: str, epoch: float = EPOCH) -> dict:
    from urllib.parse import quote
    url = SESAME + "?" + quote(name)  # Sesame takes the bare name as the query string
    r = httpx.get(url, timeout=180, follow_redirects=True)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    res = root.find(".//Resolver")
    if res is None or res.find("jradeg") is None:
        raise ValueError(f"Sesame did not resolve {name!r}")
    ra, dec = float(res.findtext("jradeg")), float(res.findtext("jdedeg"))
    pmra = float(res.findtext("pm/pmRA") or 0.0)   # mas/yr, already times cos(dec)
    pmde = float(res.findtext("pm/pmDE") or 0.0)
    dt = epoch - 2000.0
    dec_e = dec + pmde * dt / 3.6e6
    ra_e = ra + pmra * dt / 3.6e6 / math.cos(math.radians(dec))
    return {"ra": round(ra_e, 6), "dec": round(dec_e, 6), "epoch": epoch,
            "resolver": {"url": url, "utc": now(), "simbad_name": res.findtext("oname"),
                         "j2000": [ra, dec], "pm_mas_yr": [pmra, pmde]}}


# ---------------------------------------------------------------- one object

def summarize(pub: dict) -> dict:
    """The few numbers the metrics need, from one analyze() result."""
    comps = pub.get("comparisons", [])
    return {
        "n_epochs": pub.get("n_epochs", 0),
        "n_usable": pub.get("n_usable", 0),
        "n_valid_pairs": len(comps),
        "n_changed": sum(bool(c.get("changed")) for c in comps),
        "max_abs_significance": max((abs(c["significance"]) for c in comps), default=None),
        "refused_pairs": pub.get("refused_pairs", {}),
        "failed_downloads": len(pub.get("failed_downloads", [])),
        "pairs": [{"a": c["a"], "b": c["b"], "ratio": c.get("flux_ratio"), "sig": c.get("significance"),
                   "changed": bool(c.get("changed")),
                   "control_ratio": (c.get("control_star") or {}).get("ratio")} for c in comps],
        "archive_queries": pub.get("archive_queries", []),
    }


def from_evidence(obj: dict, root: Path = ROOT) -> dict:
    ev = json.loads((root / obj["evidence"]).read_text())
    if obj["category"] == "known_asteroid":
        if "evidence_index" in obj:
            case = ev["validation_cases"][obj["evidence_index"]]
            ok = bool(case.get("linked"))
            res = case.get("residuals_vs_horizons_spherex_arcsec", {})
        else:
            ok = any(t.get("matches_horizons") for t in ev["blind_search"]["tracks"])
            res = ev["residuals_vs_horizons_spherex_arcsec"]
        first = next(iter(res.values()), {}) if isinstance(res, dict) else {}
        return {"status": "measured", "source": obj["evidence"], "recovered": ok,
                "median_residual_arcsec": first.get("median_total") if isinstance(first, dict) else None}
    return {"status": "measured", "source": obj["evidence"]} | summarize(ev)


def run_archive_object(obj: dict, budget: Budget, online: bool, refresh: bool = False) -> dict:
    out = CACHE / "results" / f"{obj['id']}.json"
    if out.exists() and not refresh:
        return {"status": "measured", "source": str(out.relative_to(ROOT))} | summarize(json.loads(out.read_text()))
    if obj.get("ra") is None:
        return {"status": "no_coordinates", "note": "run `run_benchmark.py resolve` first"}

    orig_query, orig_fetch, orig_dir = archive.query, cutouts.fetch, cutouts.CACHE_DIR

    def offline_fetch(access_url, ra, dec, size=cutouts.DEFAULT_SIZE_DEG, **k):
        p = cutouts.CACHE_DIR / f"{cutouts._key(access_url, ra, dec, size)}.fits"
        if not p.exists():
            raise RuntimeError("cutout not cached (offline run)")
        return orig_fetch(access_url, ra, dec, size, **k)

    archive.query = lambda ra, dec, **k: sia_query(ra, dec, budget, online)
    cutouts.CACHE_DIR = CACHE / "cutouts"
    if not online:
        cutouts.fetch = offline_fetch
    try:
        t0 = time.monotonic()
        r = pipeline.analyze(obj["ra"], obj["dec"], obj["detector"])
    except Blocked as e:
        return {"status": BLOCKED, "url": e.url, "attempts": e.attempts}
    except FileNotFoundError as e:
        return {"status": "not_cached_offline", "note": str(e)}
    finally:
        archive.query, cutouts.fetch, cutouts.CACHE_DIR = orig_query, orig_fetch, orig_dir

    from hipparchus.api import _public
    pub = _public(r)
    pub["run"] = {"utc": now(), "seconds": round(time.monotonic() - t0, 1)}
    s = summarize(pub)
    if pub["n_epochs"] == 0 and s["failed_downloads"]:
        # every cutout failed: the archive listed data we could not fetch
        return {"status": BLOCKED, "url": "IRSA IBE cutouts",
                "attempts": [{"url": f["obs"]["access_url"], "error": f["error"], "utc": pub["run"]["utc"]}
                             for f in pub["failed_downloads"]]}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pub, indent=1))
    return {"status": "measured", "source": str(out.relative_to(ROOT))} | s


# ---------------------------------------------------------------- metrics

def outcome(obj: dict, r: dict) -> str | None:
    """TP / FN / FP / TN / refused_ok / ... for one measured object; None if not testable."""
    if r.get("status") != "measured":
        return None
    cat = obj["category"]
    if cat == "known_asteroid":
        return "recovered" if r["recovered"] else "missed"
    if cat == "saturated":
        if r["n_valid_pairs"] == 0:
            return "refused_ok"
        return "FP" if r["n_changed"] else "not_refused"
    if r["n_valid_pairs"] == 0:
        return "no_valid_pair"
    if cat == "known_variable":
        return "TP" if r["n_changed"] else "FN"
    return "FP" if r["n_changed"] else "TN"   # stable_control, low_snr


def metrics(objects: list[dict], results: dict, splits=("dev", "calibration", "held_out")) -> dict:
    sel = [o for o in objects if o["split"] in splits]
    oc = {o["id"]: outcome(o, results.get(o["id"], {})) for o in sel}
    by = lambda cat, *v: sum(1 for o in sel if o["category"] == cat and oc[o["id"]] in v)  # noqa: E731
    tp, fn = by("known_variable", "TP"), by("known_variable", "FN")
    fp_stable, tn_stable = by("stable_control", "FP"), by("stable_control", "TN")
    fp_low, tn_low = by("low_snr", "FP"), by("low_snr", "TN")
    fp_sat = by("saturated", "FP")
    fp_all = fp_stable + fp_low + fp_sat

    stable_pairs = [p for o in sel if o["category"] == "stable_control" and oc[o["id"]] in ("TN", "FP")
                    for p in results[o["id"]]["pairs"]]
    ctrl = [p["control_ratio"] - 1 for o in sel if oc[o["id"]] in ("TP", "FN", "TN", "FP")
            for p in results[o["id"]]["pairs"] if p.get("control_ratio") is not None]
    sigs = [p["sig"] for p in stable_pairs if p["sig"] is not None]
    counts = {}
    for o in sel:
        st = results.get(o["id"], {}).get("status", "not_run")
        counts.setdefault(o["category"], {}).setdefault(st, 0)
        counts[o["category"]][st] += 1
    return {
        "splits": list(splits),
        "objects_by_status": counts,
        "completeness": wilson(tp, tp + fn) | {"note": "known variables with >= 1 valid pair; a variable may simply not have varied between the SPHEREx visits, so this is a lower bound"},
        "precision": wilson(tp, tp + fp_all),
        "false_positive_rate_objects_stable": wilson(fp_stable, fp_stable + tn_stable),
        "false_positive_rate_objects_low_snr": wilson(fp_low, fp_low + tn_low),
        "false_positive_rate_pairs_stable": wilson(sum(p["changed"] for p in stable_pairs), len(stable_pairs))
        | {"note": "pairs of one object share epochs, so they are not independent"},
        "saturated_refusal_rate": wilson(by("saturated", "refused_ok"), by("saturated", "refused_ok", "not_refused", "FP")),
        "asteroid_recovery": wilson(by("known_asteroid", "recovered"), by("known_asteroid", "recovered", "missed")),
        "photometric_bias_stable_pairs": robust_bias([p["ratio"] - 1 for p in stable_pairs if p["ratio"] is not None])
        | {"what": "median(flux_b / flux_a - 1) over valid pairs of stable controls"},
        "photometric_bias_control_stars": robust_bias(ctrl)
        | {"what": "same, for the in-field control star of every valid pair of every measured star target"},
        "significance_stable_pairs": {"n": len(sigs), "mean": statistics.fmean(sigs) if sigs else None,
                                      "std": statistics.pstdev(sigs) if len(sigs) > 1 else None},
        "outcomes": oc,
    }


# ---------------------------------------------------------------- main

def cmd_resolve(m: dict) -> None:
    for o in m["objects"]:
        if o["source"] != "archive" or o.get("ra") is not None:
            continue
        try:
            o.update(resolve(o.get("simbad_query", o["name"])))
            print(o["id"], o["ra"], o["dec"])
        except Exception as e:  # one bad name must not stop the rest
            o["resolve_error"] = f"{now()} {e}"
            print(o["id"], "FAILED", e)
    MANIFEST.write_text(json.dumps(m, indent=1))


def cmd_run(m: dict, online: bool, budget_s: float, only: set[str] | None, refresh: bool) -> dict:
    budget = Budget(budget_s)
    results, log = {}, {"started_utc": now(), "online": online, "budget_s": budget_s}
    for o in m["objects"]:
        if only and o["id"] not in only:
            continue
        if o["source"] == "published_evidence":
            results[o["id"]] = from_evidence(o)
        else:
            results[o["id"]] = run_archive_object(o, budget, online, refresh)
        print(o["id"], o["split"], o["category"], results[o["id"]]["status"],
              results[o["id"]].get("n_valid_pairs"), results[o["id"]].get("n_changed"), flush=True)
    log["finished_utc"] = now()
    blocked = {k: {"url": v["url"], "attempts": v["attempts"]} for k, v in results.items() if v["status"] == BLOCKED}
    report = {
        "generated_at": now(), "label": "REAL SPHEREx data (no simulations in this benchmark)",
        "manifest": str(MANIFEST.relative_to(ROOT)),
        "manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        "run": log,
        "metrics": {"all": metrics(m["objects"], results),
                    "held_out": metrics(m["objects"], results, ("held_out",)),
                    "calibration": metrics(m["objects"], results, ("calibration",)),
                    "dev": metrics(m["objects"], results, ("dev",))},
        "blocked": blocked,
        "objects": {k: {kk: vv for kk, vv in v.items() if kk not in ("pairs",)} for k, v in results.items()},
    }
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", nargs="?", default="run", choices=["run", "resolve"])
    ap.add_argument("--online", action="store_true", help="query IRSA and download missing cutouts")
    ap.add_argument("--budget-min", type=float, default=DEFAULT_BUDGET_S / 60, help="total retry budget")
    ap.add_argument("--only", help="comma-separated object ids")
    ap.add_argument("--refresh", action="store_true", help="ignore cached results")
    a = ap.parse_args(argv)
    m = json.loads(MANIFEST.read_text())
    if a.command == "resolve":
        return cmd_resolve(m)
    rep = cmd_run(m, a.online, a.budget_min * 60, set(a.only.split(",")) if a.only else None, a.refresh)
    (OUT_DIR / "results.json").write_text(json.dumps(rep, indent=1))
    h = rep["metrics"]["all"]
    print("completeness", h["completeness"]["k"], "/", h["completeness"]["n"],
          "FPR(stable)", h["false_positive_rate_objects_stable"]["k"], "/", h["false_positive_rate_objects_stable"]["n"],
          "blocked", len(rep["blocked"]))


if __name__ == "__main__":
    main()
