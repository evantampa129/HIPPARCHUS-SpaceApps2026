"""Side-by-side audit: WCS-WAVE wavelengths versus the CWAVE/CBAND calibration.

Writes submission/evidence/wavecal_check.json. Runs offline on the cached
cutouts and archive manifests (as reproduce_robustness.py does) plus the
Spectral WCS calibration files in data/cache/calibration (fetched with
spectral_cal.download if missing). It does not change the production code
or any published evidence file; it only reports what would change.

Three wavelength readings are compared at every epoch's target pixel:
  production  astropy WCS(key="W"), exactly as quality.py reads it
  table       the same WCS-WAVE table, bilinear between control points (IRSA recipe)
  calibrated  CWAVE/CBAND maps of the Spectral WCS product (what IRSA recommends)
"""

import dataclasses
import glob
import hashlib
import json
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

import numpy as np
from astropy.io import fits

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
# Importing the robustness script also routes archive.query to the saved
# manifests, so this audit sees exactly the exposures behind the published results.
import reproduce_robustness as RR  # noqa: E402
from hipparchus import api, archive, compare as C, cutouts, pipeline, psf_photometry as P  # noqa: E402
from hipparchus import spectral_cal as S  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "submission" / "evidence" / "wavecal_check.json"

# What the published texts state; the audit says whether each still holds.
PUBLISHED = {"rw_aur": "8 valid pairs, max flux ratio 2.56, every pair brighter later, max sig >= 5",
             "wise0855": "27 valid pairs, none changes by >= 5 sigma",
             "barnard": "refused: no usable epoch"}


def stats(v):
    v = np.abs(np.asarray([x for x in v if x is not None and np.isfinite(x)], float))
    if not v.size:
        return None
    return {"n": int(v.size), "median": float(np.median(v)), "max": float(v.max())}


_PIXELS: dict = {}


def decision(a, b):
    """Pair decision as pipeline.analyze makes it: refused / null_test / comparison (+ numbers)."""
    v = C.compatibility(a, b)
    if not v.comparable:
        return {"kind": "refused", "codes": sorted(set(v.codes))}
    # The pixel part of compare() does not depend on the wavelength, so we run
    # it once per pair and reuse it for every wavelength variant.
    key = (a.obs_id, b.obs_id)
    if key not in _PIXELS:
        _PIXELS[key] = C.compare(a, b)
    c = _PIXELS[key]
    if not c["verdict"]["comparable"]:
        return {"kind": "refused", "codes": sorted(set(c["verdict"]["codes"]))}
    return {"kind": v.kind, "ratio": c["flux_ratio"], "sig": c["significance"]}


def with_wave(ep, lam, dlam):
    return dataclasses.replace(ep, wavelength_um=lam, bandwidth_um=dlam)


def summary(rows):
    comps = [r for r in rows if r["kind"] == "comparison"]
    return {"n_valid_pairs": len(comps), "n_null_tests": sum(r["kind"] == "null_test" for r in rows),
            "max_ratio": max((r["ratio"] for r in comps if r["ratio"] is not None), default=None),
            "max_abs_sig": max((abs(r["sig"]) for r in comps), default=None),
            "refusal_codes": dict(Counter(c for r in rows if r["kind"] == "refused" for c in r["codes"]))}


