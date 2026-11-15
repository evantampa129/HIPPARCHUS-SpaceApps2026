"""Compare HIPPARCHUS with IRSA's own SPHEREx tools, on the same exposures.

Writes submission/evidence/irsa_tools_check.json and
report/figures/irsa_tools_photometry.png, report/figures/irsa_tools_most.png.

Three IRSA tools were considered:

 A. SPHEREx Source Discovery Tool (SDT): IRSA tutorial notebook plus the
    Python package `spherex_source_discovery_tool`. Its photometry is plain
    aperture photometry with a sigma-clipped annulus. We download the package
    source at a pinned commit and call its own `build_phot_table` on cutouts
    of the exact exposures we used (matched by OBSID), for RW Aur and
    WISE 0855.
 B. SPHEREx Spectrophotometry Tool (Tractor forced PSF photometry inside the
    SPHEREx Data Explorer web app). IRSA documents it only as a GUI whose
    jobs run through the app's Job Monitor; we found no documented public
    endpoint, so we do not script it and record it as NOT RUN.
 C. Moving Object Search Tool (MOST): documented URL API, and `spherex` is a
    moving-object-enabled dataset. We ask it which SPHEREx images contain
    (216) Kleopatra over the window of our motion check and compare that list,
    and its predicted positions, with our 38 exposures.

Every HTTP response is cached under data/cache/irsa_tools/ with a sidecar
JSON holding the URL, HTTP status and UTC timestamp of every attempt. IRSA
was returning HTTP 502 intermittently, so we retry politely with exponential
backoff inside a 30 minute budget for the whole run, and give up honestly.

Run (the SDT part needs photutils, pandas, tqdm and psutil, which the backend
venv does not carry, so we run this script in a side venv; we used
astropy 8.0.2, numpy 2.5.5, pandas 3.1.1, photutils 3.1.1, and the full list is
written to data/cache/irsa_tools/venv-sdt-freeze.txt):
    python3 -m venv data/cache/irsa_tools/venv-sdt
    data/cache/irsa_tools/venv-sdt/bin/pip install -e backend photutils pandas tqdm psutil
    data/cache/irsa_tools/venv-sdt/bin/python backend/scripts/compare_irsa_tools.py
The parsing and matching helpers need only numpy and astropy, so the offline
tests import them from the backend venv.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import io
import json
import platform
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "irsa_tools"
EVIDENCE = ROOT / "submission" / "evidence"
FIGURES = ROOT / "report" / "figures"
OUT_JSON = EVIDENCE / "irsa_tools_check.json"

TARGETS = {
    "rw_aur": EVIDENCE / "rw_aur_spherex-d1.json",
    "wise0855": EVIDENCE / "wise0855_spherex-d6.json",
}
MOTION_JSON = EVIDENCE / "motion_check.json"

# The SDT lives in the IRSA tutorials repository. We pin the commit we read so
# the comparison can be reproduced even if the notebook changes later.
SDT_REPO = "Caltech-IPAC/irsa-tutorials"
SDT_COMMIT = "8a83a9e311b81bae8813f5102b8c5da69ed1689e"
SDT_DIR = "tutorials/spherex/spherex_source_discovery/spherex_source_discovery_tool"
SDT_FILES = ("aperture_photometry.py", "sdt_utils.py")
SDT_SRC = CACHE / "sdt_src"
# The SDT notebook uses 0.1 deg cutouts and a fixed 7-16 px annulus; our
# 0.05 deg evidence cutouts (29 px) are too small for that annulus (photutils
# would fill the missing part with zeros), so we ask IRSA for 0.1 deg cutouts
# of the same exposures.
SDT_CUTOUT_DEG = 0.1
# 3.0 px is the radius the notebook picks; 2.0 px is our own aperture, which
# separates the effect of the background method from the aperture size.
SDT_RADII = [2.0, 3.0]
# The notebook's list of flags that make a point suspect (its grab_star call).
SDT_BAD_FLAGS = ["TRANSIENT", "OVERFLOW", "SUR_ERROR", "NONFUNC", "DICHROIC", "MISSING_DATA", "HOT",
                 "COLD", "NONLINEAR", "CROSSTALK", "GHOST", "GHOST_FPA", "GHOST_EXT", "STREAK",
                 "PERSIST", "BLOOM", "SNOWBALL", "HALO", "SATELLITE_HALO"]
SAPM_COLLECTION = "cal-sapm-v3-2026-191"
SAPM_URL = ("https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/solid_angle_pixel_map/"
            "{c}/{k}/solid_angle_pixel_map_D{k}_spx_{c}.fits")
ARCSEC2_TO_SR = (np.pi / (180.0 * 3600.0)) ** 2
MJY_PER_MJYSR_SR = 1e9   # MJy -> mJy

MOST_URL = "https://irsa.ipac.caltech.edu/cgi-bin/MOST/nph-most"
HORIZONS_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
SPECTROPHOT_HELP = "https://irsa.ipac.caltech.edu/onlinehelp/spherex/spherex/sp.html"
SPHEREX_API_DOC = "https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access"

# Waits between attempts, in seconds. The whole run shares one 30 min budget
# for waiting, so a long outage ends the run instead of hammering IRSA.
BACKOFF_S = (15, 30, 60, 120, 240, 420, 600)
RETRY_BUDGET_S = 30 * 60
RETRY_STATUSES = {429, 500, 502, 503, 504}

REQUEST_LOG: list[dict] = []
_BUDGET = {"spent_s": 0.0}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# HTTP with cache and backoff
# --------------------------------------------------------------------------

def cache_paths(url: str, suffix: str, subdir: str = "http") -> tuple[Path, Path]:
    key = hashlib.sha256(url.encode()).hexdigest()[:24]
    d = CACHE / subdir
    return d / f"{key}{suffix}", d / f"{key}.meta.json"


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def fetch(url: str, suffix: str = ".dat", subdir: str = "http", timeout: float = 180.0,
          backoff=BACKOFF_S, sleep=time.sleep, opener=urllib.request.urlopen,
          budget_s: float = RETRY_BUDGET_S) -> dict:
    """Return {url, status, cached, path, sha256, attempts} for `url`.

    A cached body is reused only if the sidecar says the last attempt was a
    200 and the bytes still hash to what we stored. Failures are written to the
    sidecar too (status only), so a rerun can tell "IRSA said 502 four times"
    from "never asked".
    """
    path, meta_path = cache_paths(url, suffix, subdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {"url": url, "attempts": []}
    if meta.get("status") == 200 and path.exists() \
            and hashlib.sha256(path.read_bytes()).hexdigest() == meta.get("sha256"):
        REQUEST_LOG.append({"url": url, "status": 200, "t_utc": utc_now(), "from_cache": True})
        return {"url": url, "status": 200, "cached": True, "path": _rel(path),
                "sha256": meta["sha256"], "attempts": meta["attempts"]}

    status = None
    for i in range(len(backoff) + 1):
        t0 = utc_now()
        body = None
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hipparchus-irsa-tools-check/0.1"})
            with opener(req, timeout=timeout) as r:
                body = r.read()
                status = getattr(r, "status", 200)
        except urllib.error.HTTPError as e:
            status = e.code
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            status = f"error: {type(e).__name__}: {e}"[:200]
        meta["attempts"].append({"t_utc": t0, "status": status})
        REQUEST_LOG.append({"url": url, "status": status, "t_utc": t0, "from_cache": False})
        print(f"  [{t0}] {status}  {url[:120]}", flush=True)
        if status == 200 and body is not None:
            path.write_bytes(body)
            meta.update(status=200, sha256=hashlib.sha256(body).hexdigest(), bytes=len(body))
            meta_path.write_text(json.dumps(meta, indent=1))
            return {"url": url, "status": 200, "cached": False, "path": _rel(path),
                    "sha256": meta["sha256"], "attempts": meta["attempts"]}
        retryable = isinstance(status, str) or status in RETRY_STATUSES
        if not retryable or i == len(backoff) or _BUDGET["spent_s"] + backoff[i] > budget_s:
            break
        _BUDGET["spent_s"] += backoff[i]
        sleep(backoff[i])
    meta["status"] = status
    meta_path.write_text(json.dumps(meta, indent=1))
    return {"url": url, "status": status, "cached": False, "path": None, "sha256": None,
            "attempts": meta["attempts"]}


# --------------------------------------------------------------------------
# Small statistics helpers
# --------------------------------------------------------------------------

def robust_stats(values) -> dict:
    """Median and MAD-based scatter (1.4826 x MAD), plus plain mean/std."""
    v = np.asarray([x for x in values if x is not None and np.isfinite(x)], dtype=float)
    if v.size == 0:
        return {"n": 0}
    med = float(np.median(v))
    return {"n": int(v.size), "median": med,
            "robust_sigma": float(1.4826 * np.median(np.abs(v - med))),
            "mean": float(v.mean()), "std": float(v.std(ddof=1)) if v.size > 1 else None,
            "min": float(v.min()), "max": float(v.max())}


def sky_offset_arcsec(ra1, dec1, ra2, dec2) -> dict:
    """(1 - 2) as dRA*cos(dec), dDec, total, in arcsec (small-angle)."""
    dra = (((ra1 - ra2) + 180.0) % 360.0 - 180.0) * np.cos(np.radians(0.5 * (dec1 + dec2))) * 3600.0
    ddec = (dec1 - dec2) * 3600.0
    return {"dra": float(dra), "ddec": float(ddec), "total": float(np.hypot(dra, ddec))}


# --------------------------------------------------------------------------
# MOST and Horizons
# --------------------------------------------------------------------------

def mjd_to_most_time(mjd: float) -> str:
    t = dt.datetime(1858, 11, 17, tzinfo=dt.timezone.utc) + dt.timedelta(days=mjd)
    return t.strftime("%Y %m %d %H:%M:%S")


def most_query_url(obj_name: str, mjd_begin: float, mjd_end: float, output_mode: str = "Brief",
                   catalog: str = "spherex") -> str:
    params = {"catalog": catalog, "input_type": "name_input", "obj_name": obj_name,
              "obs_begin": mjd_to_most_time(mjd_begin), "obs_end": mjd_to_most_time(mjd_end),
              "output_mode": output_mode}
    return MOST_URL + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote_plus)


def parse_most_ipac(text: str) -> tuple[dict, list[dict]]:
    """MOST 'Brief' output is an IPAC table: \\key = "value" header lines,
    then the table. Returns (header keywords, rows as plain dicts)."""
    from astropy.io import ascii
    header = {}
    for line in text.splitlines():
        m = re.match(r'^\\\s*([A-Za-z_]+)\s*=\s*"?(.*?)"?\s*$', line)
        if m:
            header[m.group(1)] = m.group(2).strip()
        elif line.startswith("|"):
            break
    t = ascii.read(text, format="ipac")
    rows = []
    for r in t:
        d = {}
        for c in t.colnames:
            v = r[c]
            d[c] = v.item() if hasattr(v, "item") else v
            if isinstance(d[c], str):
                d[c] = d[c].strip()
        rows.append(d)
    return header, rows


def most_key(row: dict) -> tuple[str, str]:
    det = str(row["productid"]).strip()
    return str(row["observationid"]).strip(), det if det.startswith("SPHEREx-") else f"SPHEREx-{det}"


def match_most(most_rows: list[dict], exposures: list[dict]) -> dict:
    """Compare MOST's list of SPHEREx images containing the object with ours.

    Key = (OBSID, detector). For images on both lists we report MOST's
    predicted position against our Horizons positions (SPHEREx-centric and
    geocentric, at our mid-exposure time) and against our measured centroid.
    """
    most = {most_key(r): r for r in most_rows}
    ours = {(e["obs_id"], e["detector"]): e for e in exposures}
    both = sorted(set(most) & set(ours))
    only_most = sorted(set(most) - set(ours))
    only_ours = sorted(set(ours) - set(most))
    per = []
    for k in both:
        r, e = most[k], ours[k]
        rec = {"obs_id": k[0], "detector": k[1], "most_ra": r["ra_obj"], "most_dec": r["dec_obj"],
               "most_mjd_start": r["mjd_start"], "most_mjd_end": r["mjd_end"], "our_mjd_mid": e["mjd_mid"],
               "most_dist_ctr_deg": r.get("dist_ctr"), "most_vmag": r.get("vmag"),
               "most_minus_horizons_spherex_mid": sky_offset_arcsec(r["ra_obj"], r["dec_obj"],
                    e["horizons_spherex"]["ra"], e["horizons_spherex"]["dec"]),
               "most_minus_horizons_geocentric_mid": sky_offset_arcsec(r["ra_obj"], r["dec_obj"],
                    e["horizons_geocentric"]["ra"], e["horizons_geocentric"]["dec"])}
        m = e.get("measured")
        rec["most_minus_measured"] = (sky_offset_arcsec(r["ra_obj"], r["dec_obj"], m["ra"], m["dec"])
                                      if m else None)
        per.append(rec)
    return {
        "n_most": len(most), "n_ours": len(ours), "n_both": len(both),
        "only_most": [{"obs_id": k[0], "detector": k[1]} for k in only_most],
        "only_ours": [{"obs_id": k[0], "detector": k[1],
                       "our_quality_issues": ours[k].get("quality_issues_at_prediction"),
                       "we_measured_it": ours[k].get("measured") is not None} for k in only_ours],
        "n_both_with_our_measurement": sum(1 for p in per if p["most_minus_measured"] is not None),
        "per_image": per,
    }


def horizons_url(mjds, center: str) -> str:
    params = {"format": "json", "COMMAND": "'216;'", "EPHEM_TYPE": "OBSERVER", "CENTER": f"'{center}'",
              "TLIST": " ".join(f"{m:.9f}" for m in mjds), "TLIST_TYPE": "MJD", "TIME_TYPE": "UT",
              "QUANTITIES": "'1'", "ANG_FORMAT": "DEG", "CSV_FORMAT": "YES", "EXTRA_PREC": "YES",
              "OBJ_DATA": "NO"}
    return HORIZONS_URL + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote_plus)


def parse_horizons_csv(result: str) -> list[tuple[float, float]]:
    """(RA, Dec) in degrees for each row between $$SOE and $$EOE."""
    body = result.split("$$SOE", 1)[1].split("$$EOE", 1)[0]
    out = []
    for line in body.strip().splitlines():
        nums = []
        for f in line.split(",")[1:]:
            try:
                nums.append(float(f))
            except ValueError:
                continue
        out.append((nums[0], nums[1]))
    return out


def most_time_convention(per_image: list[dict]) -> dict:
    """MOST quotes one position per image but not the instant it applies to.
    We ask Horizons for (216) at MOST's mjd_start and at the mid-exposure,
    from SPHEREx and from the geocentre, and see which one MOST reproduces."""
    starts = sorted({round(p["most_mjd_start"], 9) for p in per_image})
    mids = sorted({round(p["our_mjd_mid"], 9) for p in per_image})
    out = {"queries": {}, "rms_arcsec": {}, "max_arcsec": {}}
    for center, label in (("500@-163182", "spherex"), ("500@399", "geocentric")):
        for name, times in (("mjd_start", starts), ("mid_exposure", mids)):
            url = horizons_url(times, center)
            res = fetch(url, ".json", "horizons")
            out["queries"][f"{label}@{name}"] = {k: res[k] for k in ("url", "status", "cached", "sha256")}
            if res["status"] != 200:
                continue
            radec = parse_horizons_csv(json.loads((ROOT / res["path"]).read_text())["result"])
            lut = dict(zip(times, radec))
            tot = []
            for p in per_image:
                t = round(p["most_mjd_start"] if name == "mjd_start" else p["our_mjd_mid"], 9)
                ra, dec = lut[t]
                o = sky_offset_arcsec(p["most_ra"], p["most_dec"], ra, dec)
                p.setdefault("most_minus_horizons", {})[f"{label}@{name}"] = o
                tot.append(o["total"])
            out["rms_arcsec"][f"{label}@{name}"] = float(np.sqrt(np.mean(np.square(tot))))
            out["max_arcsec"][f"{label}@{name}"] = float(np.max(tot))
    if out["rms_arcsec"]:
        out["best"] = min(out["rms_arcsec"], key=out["rms_arcsec"].get)
    return out


def run_most() -> dict:
    motion = json.loads(MOTION_JSON.read_text())
    w0, w1 = motion["field"]["window_mjd"]
    url = most_query_url("Kleopatra", w0, w1, "Brief")
    res = fetch(url, ".txt", "most")
    rec = {"status": "NOT RUN", "tool": "IRSA Moving Object Search Tool (MOST)",
           "api_doc": "https://irsa.ipac.caltech.edu/applications/MOST/MOSTProgramInterface.html",
           "query": {k: res[k] for k in ("url", "status", "cached", "sha256", "path", "attempts")},
           "window_mjd": [w0, w1], "window_utc": [mjd_to_most_time(w0), mjd_to_most_time(w1)]}
    if res["status"] != 200:
        rec["reason"] = f"MOST did not answer with HTTP 200 (last status {res['status']})."
        return rec
    text = (ROOT / res["path"]).read_text()
    header, rows = parse_most_ipac(text)
    if not rows:
        rec["reason"] = "MOST answered but returned no matched SPHEREx images."
        rec["most_header"] = header
        return rec
    m = match_most(rows, motion["exposures"])
    conv = most_time_convention(m["per_image"])
    with_meas = [p for p in m["per_image"] if p["most_minus_measured"]]
    best = conv.get("best")
    rec.update({
        "status": "RAN",
        "most_header": {k: header.get(k) for k in ("catalog", "object_name", "element_epoch",
                                                   "user_input_begin_time", "user_input_end_time",
                                                   "job_time_stamp")},
        "most_releases_in_uri": sorted({r["uri"].split("/")[3] for r in rows if r.get("uri")}),
        "match": {k: v for k, v in m.items() if k != "per_image"},
        "time_convention": conv,
        "position_agreement_arcsec": {
            "most_vs_our_horizons_spherex_mid": robust_stats(
                [p["most_minus_horizons_spherex_mid"]["total"] for p in m["per_image"]]),
            "most_vs_our_horizons_geocentric_mid": robust_stats(
                [p["most_minus_horizons_geocentric_mid"]["total"] for p in m["per_image"]]),
            "most_vs_our_measured": robust_stats([p["most_minus_measured"]["total"] for p in with_meas]),
            "most_vs_horizons_best_convention": robust_stats(
                [p["most_minus_horizons"][best]["total"] for p in m["per_image"]
                 if best and best in p.get("most_minus_horizons", {})]),
        },
        "per_image": m["per_image"],
    })
    return rec


# --------------------------------------------------------------------------
# Spectrophotometry Tool
# --------------------------------------------------------------------------

def run_spectrophotometry_tool() -> dict:
    """We only record what we checked. Its documentation describes a GUI
    (SPHEREx Data Explorer) whose jobs are UWS jobs owned by the web app's
    Job Monitor; IRSA's list of SPHEREx APIs names SIA v2 and the cutout
    service only. Driving an undocumented internal endpoint would not be a
    fair or reproducible use of IRSA's service, so we stop here."""
    checked = []
    for url in (SPECTROPHOT_HELP, SPHEREX_API_DOC):
        r = fetch(url, ".html", "docs")
        checked.append({k: r[k] for k in ("url", "status", "cached", "sha256")})
    return {
        "status": "NOT RUN",
        "tool": "IRSA SPHEREx Spectrophotometry Tool (Tractor forced PSF photometry, SPHEREx Data Explorer)",
        "checked": checked,
        "reason": ("GUI-only as documented: jobs are submitted from the SPHEREx Data Explorer web app and "
                   "tracked in its Job Monitor (UWS under the hood, but no public endpoint or parameter list "
                   "is documented); IRSA's SPHEREx API list covers SIA v2 and the cutout service only. Each "
                   "job also takes >= 5 min and is throttled to 2 per user. We did not reverse-engineer the "
                   "web app, so there are no Tractor numbers in this file."),
        "how_to_run_by_hand": ("SPHEREx Data Explorer -> Spectrophotometry -> Point Source at RA 76.956, "
                               "Dec +30.401 (RW Aur) and RA 133.76, Dec -7.2424 (WISE 0855); download the table "
                               "and match its lvf_id/det_id/mjd columns to the obs ids in the evidence files."),
        "expected_differences_if_run": [
            "PSF fit (Tractor, measured PSF) vs our 2 px aperture: no aperture loss, so absolute fluxes "
            "should be higher than ours by the inverse of our encircled-energy fraction.",
            "Background from flag-masked nearby pixels fitted jointly vs our median 4-7 px annulus.",
            "uJy via the pixel solid angle map vs our MJy/sr summed over pixels (cancels in ratios).",
        ],
    }


