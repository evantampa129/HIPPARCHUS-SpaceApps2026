"""Wavelength calibration: why WCS(key="W") is off, the corrected sources, and what changes.

Writes submission/evidence/wavecal_check.json, plus
submission/evidence/wavecal_robustness_{wcs_nosip,cwave}.json (the robustness
audit rerun with each corrected source; robustness.json itself is not touched). Runs offline on the cached
cutouts and archive manifests (as reproduce_robustness.py does) plus the
Spectral WCS calibration files in data/cache/calibration (fetched with
spectral_cal.download if missing). It does not change the production code
or any published evidence file; it only reports what would change.

Three wavelength readings are compared at every epoch's target pixel:
  production  astropy WCS(key="W"), exactly as quality.py reads it
  table       the same WCS-WAVE table, bilinear between control points (IRSA recipe)
  calibrated  CWAVE/CBAND maps of the Spectral WCS product (what IRSA recommends)
They are the quality.WAVELENGTH_SOURCES "wcs", "wcs_nosip" and "cwave"; the
pipeline is also rerun in each mode and must give the same numbers.
"""

import dataclasses
import glob
import hashlib
import json
import sys
import tempfile
import warnings
from collections import Counter
from itertools import combinations
from pathlib import Path

import numpy as np
import astropy
from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
# Importing the robustness script also routes archive.query to the saved
# manifests, so this audit sees exactly the exposures behind the published results.
import reproduce_robustness as RR  # noqa: E402
from hipparchus import api, archive, compare as C, cutouts, pipeline, psf_photometry as P  # noqa: E402
from hipparchus import quality as Q, spectral_cal as S  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "submission" / "evidence" / "wavecal_check.json"

# A cached manifest can be a "partial" IRSA answer (one release only). On
# 2026-11-15 23:59 obs_76.9560_+30.4010.json was rewritten that way: 38 D1 rows
# instead of the 56 behind the published RW Aur result. The published evidence
# keeps each epoch's full archive record, so we add back any it lists that the
# manifest lacks (read-only: the manifest file is not changed) and report it.
RESTORED: dict = {}


def published_query(ra, dec, **kw):
    m = RR.cached_query(ra, dec, **kw)
    have = {(o["obs_id"], o["detector"]) for o in m["observations"]}
    for t in api.TARGETS:
        if abs(t["ra"] - ra) > 1e-6 or abs(t["dec"] - dec) > 1e-6:
            continue
        ev = json.loads((RR.EVID / f"{t['id']}_{t['detector'].lower()}.json").read_text())
        add = [e["provenance"]["obs"] for e in ev["epochs"]
               if (e["obs_id"], e["provenance"]["obs"]["detector"]) not in have]
        m["observations"] = m["observations"] + add
        RESTORED[t["id"]] = {"manifest_file_status": json.loads(archive._manifest_path(ra, dec).read_text()).get("archive_status"),
                             "n_in_manifest": len(have), "n_added_from_published": len(add)}
    return m


archive.query = published_query

# What the published texts state; the audit says whether each still holds.
PUBLISHED = {"rw_aur": "8 valid pairs, max flux ratio 2.56, every pair brighter later, max sig >= 5",
             "wise0855": "27 valid pairs, none changes by >= 5 sigma",
             "barnard": "refused: no usable epoch"}


def stats(v):
    v = np.abs(np.asarray([x for x in v if x is not None and np.isfinite(x)], float))
    if not v.size:
        return None
    return {"n": int(v.size), "median": float(np.median(v)), "max": float(v.max())}