def audit_target(t):
    det = int(t["detector"].split("D")[-1])
    for_det = [o for o in archive.query(t["ra"], t["dec"])["observations"] if o["detector"] == t["detector"]]
    loaded = pipeline.load_epochs(t["ra"], t["dec"], t["detector"])
    epochs = sorted(loaded["epochs"], key=lambda e: e.mjd)
    url = {o["obs_id"]: o["access_url"] for o in for_det}
    cal = S.load(det)
    per_epoch, variants = [], {"production": {}, "table": {}, "calibrated": {}}
    for e in epochs:
        path = cutouts.fetch(url[e.obs_id], t["ra"], t["dec"])["path"]
        r = S.at_target(path, e.x, e.y, cal=cal)
        # Our "production" value must be the one the pipeline used; if not, the
        # comparison below would not be about the published numbers.
        assert abs(r["wcs_wave_astropy_um"] - e.wavelength_um) < 1e-9, e.obs_id
        variants["production"][e.obs_id] = e
        variants["table"][e.obs_id] = with_wave(e, r["wcs_wave_table_um"], r["wcs_band_table_um"])
        variants["calibrated"][e.obs_id] = with_wave(e, r["wavelength_um"], r["bandwidth_um"])
        lam_c, band_c = r["wavelength_um"], r["bandwidth_um"]
        per_epoch.append({
            "obs_id": e.obs_id, "usable": e.usable, "parent_xy": r.get("parent_xy"), "source": r["source"],
            "note": r.get("note"),
            "lambda_um": {"production": e.wavelength_um, "table": r["wcs_wave_table_um"], "calibrated": lam_c},
            "band_um": {"production": e.bandwidth_um, "table": r["wcs_band_table_um"], "calibrated": band_c},
            "dlambda_nm_cal_minus_production": 1e3 * (lam_c - e.wavelength_um),
            "dlambda_nm_cal_minus_table": 1e3 * (lam_c - r["wcs_wave_table_um"]),
            "dlambda_nm_table_minus_production": 1e3 * (r["wcs_wave_table_um"] - e.wavelength_um),
            "dband_nm_cal_minus_production": 1e3 * (band_c - e.bandwidth_um),
            "dlambda_over_cband_cal_minus_production": (lam_c - e.wavelength_um) / band_c,
            # quality.py rejects wavelengths outside 0.7-5.1 um; we recheck with the calibrated value.
            "in_range_calibrated": bool(0.7 <= lam_c <= 5.1 and band_c > 0),
        })
    usable = [p for p in per_epoch if p["usable"]]
    diffs = {k: stats([p[k] for p in usable]) for k in (
        "dlambda_nm_cal_minus_production", "dlambda_nm_cal_minus_table", "dlambda_nm_table_minus_production",
        "dband_nm_cal_minus_production", "dlambda_over_cband_cal_minus_production")}
    diffs_all = stats([p["dlambda_nm_cal_minus_production"] for p in per_epoch])

    # Re-run the pair rule. Pixels are compared only where some variant
    # accepts the pair, since compare() never looks at the wavelength itself.
    ids = [e.obs_id for e in epochs]
    rows = {k: [] for k in variants}
    changed = []
    for ia, ib in combinations(ids, 2):
        d = {k: decision(v[ia], v[ib]) for k, v in variants.items()}
        for k in variants:
            rows[k].append(d[k])
        if d["production"]["kind"] != d["calibrated"]["kind"]:
            a0, b0 = variants["production"][ia], variants["production"][ib]
            a1, b1 = variants["calibrated"][ia], variants["calibrated"][ib]
            changed.append({
                "a": ia, "b": ib, "production": d["production"], "calibrated": d["calibrated"],
                "table": d["table"],
                "dlambda_um": {"production": abs(a0.wavelength_um - b0.wavelength_um),
                               "calibrated": abs(a1.wavelength_um - b1.wavelength_um)},
                "limit_um": {"production": C.MAX_DLAMBDA_FRACTION * min(a0.bandwidth_um, b0.bandwidth_um),
                             "calibrated": C.MAX_DLAMBDA_FRACTION * min(a1.bandwidth_um, b1.bandwidth_um)}})
    out = {"detector": t["detector"], "n_epochs": len(epochs), "n_usable": len(usable),
           "calibration": None if cal is None else {k: cal[k] for k in ("path", "sha256", "verified", "version")},
           "differences_usable_epochs": diffs, "dlambda_nm_cal_minus_production_all_epochs": diffs_all,
           "per_epoch": per_epoch, "pairs": {k: summary(v) for k, v in rows.items()},
           "changed_pairs_production_vs_calibrated": changed,
           "n_changed_pairs_production_vs_table": sum(
               a["kind"] != b["kind"] for a, b in zip(rows["production"], rows["table"]))}
    claims = RR.CLAIMS.get(t["id"], [])
    pairs = {k: [r for r in v if r["kind"] == "comparison"] for k, v in rows.items()}
    out["claims"] = {k: {txt: fn(pairs[k]) for txt, fn in claims} for k in pairs}
    return out