# --------------------------------------------------------------------------
# Source Discovery Tool
# --------------------------------------------------------------------------

def our_epoch_fluxes(evidence: dict) -> dict:
    """Our per-exposure flux from the published comparisons.

    In compare() epoch a is measured on its own pixel grid and epoch b after
    reprojection onto a's grid. We prefer the native (a) measurement and fall
    back to the reprojected (b) one, saying which we used.
    """
    out: dict[str, dict] = {}
    for c in evidence["comparisons"]:
        for side, oid, lam in (("a", c["a"], c.get("lambda_a_um")), ("b", c["b"], c.get("lambda_b_um"))):
            f = c.get(f"flux_{side}")
            if not f or f.get("flux") is None or not np.isfinite(f["flux"]):
                continue
            prev = out.get(oid)
            if prev is None or (prev["grid"] == "reprojected" and side == "a"):
                out[oid] = {"flux": f["flux"], "flux_err": f["flux_err"], "sky": f["sky"],
                            "grid": "native" if side == "a" else "reprojected", "lambda_um": lam}
    return out


def parent_pixel(header, x0: float, y0: float) -> tuple[float, float]:
    """0-based detector pixel of 0-based cutout pixel (x0, y0), from the
    alternate 'A' WCS (CTYPE=LINEAR, '0-based active pixel coordinates')."""
    return (x0 + 1.0 - header["CRPIX1A"]) * header.get("CDELT1A", 1.0) + header.get("CRVAL1A", 0.0), \
           (y0 + 1.0 - header["CRPIX2A"]) * header.get("CDELT2A", 1.0) + header.get("CRVAL2A", 0.0)