EXPLANATION = {
    "cause": ("The cutout header holds two WCS. The celestial one is RA---TAN-SIP/DEC--TAN-SIP with SIP "
              "coefficients A_i_j, B_i_j, AP_i_j, BP_i_j. The SIP convention (Shupe et al. 2005) has no "
              "alternate-WCS letter for these keywords and ties them to a CTYPE ending in -SIP. The "
              "spectral WCS 'W' is CTYPEjW = WAVE-TAB (FITS Paper III -TAB, bilinear lookup) on raw 1-based "
              "parent pixel coordinates (CRPIXjW = CRPIXjA, CDELTjW = CRVALjW = 1); it has no -SIP. "
              "astropy.wcs.WCS(header, key='W') nevertheless calls _read_sip_kw(header, wcskey='W'), which "
              "reads the unsuffixed A_/B_ keywords and builds Sip(..., crpix=(CRPIX1W, CRPIX2W)); the CTYPE "
              "check only logs an INFO note (which quality.py silenced). pixel_to_world then looks the table "
              "up at p + SIP(p + 1 - CRPIXW): the celestial polynomial (incl. A_0_0, B_0_0 ~ -0.3/-1.1 px), "
              "evaluated around the wrong reference pixel (the parent origin instead of the celestial CRPIX), "
              "so the shift reaches tens of pixels near the detector edge."),
    "proof": ("sip_proof below, all cached cutouts, 5x5 points each: nosip - table and legacy - table@sip "
              "agree to ~1e-12 um on every detector, i.e. astropy's -TAB read is exact and the SIP shift "
              "alone is the legacy offset."),
    "is_wcs_nosip_equal_to_cwave": ("No. wcs_nosip is the 9x9 control-point table, which IRSA says is "
                                    "accurate to ~1 nm and meant for visualization; CWAVE/CBAND are the "
                                    "per-pixel maps. See sip_proof.*.cwave_minus_nosip_nm."),
    "sources": [
        {"what": "IRSA tutorial 'Introduction to SPHEREx Spectral Images', section 8b Spectral WCS",
         "url": "https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/",
         "quote": "SIP distortions must be turned off for the spectral WCS. spectral_wcs.sip = None"},
        {"what": "IRSA tutorial 'SPHEREx Source Discovery Tool IRSA Demo', process_cutout",
         "url": "https://caltech-ipac.github.io/irsa-tutorials/spherex-source-discovery-tool-demo/",
         "quote": "spectral_wcs.sip = None  # disable SIP distortions"},
        {"what": "SPHEREx archive documentation, data products: WCS-WAVE and Spectral WCS",
         "url": "https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/",
         "quote": ("bilinear interpolation ... yields values accurate to within approximately 1 nm. The fidelity "
                   "of the WCS-WAVE lookup table is intended for visualization purposes. For science analysis, "
                   "use the CWAVE and CBAND extensions in the Spectral WCS calibration product.")},
        {"what": "astropy source, astropy/wcs/wcs.py WCS.__init__ and _read_sip_kw (version below)",
         "quote": "sip = self._read_sip_kw(header, wcskey=key) ... return Sip(a, b, ap, bp, (crpix1, crpix2))"},
    ],
}


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