def epsf_layout():
    """ePSF table layout per detector over every cached cutout, and a zone-selection check."""
    rng = np.random.default_rng(0)
    out = {}
    for f in sorted(glob.glob(str(cutouts.CACHE_DIR / "*.fits"))):
        with fits.open(f) as h:
            det = int(h["IMAGE"].header["DETECTOR"])
            if "EPSF" not in h:
                out.setdefault(str(det), {}).setdefault("files_without_epsf", []).append(Path(f).name)
                continue
            t, hd = h["EPSF"].data, h["EPSF"].header
            d = out.setdefault(str(det), {"n_cutouts": 0, "tables": {}, "zone_checks": 0, "zone_failures": []})
            d["n_cutouts"] += 1
            key = hashlib.sha256(t.tobytes()).hexdigest()
            if key not in d["tables"]:
                xs, ys = np.unique(t["XCENTER"]), np.unique(t["YCENTER"])
                d["tables"][key] = {
                    "n_cutouts": 0, "rows": len(t), "n_xcenter": len(xs), "n_ycenter": len(ys),
                    "binx_range": [int(t["BINX"].min()), int(t["BINX"].max())],
                    "biny_range": [int(t["BINY"].min()), int(t["BINY"].max())],
                    "xwidth": sorted(set(np.round(t["XWIDTH"], 3).tolist())),
                    "ywidth": sorted(set(np.round(t["YWIDTH"], 3).tolist())),
                    "xcenter_range": [float(xs.min()), float(xs.max())],
                    "ycenter_range": [float(ys.min()), float(ys.max())],
                    "ovsmpx": hd.get("OVSMPX"), "ovsmpy": hd.get("OVSMPY"),
                    "detcoord": str(hd.get("DETCOORD", "")).strip(), "ordering": hd.get("ORDERING"),
                    "epsf_shape": list(np.shape(t["EPSF"][0])),
                    "source": next((str(v) for v in hd.get("HISTORY", []) if "source file" in str(v)), None)}
                # Dense check of load_epsf on the real table: 2000 random parent
                # positions; the chosen zone must be the tile that contains them.
                ih = h["IMAGE"].header
                bad = 0
                for px, py in rng.uniform(0, 2039, size=(2000, 2)):
                    e = P.load_epsf(h, px - 1 + ih["CRPIX1A"], py - 1 + ih["CRPIX2A"])
                    i = e["zone"]
                    if not (abs(px - t["XCENTER"][i]) <= t["XWIDTH"][i] / 2 + 1e-6
                            and abs(py - t["YCENTER"][i]) <= t["YWIDTH"][i] / 2 + 1e-6):
                        bad += 1
                d["tables"][key]["random_positions_checked"] = 2000
                d["tables"][key]["random_positions_wrong_zone"] = bad
            d["tables"][key]["n_cutouts"] += 1
            # The cutout centre as the star position, on every cached file.
            ny, nx = h["IMAGE"].data.shape
            e = P.load_epsf(h, (nx - 1) / 2, (ny - 1) / 2)
            d["zone_checks"] += 1
            i = None if e is None else e["zone"]
            ok = e is not None and (abs(e["parent_xy"][0] - t["XCENTER"][i]) <= t["XWIDTH"][i] / 2 + 1e-6
                                    and abs(e["parent_xy"][1] - t["YCENTER"][i]) <= t["YWIDTH"][i] / 2 + 1e-6)
            if not ok:
                d["zone_failures"].append(Path(f).name)
    for d in out.values():
        if "tables" in d:
            d["tables"] = list(d["tables"].values())
    return out


def orientation_check():
    """The EPSF zones carry CWAVE taken from the same Spectral WCS product. Comparing
    them with our map at the zone centres, as is and with x flipped, tells whether
    our indexing (map[y, x], 'sky' orientation) is the one the pipeline used."""
    out = {}
    for det in (1, 6):
        cal = S.load(det)
        f = next((f for f in sorted(glob.glob(str(cutouts.CACHE_DIR / "*.fits")))
                  if fits.getheader(f, "IMAGE").get("DETECTOR") == det), None)
        if cal is None or f is None:
            out[str(det)] = None
            continue
        t = fits.getdata(f, "EPSF")
        same = [S.bilinear(cal["cwave"], x, y) - w for x, y, w in zip(t["XCENTER"], t["YCENTER"], t["CWAVE"])]
        flip = [S.bilinear(cal["cwave"], 2039 - x, y) - w for x, y, w in zip(t["XCENTER"], t["YCENTER"], t["CWAVE"])]
        # A different calibration version shifts every zone by about the same
        # amount, so the spread (max - min) is the orientation test, not the size.
        out[str(det)] = {"zones": len(t), "epsf_source": next(
                             (str(v) for v in fits.getheader(f, "EPSF").get("HISTORY", []) if "source" in str(v)), None),
                         "abs_diff_nm_as_is": stats(1e3 * np.asarray(same)),
                         "abs_diff_nm_x_flipped": stats(1e3 * np.asarray(flip)),
                         "spread_nm_as_is": float(1e3 * (max(same) - min(same))),
                         "spread_nm_x_flipped": float(1e3 * (max(flip) - min(flip)))}
    return out