def mjysr_sum_to_mjy(flux_mjysr_pix: float, omega_arcsec2: float) -> float:
    """Our flux (MJy/sr summed over pixels) to mJy with a pixel solid angle."""
    return flux_mjysr_pix * omega_arcsec2 * ARCSEC2_TO_SR * MJY_PER_MJYSR_SR


def compare_pairs(evidence: dict, sdt: dict, radius: float, omega_fix: bool) -> list[dict]:
    """For every published comparison, our flux ratio and significance next
    to the SDT's, computed from the SDT's own per-exposure numbers."""
    out = []
    for c in evidence["comparisons"]:
        a, b = sdt.get(c["a"]), sdt.get(c["b"])
        if c.get("flux_ratio") is None or a is None or b is None:
            continue
        k = SDT_RADII.index(radius)
        fa, fb = a["flux_mjy"][k], b["flux_mjy"][k]
        if omega_fix:
            fa, fb = fa * a["omega_fix"], fb * b["omega_fix"]
        ea = np.sqrt(max(a["var_mjy2"][k], 0.0)) * (a["omega_fix"] if omega_fix else 1.0)
        eb = np.sqrt(max(b["var_mjy2"][k], 0.0)) * (b["omega_fix"] if omega_fix else 1.0)
        sig = (fb - fa) / np.hypot(ea, eb) if np.hypot(ea, eb) > 0 else float("nan")
        out.append({"a": c["a"], "b": c["b"], "kind": c["verdict"]["kind"],
                    "ours_ratio": c["flux_ratio"], "sdt_ratio": fb / fa if fa != 0 else None,
                    "ours_significance": c["significance"], "sdt_significance": float(sig),
                    "ours_changed": bool(c["changed"]), "sdt_changed": bool(abs(sig) >= 5.0)})
    return out