def sip_proof():
    """On every cached cutout, 5x5 pixel grid: what astropy does to WCS(key="W") and why.

    legacy     astropy WCS(key="W") as is (quality source "wcs")
    nosip      the same object with .sip = None (quality source "wcs_nosip")
    table      the documented 4-point bilinear read of WCS-WAVE (spectral_cal.wcs_wave_table)
    table@sip  table read at p + SIP(p + 1 - CRPIXjW), the SIP polynomial astropy attached
    cwave      CWAVE/CBAND at the parent pixel
    """
    per = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FITSFixedWarning)
        for f in sorted(glob.glob(str(cutouts.CACHE_DIR / "*.fits"))):
            with fits.open(f) as h:
                hd = h["IMAGE"].header
                det = int(hd["DETECTOR"])
                ny, nx = h["IMAGE"].data.shape
                legacy = WCS(hd, fobj=h, key="W")
                nosip = WCS(hd, fobj=h, key="W")
                nosip.sip = None
                d = per.setdefault(det, {"n_cutouts": 0, "sip_attached_to_W": 0, "sip_crpix_is_W_crpix": 0,
                                         "ctype_W": set(), "ctype_celestial": set(), **{k: [] for k in (
                                             "nosip_minus_table_um", "legacy_minus_table_at_sip_um",
                                             "sip_shift_px", "legacy_minus_nosip_lam_um", "legacy_minus_nosip_band_um",
                                             "cwave_minus_nosip_um", "cwave_minus_legacy_um",
                                             "cband_minus_nosip_um", "cband_minus_legacy_um",
                                             "nosip_minus_cwave_over_cband", "legacy_minus_cwave_over_cband")}})
                d["n_cutouts"] += 1
                d["ctype_W"].add(f"{hd['CTYPE1W']}/{hd['CTYPE2W']}")
                d["ctype_celestial"].add(f"{hd['CTYPE1']}/{hd['CTYPE2']}")
                sip = legacy.sip
                d["sip_attached_to_W"] += sip is not None
                if sip is None:
                    continue
                d["sip_crpix_is_W_crpix"] += tuple(sip.crpix) == (hd["CRPIX1W"], hd["CRPIX2W"])
                xs, ys = (g.ravel() for g in np.meshgrid(np.linspace(0, nx - 1, 5), np.linspace(0, ny - 1, 5)))
                lg = np.array(legacy.pixel_to_world_values(xs, ys)).T
                ns = np.array(nosip.pixel_to_world_values(xs, ys)).T
                tb = np.array([S.wcs_wave_table(h, x, y) for x, y in zip(xs, ys)])
                u, v = xs + 1 - hd["CRPIX1W"], ys + 1 - hd["CRPIX2W"]
                du = sum(sip.a[i, j] * u ** i * v ** j for i in range(sip.a.shape[0]) for j in range(sip.a.shape[1]))
                dv = sum(sip.b[i, j] * u ** i * v ** j for i in range(sip.b.shape[0]) for j in range(sip.b.shape[1]))
                ts = np.array([S.wcs_wave_table(h, x, y) for x, y in zip(xs + du, ys + dv)])
                ok = np.isfinite(ts[:, 0])
                d["nosip_minus_table_um"] += list((ns - tb).ravel())
                d["legacy_minus_table_at_sip_um"] += list((lg - ts)[ok].ravel())
                d["sip_shift_px"] += list(np.hypot(du, dv))
                d["legacy_minus_nosip_lam_um"] += list(lg[:, 0] - ns[:, 0])
                d["legacy_minus_nosip_band_um"] += list(lg[:, 1] - ns[:, 1])
                cal = S.load(det)
                if cal is None:
                    continue
                pp = [S.parent_pixel(hd, x, y) for x, y in zip(xs, ys)]
                cw = np.array([[S.bilinear(cal["cwave"], px, py), S.bilinear(cal["cband"], px, py)] for px, py in pp])
                d["cwave_minus_nosip_um"] += list(cw[:, 0] - ns[:, 0])
                d["cwave_minus_legacy_um"] += list(cw[:, 0] - lg[:, 0])
                d["cband_minus_nosip_um"] += list(cw[:, 1] - ns[:, 1])
                d["cband_minus_legacy_um"] += list(cw[:, 1] - lg[:, 1])
                d["nosip_minus_cwave_over_cband"] += list((ns[:, 0] - cw[:, 0]) / cw[:, 1])
                d["legacy_minus_cwave_over_cband"] += list((lg[:, 0] - cw[:, 0]) / cw[:, 1])
    out = {}
    for det, d in sorted(per.items()):
        e = {"n_cutouts": d["n_cutouts"], "n_points": len(d["sip_shift_px"]),
             "ctype_W": sorted(d["ctype_W"]), "ctype_celestial": sorted(d["ctype_celestial"]),
             "sip_attached_to_W": d["sip_attached_to_W"], "sip_crpix_is_W_crpix": d["sip_crpix_is_W_crpix"]}
        for k, v in d.items():
            if isinstance(v, list):
                st = stats(v)
                # Wavelength differences in nm; pixel shifts and band fractions as they are.
                scale = 1 if k.startswith("sip_shift") or k.endswith("over_cband") else 1e3
                name = k if scale == 1 else k.replace("_um", "_nm")
                e[name] = st and {"n": st["n"], "median_abs": scale * st["median"], "max_abs": scale * st["max"]}
        out[f"D{det}"] = e
    return out