def main():
    report = {
        "status": "AUDIT - side by side; production code and published evidence unchanged",
        "rule": f"|dlambda| <= {C.MAX_DLAMBDA_FRACTION} x min(bandwidth) (compare.MAX_DLAMBDA_FRACTION)",
        "calibration_product": {
            "name": "SPHEREx Spectral WCS (CWAVE, CBAND, WCS-WAVE), one file per detector",
            "version": S.VERSION,
            "url_template": S.URL,
            "same_files_in": ["spherex_dr1", "spherex_qr3"],
            "evidence_same_version": "identical MD5 (S3 ETag) under dr1/ and qr3/ in s3://nasa-irsa-spherex",
            "md5_etag": {"D1": "624790eba5fdde40a6cb2187099e415d", "D2": "af87630c33716cd77ae54ab6c63d388d",
                         "D3": "327f973e59efeaa101bf1fe9ac7c354e", "D4": "438a1d94ca7b392cf854f68d18bfd7db",
                         "D5": "d59bd98b5d1d14ae8d74499b1c1ccb3f", "D6": "e665c189ad63ca0cd032c0797e8aabf2"},
            "files": {},
            "docs": ["https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/",
                     "https://irsa.ipac.caltech.edu/data/SPHEREx/docs/spherex_spectral_calibrations.html"],
        },
        "finding_sip": ("astropy applies the celestial SIP polynomial (A_*/B_* keywords, no alternate "
                        "letter) to WCS(key='W'), so quality.py reads the WCS-WAVE table at a distorted "
                        "pixel. 'table' below reads the same table without SIP; the difference "
                        "table - production is that effect alone."),
        "targets": {}, "published": PUBLISHED,
    }
    for det in (1, 6):
        S.download(det)
        cal = S.load(det)
        report["calibration_product"]["files"][f"D{det}"] = {
            "url": S.URL.format(version=S.VERSION, det=det), "sha256": cal["sha256"],
            "sha256_matches_recorded": cal["verified"], "detcoord": cal["detcoord"],
            "history": cal["history"], "comment": cal["comment"],
            "header_error_estimates_um": {k: cal[k] for k in ("wl_err_max_um", "bw_err_max_um",
                                                             "wl_err_p99_um", "bw_err_p99_um")},
            "shape": list(cal["cwave"].shape),
            "cwave_range_um": [float(cal["cwave"].min()), float(cal["cwave"].max())],
            "cband_range_um": [float(cal["cband"].min()), float(cal["cband"].max())]}
    report["orientation_check"] = orientation_check()
    for t in api.TARGETS:
        r = audit_target(t)
        report["targets"][t["id"]] = r
        p, c = r["pairs"]["production"], r["pairs"]["calibrated"]
        print(t["id"], "valid pairs", p["n_valid_pairs"], "->", c["n_valid_pairs"],
              "| changed", len(r["changed_pairs_production_vs_calibrated"]),
              "| dlam nm", r["differences_usable_epochs"]["dlambda_nm_cal_minus_production"])
    report["conclusions"] = {
        tid: {"published": PUBLISHED[tid],
              "production": report["targets"][tid]["pairs"]["production"],
              "calibrated": report["targets"][tid]["pairs"]["calibrated"],
              "claims": report["targets"][tid]["claims"]}
        for tid in report["targets"]}
    report["epsf_layout"] = epsf_layout()
    OUT.write_text(json.dumps(report, indent=1, default=lambda o: None if o is None else float(o)) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