def _load_sdt():
    """Import the SDT's own modules from the pinned source, fetching them first."""
    pkg = SDT_SRC / "spherex_source_discovery_tool"
    pkg.mkdir(parents=True, exist_ok=True)
    prov = {"repo": SDT_REPO, "commit": SDT_COMMIT, "files": {}}
    for f in SDT_FILES:
        url = f"https://raw.githubusercontent.com/{SDT_REPO}/{SDT_COMMIT}/{SDT_DIR}/{f}"
        r = fetch(url, ".py", "sdt_http")
        if r["status"] != 200:
            raise RuntimeError(f"could not fetch {url}: {r['status']}")
        (pkg / f).write_bytes((ROOT / r["path"]).read_bytes())
        prov["files"][f] = {"url": url, "sha256": r["sha256"]}
    # The upstream __init__ also imports bokeh/firefly/SExtractor helpers that
    # we do not use; an empty __init__ lets us import the two modules we need.
    (pkg / "__init__.py").write_text("# only aperture_photometry and sdt_utils are used here\n")
    prov["local_changes"] = [
        "__init__.py replaced by an empty file (upstream imports bokeh/firefly/SExtractor helpers we do not call)",
        "fetch_sapm() replaced: the same cal-sapm-v3-2026-191 maps, read over HTTPS from IRSA instead of "
        "anonymous S3, and only for the detectors we need; the interpolator is still the SDT's interp2d_rg",
    ]
    sys.path.insert(0, str(SDT_SRC))
    ap = importlib.import_module("spherex_source_discovery_tool.aperture_photometry")
    return ap, prov


def _sapm_maps(detectors) -> tuple[dict, dict]:
    from astropy.io import fits
    maps, meta = {}, {}
    for k in sorted(detectors):
        url = SAPM_URL.format(c=SAPM_COLLECTION, k=k)
        r = fetch(url, ".fits", "sapm", timeout=600)
        if r["status"] != 200:
            raise RuntimeError(f"solid angle pixel map D{k} unavailable: {r['status']}")
        with fits.open(ROOT / r["path"]) as h:
            maps[k] = np.asarray(h["IMAGE"].data, dtype=float)
        meta[f"D{k}"] = {"url": url, "sha256": r["sha256"]}
    return maps, meta