def mode_epochs(t, mode):
    """Epochs exactly as pipeline.load_epochs gives them with one wavelength source."""
    loaded = pipeline.load_epochs(t["ra"], t["dec"], t["detector"], wavelength_source=mode)
    return {e.obs_id: e for e in loaded["epochs"]}


def audit_target(t):
    det = int(t["detector"].split("D")[-1])
    for_det = [o for o in archive.query(t["ra"], t["dec"])["observations"] if o["detector"] == t["detector"]]
    loaded = pipeline.load_epochs(t["ra"], t["dec"], t["detector"])
    epochs = sorted(loaded["epochs"], key=lambda e: e.mjd)
    url = {o["obs_id"]: o["access_url"] for o in for_det}
    cal = S.load(det)
    per_epoch = []
    variants = {"production": {}, "table": {}, "calibrated": {}, "cwave_lambda_table_band": {}}
    # The pipeline itself in the two corrected modes; must equal the variants below.
    by_mode = {m: mode_epochs(t, m) for m in ("wcs_nosip", "cwave")}
    mode_check = {m: {"max_abs_dlambda_um": 0.0, "max_abs_dband_um": 0.0, "sources": Counter()} for m in by_mode}
    for e in epochs:
        path = cutouts.fetch(url[e.obs_id], t["ra"], t["dec"])["path"]
        r = S.at_target(path, e.x, e.y, cal=cal)
        # Our "production" value must be the one the pipeline used; if not, the
        # comparison below would not be about the published numbers.
        assert abs(r["wcs_wave_astropy_um"] - e.wavelength_um) < 1e-9, e.obs_id
        variants["production"][e.obs_id] = e
        variants["table"][e.obs_id] = with_wave(e, r["wcs_wave_table_um"], r["wcs_band_table_um"])
        variants["calibrated"][e.obs_id] = with_wave(e, r["wavelength_um"], r["bandwidth_um"])
        # CWAVE wavelength with the table bandwidth: separates the effect of CBAND on the half-channel rule.
        variants["cwave_lambda_table_band"][e.obs_id] = with_wave(e, r["wavelength_um"], r["wcs_band_table_um"])
        for m, ref in (("wcs_nosip", "table"), ("cwave", "calibrated")):
            em, ev = by_mode[m][e.obs_id], variants[ref][e.obs_id]
            mc = mode_check[m]
            mc["max_abs_dlambda_um"] = max(mc["max_abs_dlambda_um"], abs(em.wavelength_um - ev.wavelength_um))
            mc["max_abs_dband_um"] = max(mc["max_abs_dband_um"], abs(em.bandwidth_um - ev.bandwidth_um))
            mc["sources"][em.wavelength_source] += 1
            assert em.usable == e.usable and em.x == e.x and em.y == e.y, (m, e.obs_id)
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
    moved = {k: {"entered": [], "left": []} for k in variants if k != "production"}
    for ia, ib in combinations(ids, 2):
        d = {k: decision(v[ia], v[ib]) for k, v in variants.items()}
        for k in variants:
            rows[k].append(d[k])
        was = d["production"]["kind"] == "comparison"
        for k in moved:
            now = d[k]["kind"] == "comparison"
            if now != was:
                a1, b1 = variants[k][ia], variants[k][ib]
                moved[k]["entered" if now else "left"].append({
                    "a": ia, "b": ib, "ratio": (d[k] if now else d["production"])["ratio"],
                    "sig": (d[k] if now else d["production"])["sig"],
                    "codes_when_refused": (d["production"] if now else d[k]).get("codes"),
                    "dlambda_um": abs(a1.wavelength_um - b1.wavelength_um),
                    "half_channel_um": C.MAX_DLAMBDA_FRACTION * min(a1.bandwidth_um, b1.bandwidth_um)})
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
           "pairs_entering_leaving_vs_production": moved,
           "pipeline_mode_check": {m: {**v, "sources": dict(v["sources"])} for m, v in mode_check.items()},
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


