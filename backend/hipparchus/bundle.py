"""Reproduction bundles: one small, self-contained package per validated case.

A bundle holds the evidence JSON for the case, a manifest of every dataset DOI,
archive query and cutout URL with its sha256, the pinned environment, the exact
commands, the sha256 of each source file the result came from, the parameters,
figures and the mini report. It holds no FITS data: the archive links are
enough, and IRSA's terms ask us to point to the data rather than copy it.

`verify` replays the manifest. From the local cache by default, or with
network=True (opt-in) from the archive itself. A checksum that changed is
reported as DRIFT with both values: it means IRSA reprocessed or replaced the
file, and the published numbers were computed from the old one.

This file uses only the standard library, so the copy inside each bundle runs
anywhere:  python tools/bundle.py verify <bundle.zip or dir> [--network]
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "submission" / "evidence"
BUNDLE_DIR = ROOT / "submission" / "bundles"

DOI_LANDING = {
    "10.26131/IRSA678": "SPHEREx DR1 (spherex_dr1), NASA/IPAC Infrared Science Archive",
    "10.26131/IRSA662": "SPHEREx Quick Release 3 (spherex_qr3), NASA/IPAC Infrared Science Archive",
}

# Code behind each case. We record the sha256 of these files instead of a
# commit id, so anyone can check that their copy is the one we ran.
_STATIC_CODE = ["hipparchus/__init__.py", "hipparchus/archive.py", "hipparchus/cutouts.py",
                "hipparchus/quality.py", "hipparchus/compare.py", "hipparchus/pipeline.py",
                "hipparchus/api.py", "hipparchus/graph.py", "hipparchus/compat.py",
                "hipparchus/robustness.py", "hipparchus/validation.py"]

CASES = {
    "rw_aur": {
        "title": "RW Aurigae: a real brightness change",
        "kind": "change", "target_id": "rw_aur",
        "evidence": "rw_aur_spherex-d1.json", "graph": "graph_rw_aur_spherex-d1.json",
        "code": _STATIC_CODE + ["scripts/reproduce_evidence.py", "scripts/reproduce_validation.py",
                                "scripts/reproduce_robustness.py", "scripts/reproduce_compat.py"],
        "commands": ["cd backend", "python -m venv .venv && .venv/bin/pip install -r ../environment/requirements-freeze.txt",
                     ".venv/bin/pip install -e .",
                     ".venv/bin/python scripts/reproduce_evidence.py      # rewrites submission/evidence/<target>.json",
                     ".venv/bin/python scripts/reproduce_validation.py    # null tests + SIMULATED injections",
                     ".venv/bin/python scripts/reproduce_robustness.py    # aperture/annulus/mask grid",
                     ".venv/bin/python -m hipparchus.bundle verify ../submission/bundles/rw_aur.zip"],
    },
    "barnard": {
        "title": "Barnard's Star: the tool refuses a saturated star",
        "kind": "change", "target_id": "barnard",
        "evidence": "barnard_spherex-d6.json", "graph": "graph_barnard_spherex-d6.json",
        "code": _STATIC_CODE + ["scripts/reproduce_evidence.py", "scripts/reproduce_validation.py",
                                "scripts/reproduce_robustness.py", "scripts/reproduce_compat.py"],
        "commands": ["cd backend", "python -m venv .venv && .venv/bin/pip install -r ../environment/requirements-freeze.txt",
                     ".venv/bin/pip install -e .",
                     ".venv/bin/python scripts/reproduce_evidence.py",
                     ".venv/bin/python -m hipparchus.bundle verify ../submission/bundles/barnard.zip"],
    },
    "wise0855": {
        "title": "WISE 0855-0714: no change at the limit of the data",
        "kind": "change", "target_id": "wise0855",
        "evidence": "wise0855_spherex-d6.json", "graph": "graph_wise0855_spherex-d6.json",
        "code": _STATIC_CODE + ["scripts/reproduce_evidence.py", "scripts/reproduce_validation.py",
                                "scripts/reproduce_robustness.py", "scripts/reproduce_compat.py"],
        "commands": ["cd backend", "python -m venv .venv && .venv/bin/pip install -r ../environment/requirements-freeze.txt",
                     ".venv/bin/pip install -e .",
                     ".venv/bin/python scripts/reproduce_evidence.py",
                     ".venv/bin/python scripts/reproduce_validation.py",
                     ".venv/bin/python -m hipparchus.bundle verify ../submission/bundles/wise0855.zip"],
    },
    "kleopatra": {
        "title": "(216) Kleopatra: motion of a known asteroid against JPL Horizons",
        "kind": "motion",
        "evidence": "motion_check.json",
        "code": ["hipparchus/__init__.py", "hipparchus/archive.py", "hipparchus/cutouts.py",
                 "hipparchus/quality.py", "hipparchus/motion.py", "scripts/reproduce_motion.py"],
        "commands": ["cd backend", "python -m venv .venv && .venv/bin/pip install -r ../environment/requirements-freeze.txt",
                     ".venv/bin/pip install -e .",
                     ".venv/bin/python scripts/reproduce_motion.py       # ~17 min; Horizons + IRSA",
                     ".venv/bin/python -m hipparchus.bundle verify ../submission/bundles/kleopatra.zip"],
    },
}


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(Path(p).read_bytes())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- what goes in

def evidence_subset(case: str, evidence_dir: Path = EVIDENCE) -> dict[str, dict]:
    """The evidence files of one case, plus the slices of the shared files that
    belong to it. Each slice says which file it came from and that file's sha256."""
    spec = CASES[case]
    out: dict[str, dict] = {}
    main = evidence_dir / spec["evidence"]
    out[spec["evidence"]] = json.loads(main.read_text())
    if spec["kind"] == "motion":
        return out
    tid = spec["target_id"]
    out[spec["graph"]] = json.loads((evidence_dir / spec["graph"]).read_text())

    def piece(fname, pick):
        p = evidence_dir / fname
        if not p.exists():
            return
        full = json.loads(p.read_text())
        out[f"subset_{fname}"] = {"extracted_from": f"submission/evidence/{fname}",
                                  "source_sha256": sha256_file(p), "content": pick(full)}

    piece("validation.json", lambda v: {"generated_at": v.get("generated_at"), "code_commit": v.get("code_commit"),
                                        "note": v.get("note"),
                                        "target": next(t for t in v["targets"] if t["id"] == tid)})
    piece("robustness.json", lambda r: {"settings": r["settings"], "target": r["targets"][tid]})
    piece("compat_check.json", lambda c: {"assumption": c.get("assumption"), "rule": c.get("rule"),
                                          "target": c["targets"][tid]})
    piece("evidence_manifest.json", lambda m: {"generated_at": m["generated_at"], "code_commit": m["code_commit"],
                                               "config": m["config"],
                                               "case": next(x for x in m["cases"] if x["file"].endswith(spec["evidence"]))})
    return out