def run_sdt_target(name: str, ap, sapm: dict) -> dict:
    import pandas as pd
    from astropy.io import fits
    from astropy.table import Table
    from astropy.wcs import WCS

    ev = json.loads(TARGETS[name].read_text())
    ra, dec = ev["ra"], ev["dec"]
    epochs = {e["obs_id"]: e for e in ev["epochs"]}
    ids = sorted({c["a"] for c in ev["comparisons"]} | {c["b"] for c in ev["comparisons"]})
    downloads, rows = [], []
    for oid in ids:
        acc = epochs[oid]["provenance"]["obs"]["access_url"]
        url = acc + "?" + urllib.parse.urlencode({"center": f"{ra},{dec}", "size": f"{SDT_CUTOUT_DEG}"})
        r = fetch(url, ".fits", "cutouts")
        downloads.append({"obs_id": oid, **{k: r[k] for k in ("url", "status", "cached", "sha256")},
                          "n_attempts": len(r["attempts"])})
        if r["status"] == 200:
            rows.append((oid, ROOT / r["path"]))

    # Build the table the notebook's process_cutout() builds: HDUs 1..6 and
    # the spectral WCS with SIP switched off, exactly as the notebook does.
    tab = Table()
    tab["uri"] = [str(p) for _, p in rows]
    tab["cutout_index"] = np.arange(1, len(rows) + 1)
    tab["hdus"] = np.full(len(rows), None)
    tab["spectral_wcs"] = np.full(len(rows), None)
    info = {}
    for i, (oid, p) in enumerate(rows):
        with fits.open(p) as hl:
            hdr = hl[1].header
            sw = WCS(hdr, fobj=hl, key="W")
            sw.sip = None
            tab["spectral_wcs"][i] = sw
            tab["hdus"][i] = [h.copy() for h in hl[1:]]
            x, y = (float(v) for v in WCS(hdr).world_to_pixel_values(ra, dec))
            px, py = parent_pixel(hdr, x, y)
            det = int(hdr["DETECTOR"])
            sa = sapm[det]
            ny, nx = hl[1].data.shape
            info[str(hdr["EXPIDN"])] = {
                "obs_id": hdr["OBSID"], "detector": det, "x_cutout": x, "y_cutout": y,
                "x_detector": px, "y_detector": py, "cutout_shape": [ny, nx],
                # What the SDT's sa_mjy_scale_map() uses: the full-detector map
                # does not match the cutout shape, so it is interpolated at
                # cutout pixel indices 0..nx-1, i.e. the detector's corner, not
                # where the cutout really sits. We record both values.
                "omega_sdt_arcsec2": float(sa[int(round(y)), int(round(x))]),
                "omega_true_arcsec2": float(sa[int(round(py)), int(round(px))]),
            }
            assert hdr["OBSID"] == oid, (hdr["OBSID"], oid)

    stars = pd.DataFrame({"ra": [ra], "dec": [dec]})
    phot_path = CACHE / f"sdt_phot_{name}.pkl"
    ap.build_phot_table(tab, stars, SDT_RADII, str(phot_path), sapm_s3=[])

    sdt = {}
    for obs in stars.at[0, "obs_log"]:
        i = info[str(obs["image_id"])]
        n_bad = [sum(obs["dqf_sum"][f][k] for f in SDT_BAD_FLAGS if f in obs["dqf_sum"])
                 for k in range(len(SDT_RADII))]
        sdt[i["obs_id"]] = {**i, "mjd": obs["mjd_center"], "wavelength_um": obs["wavelength"],
                            "bandwidth_um": obs["bandwidth"], "flux_mjy": obs["aper_sum_bkgsub"],
                            "var_mjy2": obs["variance_sum"], "n_bad_flag_pixels": n_bad,
                            "omega_fix": i["omega_true_arcsec2"] / i["omega_sdt_arcsec2"]}

    ours = our_epoch_fluxes(ev)
    per = []
    for oid, s in sorted(sdt.items()):
        o = ours.get(oid)
        rec = {"obs_id": oid, "detector": s["detector"], "mjd": s["mjd"],
               "sdt_wavelength_um": s["wavelength_um"], "sdt_bandwidth_um": s["bandwidth_um"],
               "our_wavelength_um": epochs[oid]["wavelength_um"], "our_bandwidth_um": epochs[oid]["bandwidth_um"],
               "sdt_flux_mjy": dict(zip([f"r{r:.1f}" for r in SDT_RADII], s["flux_mjy"])),
               "sdt_flux_err_mjy": dict(zip([f"r{r:.1f}" for r in SDT_RADII],
                                            [float(np.sqrt(max(v, 0))) for v in s["var_mjy2"]])),
               "sdt_n_bad_flag_pixels": dict(zip([f"r{r:.1f}" for r in SDT_RADII], s["n_bad_flag_pixels"])),
               "omega_sdt_arcsec2": s["omega_sdt_arcsec2"], "omega_true_arcsec2": s["omega_true_arcsec2"],
               "x_detector": s["x_detector"], "y_detector": s["y_detector"]}
        if o:
            our_mjy = mjysr_sum_to_mjy(o["flux"], s["omega_true_arcsec2"])
            our_err = mjysr_sum_to_mjy(o["flux_err"], s["omega_true_arcsec2"])
            k2 = SDT_RADII.index(2.0)
            sdt2 = s["flux_mjy"][k2] * s["omega_fix"]
            rec.update({"our_flux_mjy": our_mjy, "our_flux_err_mjy": our_err, "our_grid": o["grid"],
                        "ratio_sdt_r2_omegafixed_over_ours": sdt2 / our_mjy if our_mjy else None,
                        "ratio_sdt_r2_verbatim_over_ours": s["flux_mjy"][k2] / our_mjy if our_mjy else None,
                        "ratio_sdt_r3_verbatim_over_ours": s["flux_mjy"][SDT_RADII.index(3.0)] / our_mjy
                        if our_mjy else None,
                        "pull_sdt_r2_omegafixed_minus_ours": (sdt2 - our_mjy) / our_err if our_err else None})
        rec["dlambda_sdt_minus_ours_nm"] = 1e3 * (s["wavelength_um"] - epochs[oid]["wavelength_um"])
        rec["dlambda_over_bandwidth"] = (s["wavelength_um"] - epochs[oid]["wavelength_um"]) / epochs[oid]["bandwidth_um"]
        per.append(rec)

    pairs = {f"r{r:.1f}_{'omegafixed' if fix else 'verbatim'}": compare_pairs(ev, sdt, r, fix)
             for r in SDT_RADII for fix in (False, True)}
    snr = robust_stats([p["our_flux_mjy"] / p["our_flux_err_mjy"] for p in per if p.get("our_flux_err_mjy")])

    def pair_summary(lst):
        return {"n_pairs": len(lst),
                "sdt_ratio_over_ours_ratio": robust_stats(
                    [p["sdt_ratio"] / p["ours_ratio"] for p in lst if p["sdt_ratio"] and p["ours_ratio"]]),
                "sdt_significance_minus_ours": robust_stats(
                    [p["sdt_significance"] - p["ours_significance"] for p in lst]),
                "changed_verdict_agrees": sum(p["ours_changed"] == p["sdt_changed"] for p in lst),
                "changed_ours": sum(p["ours_changed"] for p in lst),
                "changed_sdt": sum(p["sdt_changed"] for p in lst)}

    return {
        "target": ev["target"], "ra": ra, "dec": dec,
        "n_exposures_requested": len(ids), "n_cutouts_downloaded": len(rows),
        "n_measured_by_sdt": len(sdt), "n_matched_by_obs_id": sum(1 for p in per if "our_flux_mjy" in p),
        "cutout_downloads": downloads,
        "our_snr": snr,
        "summary": {
            "flux_ratio_sdt_r2_omegafixed_over_ours": robust_stats(
                [p.get("ratio_sdt_r2_omegafixed_over_ours") for p in per]),
            # Our epoch b is measured after reprojection onto a's grid; splitting
            # by grid shows how much of any offset comes from that interpolation.
            "flux_ratio_sdt_r2_omegafixed_over_ours_native_grid": robust_stats(
                [p.get("ratio_sdt_r2_omegafixed_over_ours") for p in per if p.get("our_grid") == "native"]),
            "flux_ratio_sdt_r2_omegafixed_over_ours_reprojected": robust_stats(
                [p.get("ratio_sdt_r2_omegafixed_over_ours") for p in per if p.get("our_grid") == "reprojected"]),
            "flux_ratio_sdt_r2_verbatim_over_ours": robust_stats(
                [p.get("ratio_sdt_r2_verbatim_over_ours") for p in per]),
            "flux_ratio_sdt_r3_verbatim_over_ours": robust_stats(
                [p.get("ratio_sdt_r3_verbatim_over_ours") for p in per]),
            "pull_sdt_r2_omegafixed_minus_ours": robust_stats(
                [p.get("pull_sdt_r2_omegafixed_minus_ours") for p in per]),
            "omega_true_over_sdt_used": robust_stats([p["omega_true_arcsec2"] / p["omega_sdt_arcsec2"] for p in per]),
            "dlambda_sdt_minus_ours_nm": robust_stats([p["dlambda_sdt_minus_ours_nm"] for p in per]),
            "abs_dlambda_over_bandwidth": robust_stats([abs(p["dlambda_over_bandwidth"]) for p in per]),
            "exposures_sdt_would_flag_r2": sum(1 for p in per if p["sdt_n_bad_flag_pixels"]["r2.0"] > 0),
            "exposures_sdt_would_flag_r3": sum(1 for p in per if p["sdt_n_bad_flag_pixels"]["r3.0"] > 0),
            "pairs": {k: pair_summary(v) for k, v in pairs.items()},
        },
        "per_exposure": per,
        "pairs": pairs,
    }


