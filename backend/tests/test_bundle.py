"""Reproduction bundles, offline: built from the evidence, replayed against a
fake cache made of our FITS fixtures."""

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from hipparchus import bundle

FIX = Path(__file__).parent / "fixtures"
EVID = bundle.EVIDENCE


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


@pytest.fixture
def evidence_copy(tmp_path):
    """A copy of the evidence where epoch 0 of RW Aur points at our fixture file,
    so a cache made of fixtures can give a real match."""
    d = tmp_path / "evidence"
    d.mkdir()
    for f in ("rw_aur_spherex-d1.json", "graph_rw_aur_spherex-d1.json", "validation.json",
              "robustness.json", "compat_check.json", "evidence_manifest.json", "motion_check.json"):
        shutil.copy(EVID / f, d / f)
    ev = json.loads((d / "rw_aur_spherex-d1.json").read_text())
    ev["epochs"][0]["provenance"]["cutout"]["sha256"] = _sha(FIX / "rwaur_d1_2025.fits")
    (d / "rw_aur_spherex-d1.json").write_text(json.dumps(ev, indent=1))
    return d, ev


def _build(tmp_path, evidence_dir, case="rw_aur"):
    return bundle.build(case, out_dir=tmp_path / "out", evidence_dir=evidence_dir, with_env=False, with_report=False)


def _fake_cache(tmp_path, items):
    c = tmp_path / "cache"
    c.mkdir()
    for i, (url, src) in enumerate(items):
        shutil.copy(src, c / f"k{i}.fits")
        (c / f"k{i}.json").write_text(json.dumps({"url": url, "sha256": _sha(src)}))
    return c


def test_bundle_has_no_fits_and_full_provenance(tmp_path):
    z = _build(tmp_path, EVID)
    names = zipfile.ZipFile(z).namelist()
    assert not any(n.lower().endswith((".fits", ".fit", ".fz")) for n in names)
    man = json.loads(zipfile.ZipFile(z).read("rw_aur/manifest.json"))
    ev = json.loads((EVID / "rw_aur_spherex-d1.json").read_text())
    assert len(man["cutouts"]) == len(ev["epochs"])
    assert all(len(c["sha256"]) == 64 and c["url"].startswith("https://") for c in man["cutouts"])
    assert {d["doi"] for d in man["datasets"]} == {e["provenance"]["obs"]["doi"] for e in ev["epochs"]}
    assert [q["sha256"] for q in man["archive_queries"]] == [q["sha256"] for q in ev["archive_queries"]]
    assert man["parameters"] == ev["config"]
    assert man["source_files"] and all(len(s["sha256"]) == 64 for s in man["source_files"])
    assert man["evidence_files"][0]["sha256"] == _sha(EVID / "rw_aur_spherex-d1.json")
    # the evidence inside is the published evidence, unchanged
    assert json.loads(zipfile.ZipFile(z).read("rw_aur/evidence/rw_aur_spherex-d1.json")) == ev


def test_motion_bundle_lists_horizons_without_checksum(tmp_path):
    z = _build(tmp_path, EVID, "kleopatra")
    man = json.loads(zipfile.ZipFile(z).read("kleopatra/manifest.json"))
    assert man["external"] and all(e["kind"] == "jpl_horizons" and e["sha256"] is None for e in man["external"])
    assert len(man["cutouts"]) == len(json.loads((EVID / "motion_check.json").read_text())["exposures"])


def test_verify_cache_match_drift_and_missing(tmp_path, evidence_copy):
    d, ev = evidence_copy
    z = _build(tmp_path, d)
    url0 = ev["epochs"][0]["provenance"]["cutout"]["url"]
    url1 = ev["epochs"][1]["provenance"]["cutout"]["url"]
    # epoch 1 in the cache holds different bytes: what a reprocessed product looks like
    cache = _fake_cache(tmp_path, [(url0, FIX / "rwaur_d1_2025.fits"), (url1, FIX / "rwaur_d1_2026.fits")])
    r = bundle.verify(z, cache_dir=cache, root=None)
    by = {i["url"]: i for i in r["items"]}
    assert by[url0]["status"] == "match"
    assert by[url1]["status"] == "DRIFT"
    assert by[url1]["expected_sha256"] != by[url1]["got_sha256"]
    assert "reprocessed" in by[url1]["note"]
    assert r["summary"]["data"]["not_cached"] == len(r["items"]) - 2
    assert r["ok"] is False   # drift is never hidden behind an OK


def test_verify_network_mode_with_fake_fetch(tmp_path, evidence_copy):
    d, ev = evidence_copy
    z = _build(tmp_path, d)
    url0 = ev["epochs"][0]["provenance"]["cutout"]["url"]

    def fetch(url):
        if url == url0:
            return (FIX / "rwaur_d1_2025.fits").read_bytes()
        raise ConnectionError("HTTP 502")

    r = bundle.verify(z, network=True, fetch=fetch, root=None)
    st = {i["url"]: i["status"] for i in r["items"]}
    assert st[url0] == "match"
    assert set(st.values()) == {"match", "unreachable"}
    assert all("fetched_at" in i for i in r["items"])


def test_tampered_bundle_is_caught(tmp_path):
    z = _build(tmp_path, EVID)
    unpacked = tmp_path / "u"
    zipfile.ZipFile(z).extractall(unpacked)
    f = unpacked / "rw_aur" / "evidence" / "rw_aur_spherex-d1.json"
    f.write_text(f.read_text().replace('"changed": true', '"changed": false', 1))
    r = bundle.verify(unpacked, cache_dir=tmp_path, root=None)
    assert not r["ok"]
    assert any(b["status"] == "DRIFT" for b in r["bundle_files"])


def test_prebuilt_bundles_match_published_evidence():
    # the zips committed under submission/bundles must carry the current evidence
    for case, spec in bundle.CASES.items():
        z = bundle.BUNDLE_DIR / f"{case}.zip"
        if not z.exists():
            pytest.skip("bundles not built yet")
        man = json.loads(zipfile.ZipFile(z).read(f"{case}/manifest.json"))
        assert man["evidence_files"][0]["sha256"] == _sha(EVID / spec["evidence"])