def data_manifest(case: str, ev: dict[str, dict]) -> dict:
    """Every external input of the case: DOIs, archive queries, cutouts, ephemerides."""
    spec = CASES[case]
    main = ev[spec["evidence"]]
    queries, cutouts, dois, external = [], [], {}, []
    if spec["kind"] == "change":
        for q in main["archive_queries"]:
            queries.append({"kind": "sia_votable", "release": q["release"], "url": q["url"], "sha256": q["sha256"]})
        for e in main["epochs"]:
            o, c = e["provenance"]["obs"], e["provenance"].get("cutout")
            dois[o["doi"]] = dois.get(o["doi"], 0) + 1
            if c:
                cutouts.append({"kind": "fits_cutout", "obs_id": o["obs_id"], "release": o["release"],
                                "publisher_did": o["publisher_did"], "url": c["url"], "sha256": c["sha256"]})
        params = main["config"]
    else:
        for q in main["archive"]["queries"]:
            queries.append({"kind": "sia_votable", "release": q["release"], "url": q["url"], "sha256": q["sha256"]})
        for e in main["exposures"]:
            dois[e["doi"]] = dois.get(e["doi"], 0) + 1
            cutouts.append({"kind": "fits_cutout", "obs_id": e["obs_id"], "release": e["release"],
                            "url": e["cutout_url"], "sha256": e["cutout_sha256"]})
        hz = main["horizons"]
        for u in hz.get("query_urls_spherex", []) + hz.get("query_urls_geocentric", []):
            # The ephemeris text was not checksummed at run time; a replay can
            # compare positions, not bytes.
            external.append({"kind": "jpl_horizons", "url": u, "sha256": None})
        params = {"settings": main["settings"], "field": main["field"]}
    return {
        "datasets": [{"doi": d, "url": f"https://doi.org/{d}", "title": DOI_LANDING.get(d, ""), "n_files": n}
                     for d, n in sorted(dois.items())],
        "archive_queries": queries, "cutouts": cutouts, "external": external, "parameters": params,
    }