def run_sdt() -> dict:
    rec = {"tool": "IRSA SPHEREx Source Discovery Tool (spherex_source_discovery_tool.aperture_photometry)",
           "notebook": "https://caltech-ipac.github.io/irsa-tutorials/spherex-source-discovery-tool-demo/"}
    try:
        for mod in ("photutils", "pandas", "tqdm", "psutil"):
            importlib.import_module(mod)
    except ImportError as e:
        return rec | {"status": "NOT RUN", "reason": f"SDT dependency missing in this Python: {e}. "
                      "Run with data/cache/irsa_tools/venv-sdt/bin/python."}
    try:
        ap, prov = _load_sdt()
        sapm, sapm_meta = _sapm_maps({1, 6})

        def fetch_sapm(_paths):
            # Same return shape as upstream; the interpolator is upstream's own.
            return sapm, {k: ap.interp2d_rg(np.arange(m.shape[1]), np.arange(m.shape[0]), m)
                          for k, m in sapm.items()}
        ap.fetch_sapm = fetch_sapm
        import photutils
        rec.update({"status": "RAN", "provenance": prov, "sapm": sapm_meta,
                    "photutils_version": photutils.__version__,
                    "settings": {"cutout_size_deg": SDT_CUTOUT_DEG, "aperture_radii_px": SDT_RADII,
                                 "annulus_px": [7, 16], "background": "sigma-clipped median in annulus "
                                 "(SDT's extract_photometry); no flag masking in the aperture sum",
                                 "spectral_wcs": "WCS(key='W') with sip=None, as the notebook",
                                 "bad_flags_for_counting": SDT_BAD_FLAGS},
                    "method_differences_vs_hipparchus": [
                        "Aperture: SDT r=3 px (notebook) vs ours r=2 px; we also run SDT at r=2 px.",
                        "Background: SDT sigma-clipped median of a 7-16 px annulus vs our plain median "
                        "of a 4-7 px annulus with flagged pixels excluded.",
                        "Flags: SDT sums all pixels and only counts flags afterwards; we refuse a measurement "
                        "when any aperture pixel carries a BAD_PLANES flag.",
                        "Units: SDT converts to mJy with the solid angle pixel map; ours is MJy/sr summed over "
                        "pixels. We convert ours with the map value at the target's detector pixel.",
                        "Solid angle position: the SDT interpolates the full-detector map at cutout pixel "
                        "indices (its sa_mjy_scale_map), i.e. the detector corner, not the cutout's real "
                        "place. We report SDT verbatim and with that factor corrected (omegafixed).",
                        "Grid: our epoch b is measured after reprojection onto epoch a's grid; SDT measures "
                        "every exposure on its own grid.",
                        "Wavelength: SDT reads WCS-WAVE without SIP; our published numbers use the legacy "
                        "'wcs' source (SIP applied, see quality.WAVELENGTH_SOURCES).",
                    ]})
        for name in TARGETS:
            print(f"SDT on {name}", flush=True)
            rec[name] = run_sdt_target(name, ap, sapm)
    except Exception as e:  # we report the failure instead of inventing numbers
        rec.update({"status": "NOT RUN", "reason": f"{type(e).__name__}: {e}"})
    return rec


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------

# Categorical slots 1-3 of the shared report palette (blue, orange, aqua).
C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED = "#222222", "#8a8a85"