def robustness_summary(d):
    out = {}
    for tid, e in d["targets"].items():
        out[tid] = {"verdict": e["verdict"], "systematic_floor": e.get("systematic_floor"),
                    "n_pairs": len(e.get("pairs", [])),
                    "max_ratio": max((r["ratio"] for r in e.get("pairs", [])), default=None),
                    "max_abs_sig": max((abs(r["sig"]) for r in e.get("pairs", [])), default=None),
                    "claims": [{k: c[k] for k in ("claim", "verdict", "n_holding", "n_checks", "settings_grid",
                                                  "leave_one_pair_out", "with_systematic_floor", "wavelength_rule")}
                               for c in e.get("claims", [])],
                    "wavelength_rule_variants": {k: {"n_pairs": v["n_pairs"], "max_abs_sig": v["max_abs_sig"]}
                                                 for k, v in (e.get("wavelength_rule_variants") or {}).items()}}
    return out


def robustness_by_mode():
    """Rerun reproduce_robustness in every mode. Legacy goes to a temp file and is
    compared with the published robustness.json (it must reproduce it)."""
    out = {"published": robustness_summary(json.loads(RR.OUT.read_text()))}
    for m in Q.WAVELENGTH_SOURCES:
        if m == "wcs":
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / "robustness_wcs.json"
                RR.main("wcs", p)
                out["wcs"] = robustness_summary(json.loads(p.read_text()))
        else:
            p = OUT.parent / f"wavecal_robustness_{m}.json"
            RR.main(m, p)
            out[m] = robustness_summary(json.loads(p.read_text()))
            out[m]["file"] = str(p.relative_to(ROOT))
    out["wcs_reproduces_published"] = out["wcs"] == out["published"]
    return out


def main():
    report = {
        "status": ("wavelength source is selectable (quality.WAVELENGTH_SOURCES); the default and every "
                   "published number stay on legacy 'wcs'. This file says what would change on a switch."),
        "explanation": EXPLANATION,
        "astropy_version": astropy.__version__,
        "modes": {"wcs": "astropy WCS(key='W') with the celestial SIP attached (legacy, published)",
                  "wcs_nosip": "WCS(key='W') with .sip = None; = documented bilinear read of WCS-WAVE",
                  "cwave": "CWAVE/CBAND of the Spectral WCS product at the parent pixel (IRSA: for science); "
                           "falls back to wcs_nosip with a 'wavelength_fallback' warning if the map is missing"},
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
        "finding_sip_previous_wording": ("astropy applies the celestial SIP polynomial (A_*/B_* keywords, no alternate "
                        "letter) to WCS(key='W'), so quality.py reads the WCS-WAVE table at a distorted "
                        "pixel. 'table' below reads the same table without SIP; the difference "
                        "table - production is that effect alone."),
        "targets": {}, "published": PUBLISHED,
    }
    for det in range(1, 7):
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
    report["sip_proof"] = sip_proof()
    report["exposures_restored_from_published_evidence"] = RESTORED
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
    report["regression_table"] = {
        tid: {m: report["targets"][tid]["pairs"][v] for m, v in
              (("wcs", "production"), ("wcs_nosip", "table"), ("cwave", "calibrated"),
               ("cwave_lambda_table_band", "cwave_lambda_table_band"))}
        for tid in report["targets"]}
    report["robustness_by_mode"] = robustness_by_mode()
    report["epsf_layout"] = epsf_layout()
    OUT.write_text(json.dumps(report, indent=1, default=lambda o: None if o is None else float(o)) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