def environment(root: Path = ROOT) -> dict[str, str]:
    """pyproject plus the exact package versions of the venv we ran in."""
    import subprocess
    files = {"environment/pyproject.toml": (root / "backend" / "pyproject.toml").read_text()}
    py = root / "backend" / ".venv" / "bin" / "python"
    try:
        freeze = subprocess.run([str(py), "-m", "pip", "freeze", "--exclude-editable"],
                                capture_output=True, text=True, timeout=120).stdout
        pyv = subprocess.run([str(py), "--version"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError) as e:
        freeze, pyv = f"# pip freeze unavailable: {e}\n", ""
    files["environment/requirements-freeze.txt"] = freeze
    files["environment/python-version.txt"] = pyv
    return files


# ---------------------------------------------------------------- building

def _readme(case: str, man: dict) -> str:
    spec = CASES[case]
    lines = [f"HIPPARCHUS reproduction bundle: {spec['title']}", "",
             f"Built {man['built_at']} from the published evidence (nothing recomputed).",
             "No FITS data inside: every input is a link with its sha256 in manifest.json.", "",
             "Check the bundle against your cache, or (slow, opt-in) against the archive:",
             "    python tools/bundle.py verify .            # cache only",
             "    python tools/bundle.py verify . --network  # re-download and compare checksums", "",
             "Rerun the analysis from the repository:"] + ["    " + c for c in spec["commands"]] + [
             "", "Files:", "  evidence/       evidence JSON of this case (and slices of the shared files)",
             "  environment/    pyproject.toml, pip freeze, python version",
             "  figures/        figures drawn from the evidence", "  report.html     mini scientific report",
             "  manifest.json   DOIs, URLs, checksums, parameters, source-file checksums, commands", ""]
    return "\n".join(lines)


def build(case: str, out_dir: Path = BUNDLE_DIR, root: Path = ROOT, evidence_dir: Path | None = None,
          with_report: bool = True, with_env: bool = True) -> Path:
    """Write submission/bundles/<case>.zip and return its path."""
    evidence_dir = evidence_dir or root / "submission" / "evidence"
    spec = CASES[case]
    ev = evidence_subset(case, evidence_dir)
    files: dict[str, bytes] = {f"evidence/{k}": json.dumps(v, indent=1).encode() for k, v in ev.items()}
    if with_env:
        files |= {k: v.encode() for k, v in environment(root).items()}
    if with_report:
        from hipparchus import minireport
        files["report.html"] = minireport.render_html(case, evidence_dir).encode()
        for name, png in minireport.figures(case, evidence_dir).items():
            files[f"figures/{name}.png"] = png
    files["tools/bundle.py"] = Path(__file__).read_bytes()

    src = []
    for rel in spec["code"]:
        p = root / "backend" / rel
        if p.exists():
            src.append({"path": f"backend/{rel}", "sha256": sha256_file(p)})
    main = ev[spec["evidence"]]
    man = {
        "case": case, "title": spec["title"], "built_at": _now(),
        "built_from": "published evidence in submission/evidence (cached, not recomputed)",
        "evidence_files": [{"path": f"submission/evidence/{spec['evidence']}",
                            "sha256": sha256_file(evidence_dir / spec["evidence"])}],
        # The commit the evidence itself recorded when it was produced; we did
        # not query version control while building the bundle.
        "code_commit_recorded_in_evidence": (ev.get("subset_evidence_manifest.json", {})
                                             .get("content", {}).get("code_commit")),
        "source_files": src,
        "commands": spec["commands"],
        "files": {k: sha256_bytes(v) for k, v in sorted(files.items())},
        "run": main.get("run"),
    } | data_manifest(case, ev)
    files["manifest.json"] = json.dumps(man, indent=1).encode()
    files["README.txt"] = _readme(case, man).encode()

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{case}.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            # fixed timestamp, so the same content gives the same zip bytes
            zi = zipfile.ZipInfo(f"{case}/{name}", date_time=(2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, files[name])
    path.write_bytes(buf.getvalue())
    return path


# ---------------------------------------------------------------- verifying

class _Bundle:
    """Read a bundle from a zip or an unpacked directory alike."""

    def __init__(self, path: Path):
        self.path = Path(path)
        if self.path.is_file():
            self.z = zipfile.ZipFile(self.path)
            names = self.z.namelist()
            self.prefix = names[0].split("/")[0] + "/" if names and "/" in names[0] else ""
        else:
            self.z = None
            self.prefix = ""
            if not (self.path / "manifest.json").exists():
                subs = [d for d in self.path.iterdir() if (d / "manifest.json").exists()]
                if subs:
                    self.path = subs[0]

    def read(self, name: str) -> bytes:
        if self.z:
            return self.z.read(self.prefix + name)
        return (self.path / name).read_bytes()


def cache_index(cache_dir: Path) -> dict[str, Path]:
    """URL -> local file, from the sidecars the pipeline writes next to each cutout,
    and from the raw SIA answers kept by the motion and benchmark scripts."""
    idx: dict[str, Path] = {}
    for d in [cache_dir, cache_dir / "benchmark" / "cutouts"]:
        if not d.is_dir():
            continue
        for meta in d.glob("*.json"):
            try:
                url = json.loads(meta.read_text())["url"]
            except (ValueError, KeyError, OSError):
                continue
            fits = meta.with_suffix(".fits")
            if fits.exists():
                idx[url] = fits
    return idx


def _sia_cached(cache_dir: Path, url: str) -> Path | None:
    key = hashlib.sha256(url.encode()).hexdigest()[:24] + ".xml"
    for d in (cache_dir / "sia", cache_dir / "benchmark" / "sia"):
        if (d / key).exists():
            return d / key
    return None


def http_fetch(url: str, timeout: float = 180.0, tries: int = 4) -> bytes:
    """Plain GET with growing pauses (IRSA answers 502 now and then)."""
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hipparchus-verify"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if k < tries - 1:
                time.sleep(10 * 2 ** k)
    raise ConnectionError(f"{url}: {last}")


DRIFT_NOTE = ("checksum differs from the one recorded when the evidence was built: the archive "
              "reprocessed or replaced this product. The published numbers came from the old version.")


def verify(bundle_path, network: bool = False, cache_dir: Path | None = None, fetch=None,
           root: Path | None = ROOT, limit: int | None = None) -> dict:
    """Replay a bundle and say, item by item, what still matches.

    Statuses: match, DRIFT (changed checksum, never hidden), not_cached (cache
    mode, nothing local), unreachable (network mode), no_checksum (ephemeris).
    """
    b = _Bundle(Path(bundle_path))
    man = json.loads(b.read("manifest.json"))
    cache_dir = Path(cache_dir) if cache_dir else (root / "data" / "cache" if root else None)
    fetch = fetch or http_fetch
    report = {"case": man["case"], "checked_at": _now(), "mode": "network" if network else "cache",
              "bundle_files": [], "items": [], "source_files": []}

    for name, want in man["files"].items():
        try:
            got = sha256_bytes(b.read(name))
        except (KeyError, FileNotFoundError):
            got = None
        report["bundle_files"].append({"file": name, "status": "match" if got == want else ("missing" if got is None else "DRIFT")})

    idx = cache_index(cache_dir) if (cache_dir and not network) else {}
    items = man["archive_queries"] + man["cutouts"]
    if limit:
        items = items[:limit]
    for it in items:
        rec = {"kind": it["kind"], "url": it["url"], "expected_sha256": it["sha256"]}
        if network:
            rec["fetched_at"] = _now()
            try:
                data = fetch(it["url"])
            except Exception as e:  # report and keep going; one dead link is a finding
                report["items"].append(rec | {"status": "unreachable", "error": str(e)})
                continue
        else:
            local = _sia_cached(cache_dir, it["url"]) if (cache_dir and it["kind"] == "sia_votable") else idx.get(it["url"])
            if local is None:
                report["items"].append(rec | {"status": "not_cached"})
                continue
            rec["local_file"] = str(local)
            data = local.read_bytes()
        got = sha256_bytes(data)
        rec["got_sha256"] = got
        rec["status"] = "match" if got == it["sha256"] else "DRIFT"
        if rec["status"] == "DRIFT":
            rec["note"] = DRIFT_NOTE
        report["items"].append(rec)
    for it in man.get("external", []):
        report["items"].append({"kind": it["kind"], "url": it["url"], "status": "no_checksum"})

    if root:
        for s in man["source_files"]:
            p = root / s["path"]
            got = sha256_file(p) if p.exists() else None
            report["source_files"].append({"path": s["path"], "status": "match" if got == s["sha256"]
                                           else ("missing" if got is None else "changed_since_bundle")})

    def count(rows):
        c: dict[str, int] = {}
        for r in rows:
            c[r["status"]] = c.get(r["status"], 0) + 1
        return c
    report["summary"] = {"bundle_files": count(report["bundle_files"]), "data": count(report["items"]),
                         "source_files": count(report["source_files"])}
    report["ok"] = (all(r["status"] == "match" for r in report["bundle_files"])
                    and not any(r["status"] == "DRIFT" for r in report["items"]))
    return report


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="bundle", description="build or verify reproduction bundles")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify")
    v.add_argument("bundle")
    v.add_argument("--network", action="store_true", help="re-download every item (slow)")
    v.add_argument("--cache", help="cache directory (default: data/cache of the repository)")
    v.add_argument("--limit", type=int)
    bb = sub.add_parser("build")
    bb.add_argument("cases", nargs="*", default=list(CASES))
    a = ap.parse_args(argv)
    if a.cmd == "build":
        for c in a.cases:
            print(build(c))
        return 0
    root = ROOT if (ROOT / "backend" / "hipparchus").exists() else None
    r = verify(a.bundle, network=a.network, cache_dir=Path(a.cache) if a.cache else None, root=root, limit=a.limit)
    for row in r["items"]:
        if row["status"] != "match":
            print(row["status"], row["url"], row.get("note", row.get("error", "")))
    print(json.dumps(r["summary"], indent=1))
    print("OK" if r["ok"] else "NOT OK")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