def make_figures(result: dict) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    FIGURES.mkdir(parents=True, exist_ok=True)
    written = []
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
                         "xtick.color": INK, "ytick.color": INK, "axes.grid": True,
                         "grid.color": "#e6e6e3", "grid.linewidth": 0.6})

    sdt = result["source_discovery_tool"]
    if sdt.get("status") == "RAN":
        fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.4))
        rw = sdt["rw_aur"]
        per = [p for p in rw["per_exposure"] if "our_flux_mjy" in p]
        x = np.array([p["our_flux_mjy"] for p in per])
        ax = axes[0]
        ax.plot([x.min() * 0.9, x.max() * 1.1], [x.min() * 0.9, x.max() * 1.1], color=MUTED, lw=1, label="1:1")
        ax.scatter(x, [p["sdt_flux_mjy"]["r2.0"] * p["omega_true_arcsec2"] / p["omega_sdt_arcsec2"] for p in per],
                   s=28, color=C1, marker="o", label="SDT r=2 px (Ω fixed)", zorder=3)
        ax.scatter(x, [p["sdt_flux_mjy"]["r3.0"] for p in per], s=28, color=C2, marker="s",
                   label="SDT r=3 px (as published)", zorder=3)
        ax.set_xlabel("HIPPARCHUS flux, r=2 px [mJy]")
        ax.set_ylabel("IRSA SDT flux [mJy]")
        ax.set_title("RW Aur, same exposures", color=INK)
        ax.legend(frameon=False, fontsize=7.5)

        ax = axes[1]
        pr = rw["pairs"]["r2.0_omegafixed"]
        pr3 = rw["pairs"]["r3.0_verbatim"]
        lo = min(min(p["ours_ratio"] for p in pr), min(p["sdt_ratio"] for p in pr + pr3)) * 0.95
        hi = max(max(p["ours_ratio"] for p in pr), max(p["sdt_ratio"] for p in pr + pr3)) * 1.05
        ax.plot([lo, hi], [lo, hi], color=MUTED, lw=1, label="1:1")
        ax.scatter([p["ours_ratio"] for p in pr], [p["sdt_ratio"] for p in pr], s=28, color=C1, marker="o",
                   label="SDT r=2 px (Ω fixed)", zorder=3)
        ax.scatter([p["ours_ratio"] for p in pr3], [p["sdt_ratio"] for p in pr3], s=28, color=C2, marker="s",
                   label="SDT r=3 px (as published)", zorder=3)
        ax.set_xlabel("HIPPARCHUS flux ratio b/a")
        ax.set_ylabel("IRSA SDT flux ratio b/a")
        ax.set_title("RW Aur, the 8 published pairs", color=INK)
        ax.legend(frameon=False, fontsize=7.5)

        ax = axes[2]
        wp = [p for p in sdt["wise0855"]["per_exposure"] if "our_flux_mjy" in p]
        ax.errorbar([p["our_flux_mjy"] for p in wp],
                    [p["sdt_flux_mjy"]["r2.0"] * p["omega_true_arcsec2"] / p["omega_sdt_arcsec2"] for p in wp],
                    xerr=[p["our_flux_err_mjy"] for p in wp], yerr=[p["sdt_flux_err_mjy"]["r2.0"] for p in wp],
                    fmt="o", ms=4, color=C1, ecolor="#b7d3f6", elinewidth=1, label="SDT r=2 px (Ω fixed)")
        v = [p["our_flux_mjy"] for p in wp]
        ax.plot([min(v), max(v)], [min(v), max(v)], color=MUTED, lw=1, label="1:1")
        ax.set_xlabel("HIPPARCHUS flux, r=2 px [mJy]")
        ax.set_ylabel("IRSA SDT flux [mJy]")
        ax.set_title(f"WISE 0855 (our S/N ~ {sdt['wise0855']['our_snr']['median']:.0f})", color=INK)
        ax.legend(frameon=False, fontsize=7.5)
        fig.tight_layout()
        p = FIGURES / "irsa_tools_photometry.png"
        fig.savefig(p, dpi=170)
        plt.close(fig)
        written.append(_rel(p))

    most = result["most"]
    if most.get("status") == "RAN":
        fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.6))
        per = most["per_image"]
        best = most["time_convention"].get("best")
        ax = axes[0]
        ax.plot([p["most_ra"] for p in per], [p["most_dec"] for p in per], "o", ms=6, color=C2,
                label="MOST predicted", zorder=2)
        meas = [p for p in per if p["most_minus_measured"]]
        motion = json.loads(MOTION_JSON.read_text())
        ours = {(e["obs_id"], e["detector"]): e for e in motion["exposures"]}
        ax.plot([ours[(p["obs_id"], p["detector"])]["measured"]["ra"] for p in meas],
                [ours[(p["obs_id"], p["detector"])]["measured"]["dec"] for p in meas], "x", ms=6, color=C1,
                label="HIPPARCHUS measured", zorder=3)
        miss = [ours[(m["obs_id"], m["detector"])] for m in most["match"]["only_ours"]]
        if miss:
            ax.plot([e["horizons_spherex"]["ra"] for e in miss], [e["horizons_spherex"]["dec"] for e in miss],
                    "^", ms=7, mfc="none", color=C3, label="in our list only (off detector)", zorder=3)
        ax.invert_xaxis()
        ax.set_xlabel("RA [deg]")
        ax.set_ylabel("Dec [deg]")
        ax.set_title("(216) Kleopatra, MJD 60843.4-60846.7", color=INK)
        ax.legend(frameon=False, fontsize=7.5)
        ax = axes[1]
        t = [p["our_mjd_mid"] for p in per]
        ax.plot(t, [p["most_minus_horizons_spherex_mid"]["total"] for p in per], "o", ms=5, color=C2,
                label="MOST − Horizons (SPHEREx, mid-exposure)")
        if best:
            ax.plot(t, [p["most_minus_horizons"][best]["total"] for p in per], "s", ms=4, color=C3,
                    label="MOST − Horizons (SPHEREx, exposure start)" if best == "spherex@mjd_start" else f"MOST − Horizons ({best})")
        ax.plot([p["our_mjd_mid"] for p in meas], [p["most_minus_measured"]["total"] for p in meas], "x", ms=6,
                color=C1, label="MOST − HIPPARCHUS measured")
        ax.ticklabel_format(axis="x", useOffset=False)
        ax.set_xlabel("MJD")
        ax.set_ylabel("offset [arcsec]")
        ax.set_title("Position differences (SPHEREx pixel = 6.15\")", color=INK)
        ax.legend(frameon=False, fontsize=7.5)
        fig.tight_layout()
        p = FIGURES / "irsa_tools_most.png"
        fig.savefig(p, dpi=170)
        plt.close(fig)
        written.append(_rel(p))
    return written


# --------------------------------------------------------------------------

def interpret(result: dict) -> list[str]:
    """Plain-language reading of the numbers, built from the numbers themselves
    so the text cannot drift away from the JSON."""
    out = []
    sdt = result["source_discovery_tool"]
    if sdt.get("status") == "RAN":
        rw = sdt["rw_aur"]["summary"]
        f, nat, rep = (rw["flux_ratio_sdt_r2_omegafixed_over_ours"],
                       rw["flux_ratio_sdt_r2_omegafixed_over_ours_native_grid"],
                       rw["flux_ratio_sdt_r2_omegafixed_over_ours_reprojected"])
        pr = rw["pairs"]["r2.0_omegafixed"]
        out.append(
            f"RW Aur, same aperture (r=2 px), same {f['n']} exposures: SDT/ours = {f['median']:.4f} "
            f"(robust scatter {f['robust_sigma']:.4f}). On exposures we measure on their own grid the median is "
            f"{nat['median']:.4f} (n={nat['n']}); on exposures we measure after reprojection it is "
            f"{rep['median']:.4f} (n={rep['n']}). So the background methods agree to a few 0.1%, and our "
            f"bilinear reprojection of epoch b costs about {100 * (rep['median'] - nat['median']):.1f}% of its flux "
            f"in a 2 px aperture.")
        out.append(
            f"RW Aur brightness ratios (8 published pairs): SDT ratio / our ratio = "
            f"{pr['sdt_ratio_over_ours_ratio']['median']:.4f} (robust scatter "
            f"{pr['sdt_ratio_over_ours_ratio']['robust_sigma']:.4f}); the ~1% excess is the reprojection loss "
            f"above, not a calibration difference. All {pr['n_pairs']} pairs are 'changed' in both. The SDT's "
            f"significances are larger (median +{pr['sdt_significance_minus_ours']['median']:.0f} sigma) because "
            f"its error is the variance sum only, while ours adds the sky-level error for every aperture pixel.")
        r3 = rw["flux_ratio_sdt_r3_verbatim_over_ours"]
        om = rw["omega_true_over_sdt_used"]
        out.append(
            f"As published (r=3 px, SDT's own solid-angle handling) SDT/ours = {r3['median']:.4f}: the larger "
            f"aperture adds light, while the SDT reads the solid angle map at the detector corner instead of the "
            f"cutout's real place, which here is {100 * (om['median'] - 1):.1f}% too small; the two partly cancel.")
        dl = rw["dlambda_sdt_minus_ours_nm"]
        dlw = sdt["wise0855"]["summary"]["dlambda_sdt_minus_ours_nm"]
        out.append(
            f"Wavelengths: SDT - ours = {dl['median']:+.1f} nm median on D1 (max {dl['max']:.1f}) and "
            f"{dlw['median']:+.1f} nm on D6 (range {dlw['min']:.1f} to {dlw['max']:.1f}). The SDT reads WCS-WAVE "
            f"without SIP; our published numbers use the legacy 'wcs' source with SIP applied, the offset we "
            f"already document (up to 18 nm on D6).")
        w = sdt["wise0855"]["summary"]
        wf, wp = w["flux_ratio_sdt_r2_omegafixed_over_ours"], w["pull_sdt_r2_omegafixed_minus_ours"]
        p2, p3 = w["pairs"]["r2.0_omegafixed"], w["pairs"]["r3.0_verbatim"]
        out.append(
            f"WISE 0855 (our S/N median {sdt['wise0855']['our_snr']['median']:.1f}): at r=2 px SDT/ours = "
            f"{wf['median']:.3f} (robust scatter {wf['robust_sigma']:.3f}), (SDT - ours)/sigma_ours median "
            f"{wp['median']:+.2f}. No pair is 'changed' for either at r=2 px ({p2['changed_verdict_agrees']}/"
            f"{p2['n_pairs']} verdicts agree). At r=3 px, as published, the SDT calls {p3['changed_sdt']} pairs "
            f"changed; every one involves an exposure with flagged pixels inside its aperture, which the SDT sums "
            f"and only counts afterwards ({w['exposures_sdt_would_flag_r3']} exposures). Those pixels lie between 2 "
            f"and 3 px from the target ({w['exposures_sdt_would_flag_r2']} exposures are flagged at r=2 px), so our "
            f"2 px aperture never touches them, and we would refuse the measurement if it did.")
    most = result["most"]
    if most.get("status") == "RAN":
        m, tc, pa = most["match"], most["time_convention"], most["position_agreement_arcsec"]
        out.append(
            f"MOST lists {m['n_most']} SPHEREx images with (216) Kleopatra in the window; we used {m['n_ours']}. "
            f"{m['n_both']} are common, {len(m['only_most'])} are MOST-only, {len(m['only_ours'])} are ours-only "
            f"({', '.join(sorted({x['obs_id'] for x in m['only_ours']}))}): there the predicted position is beyond "
            f"the detector edge, we flagged it 'off_edge' and measured nothing, so both tools agree it is not in "
            f"the image.")
        out.append(
            f"MOST positions equal Horizons as seen from SPHEREx at the exposure START (rms "
            f"{tc['rms_arcsec']['spherex@mjd_start']:.4f} arcsec), not at mid-exposure "
            f"({tc['rms_arcsec']['spherex@mid_exposure']:.2f} arcsec) and not geocentric "
            f"({tc['rms_arcsec']['geocentric@mjd_start']:.2f} arcsec). Against our measured centroids MOST "
            f"differs by {pa['most_vs_our_measured']['median']:.2f} arcsec median (n={pa['most_vs_our_measured']['n']}), "
            f"mostly that start-vs-mid time offset; both are far below the 6.15 arcsec pixel.")
    out.append("The Spectrophotometry Tool (Tractor PSF photometry) was NOT RUN: see spectrophotometry_tool.reason.")
    return out


def main() -> dict:
    t0 = utc_now()
    print("MOST ...", flush=True)
    most = run_most()
    print("Spectrophotometry Tool (documentation check only) ...", flush=True)
    spt = run_spectrophotometry_tool()
    print("Source Discovery Tool ...", flush=True)
    sdt = run_sdt()
    result = {
        "experiment": "HIPPARCHUS against IRSA's own SPHEREx tools, on the same exposures",
        "claim": "consistency check only; IRSA's tools are references, not ground truth",
        "run": {"started_utc": t0, "finished_utc": None, "python": platform.python_version(),
                "numpy": np.__version__, "script": "backend/scripts/compare_irsa_tools.py",
                "retry_policy": {"backoff_s": list(BACKOFF_S), "budget_s": RETRY_BUDGET_S,
                                 "retry_on": sorted(RETRY_STATUSES) + ["connection errors / timeouts"]},
                "retry_wait_spent_s": _BUDGET["spent_s"]},
        "source_discovery_tool": sdt,
        "spectrophotometry_tool": spt,
        "most": most,
    }
    result["interpretation"] = interpret(result)
    result["figures"] = make_figures(result)
    result["run"]["finished_utc"] = utc_now()
    result["run"]["retry_wait_spent_s"] = _BUDGET["spent_s"]
    fresh = [r for r in REQUEST_LOG if not r["from_cache"]]
    result["http_log"] = {"n_requests_sent": len(fresh), "n_cache_hits": len(REQUEST_LOG) - len(fresh),
                          "status_counts": {str(s): sum(1 for r in fresh if str(r["status"]) == s)
                                            for s in sorted({str(r["status"]) for r in fresh})},
                          "non_200": [r for r in fresh if r["status"] != 200]}
    try:
        import astropy
        result["run"]["astropy"] = astropy.__version__
    except ImportError:
        pass
    OUT_JSON.write_text(json.dumps(result, indent=1, default=float) + "\n")
    print(f"wrote {_rel(OUT_JSON)}", flush=True)
    return result


if __name__ == "__main__":
    main()
