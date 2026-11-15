"""Read-only endpoints behind the explorer views of the web page.

- /explore/meta      presets, cutout size, aperture and the pairing rule, in one place
- /explore/hips      which all-sky HiPS layers IRSA is serving right now
- /explore/resolve   object name -> position, through CDS Sesame (SIMBAD first)
- /explore/spectrum  per-epoch aperture photometry of an analysis (single exposures only)
- /explore/pixels    native-pixel arrays of an epoch or a pair, for the zoomable viewer

Everything here reads an analysis that /analyze already made; nothing starts a new
download from IRSA except the HiPS probe and the name resolver, and both have short
timeouts and a cache.
"""

from __future__ import annotations

import math
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlparse

import httpx
import numpy as np
from astropy import units as u
from fastapi import APIRouter, HTTPException, Path, Query

from hipparchus import compare, cutouts, quality

router = APIRouter(prefix="/explore", tags=["explore"])

# The static page that works without our backend or IRSA; we point to it whenever
# the archive is down.
JUDGE_MODE_URL = "https://evantampa129.github.io/HIPPARCHUS-SpaceApps2026/"

# SPHEREx native pixel, from the instrument description. Each epoch also carries
# its own WCS scale; this number is only for labels.
NATIVE_PIXEL_ARCSEC = 6.15


def _api():
    # We import api lazily: api.py includes this router, so a top-level import would be circular.
    from hipparchus import api
    return api


# ---------------------------------------------------------------- small TTL cache

class _TTLCache:
    """A tiny thread-safe cache with expiry and a size cap (oldest entry goes first)."""

    def __init__(self, ttl: float, max_items: int):
        self.ttl, self.max_items = ttl, max_items
        self._d: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            hit = self._d.get(key)
            if hit is None or time.monotonic() - hit[0] > self.ttl:
                self._d.pop(key, None)
                return None
            return hit[1]

    def put(self, key: str, value) -> None:
        with self._lock:
            if len(self._d) >= self.max_items:
                self._d.pop(min(self._d, key=lambda k: self._d[k][0]))
            self._d[key] = (time.monotonic(), value)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()


# ---------------------------------------------------------------- meta

@router.get("/meta")
def meta() -> dict:
    api = _api()
    return {
        "targets": api.TARGETS,
        "cutout_size_deg": cutouts.DEFAULT_SIZE_DEG,
        "native_pixel_arcsec": NATIVE_PIXEL_ARCSEC,
        "aperture_radius_px": quality.APERTURE_PX,
        "sky_annulus_px": [compare.SKY_INNER, compare.SKY_OUTER],
        "max_dlambda_fraction": compare.MAX_DLAMBDA_FRACTION,
        "judge_mode_url": JUDGE_MODE_URL,
    }


# ---------------------------------------------------------------- HiPS layers

# All four trees are hosted by IRSA, so the explorer does not depend on a second
# data centre. Only the first one is SPHEREx; the others are context and say so.
HIPS_LAYERS = [
    {"id": "spherex", "kind": "spherex", "label": "SPHEREx (NASA/IPAC IRSA)",
     "url": "https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube",
     "credit": "NASA/SPHEREx; HiPS by the SPHEREx Science Data Center, Caltech/IPAC"},
    {"id": "2mass", "kind": "context", "label": "Context: 2MASS J/H/K colour (not SPHEREx)",
     "url": "https://irsa.ipac.caltech.edu/data/hips/CDS/2MASS/Color",
     "credit": "2MASS (UMass/IPAC); HiPS by CDS, mirrored at IRSA"},
    {"id": "allwise", "kind": "context", "label": "Context: AllWISE W1/W2/W4 colour (not SPHEREx)",
     "url": "https://irsa.ipac.caltech.edu/data/hips/CDS/AllWISE/RGB-W4-W2-W1",
     "credit": "WISE/NEOWISE (NASA/JPL-Caltech/UCLA); HiPS by CDS, mirrored at IRSA"},
    {"id": "dss2", "kind": "context", "label": "Context: DSS2 optical colour (not SPHEREx)",
     "url": "https://irsa.ipac.caltech.edu/data/hips/CDS/DSS2/color",
     "credit": "Digitized Sky Survey (STScI); HiPS by CDS, mirrored at IRSA"},
]

# Channel centres of the SPHEREx DR1 HiPS cube (data_cube_crval3_arr in its
# properties file, read on 2026-11-16). Frame = 17*(band-1) + (channel-1), and
# band n is detector Dn. We use this copy only when IRSA cannot be reached.
SPHEREX_CHANNELS_UM_SAVED = [float(v) for v in """
0.753 0.771 0.790 0.809 0.828 0.848 0.868 0.889 0.910 0.932 0.955 0.978 1.001 1.025 1.050 1.075 1.102
1.113 1.139 1.167 1.195 1.224 1.254 1.284 1.315 1.346 1.378 1.412 1.446 1.481 1.517 1.554 1.592 1.631
1.656 1.695 1.735 1.775 1.818 1.861 1.905 1.949 1.995 2.041 2.089 2.139 2.189 2.240 2.292 2.345 2.399
2.445 2.506 2.575 2.646 2.719 2.794 2.871 2.951 3.033 3.118 3.204 3.293 3.383 3.476 3.570 3.667 3.768
3.833 3.867 3.901 3.935 3.970 4.005 4.040 4.076 4.112 4.148 4.184 4.220 4.257 4.294 4.331 4.368 4.405
4.435 4.467 4.500 4.533 4.566 4.600 4.635 4.669 4.704 4.739 4.773 4.808 4.843 4.879 4.915 4.951 4.988
""".split()]

HIPS_TIMEOUT_S = 6.0
_HIPS_CACHE = _TTLCache(ttl=300, max_items=8)


def _fetch(url: str, timeout: float) -> httpx.Response:
    # One place for outgoing GETs, so the tests can replace it without any network.
    return httpx.get(url, timeout=timeout, follow_redirects=True,
                     headers={"User-Agent": "HIPPARCHUS explorer (NASA Space Apps 2026)"})


def parse_properties(text: str) -> dict[str, str]:
    """HiPS 'properties' file: key = value lines, '#' comments."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _probe(layer: dict) -> dict:
    status = {"ok": False, "http_status": None, "message": ""}
    try:
        r = _fetch(layer["url"] + "/properties", HIPS_TIMEOUT_S)
    except httpx.TimeoutException:
        status["message"] = f"IRSA did not answer within {HIPS_TIMEOUT_S:.0f} s."
        return {**layer, "status": status}
    except httpx.HTTPError as e:
        status["message"] = f"Could not reach IRSA ({type(e).__name__})."
        return {**layer, "status": status}
    status["http_status"] = r.status_code
    if r.status_code != 200:
        # We name the code: a 502 is IRSA's gateway, not a fault of this page.
        status["message"] = (f"IRSA answered HTTP {r.status_code}"
                             + (" (Bad Gateway: the archive side is down or overloaded)" if r.status_code == 502 else "")
                             + ". This is an archive-side problem; try again later.")
        return {**layer, "status": status}
    p = parse_properties(r.text)
    status["ok"] = True
    info = {"status": status, "properties": {
        k: p.get(k) for k in ("obs_title", "hips_release_date", "hips_order", "hips_tile_width",
                              "hips_pixel_scale", "dataproduct_type", "hips_cube_depth",
                              "hips_cube_firstframe", "em_min", "em_max", "t_min", "t_max",
                              "obs_copyright", "hips_copyright", "obs_description")}}
    try:
        info["hips_pixel_arcsec"] = float(p["hips_pixel_scale"]) * 3600
    except (KeyError, ValueError):
        info["hips_pixel_arcsec"] = None
    if "data_cube_crval3_arr" in p:
        try:
            info["channels_um"] = [float(v) for v in p["data_cube_crval3_arr"].split()]
        except ValueError:
            pass
    return {**layer, **info}


@router.get("/hips")
def hips() -> dict:
    """Which HiPS layers are available right now. Probed live, cached for 5 minutes."""
    hit = _HIPS_CACHE.get("layers")
    if hit is not None:
        return {**hit, "cached": True}
    with ThreadPoolExecutor(len(HIPS_LAYERS)) as pool:
        layers = list(pool.map(_probe, HIPS_LAYERS))
    sx = layers[0]
    channels = sx.get("channels_um")
    out = {
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "layers": layers,
        "spherex_available": sx["status"]["ok"],
        "channels_um": channels or SPHEREX_CHANNELS_UM_SAVED,
        "channels_source": "live HiPS properties" if channels else "saved copy of the HiPS properties (2026-11-16)",
        "native_pixel_arcsec": NATIVE_PIXEL_ARCSEC,
        "judge_mode_url": JUDGE_MODE_URL,
        "cached": False,
    }
    _HIPS_CACHE.put("layers", out)
    return out


# ---------------------------------------------------------------- name resolver

# Letters, digits, spaces and the punctuation real designations use
# ("Barnard's Star", "WISE J085510.83-071442.5", "NGC 1952", "V* RW Aur", "[ABC] 12").
NAME_RE = re.compile(r"^[A-Za-z0-9 +\-_.'*()\[\]:/]{1,64}$")
SESAME_URLS = [
    "https://cds.unistra.fr/cgi-bin/nph-sesame/-oxp/SNV?",
    "https://vizier.cfa.harvard.edu/viz-bin/nph-sesame/-oxp/SNV?",
]
# Sesame redirects to its mirrors; we only follow to hosts we know.
SESAME_HOSTS = ("unistra.fr", "vizier.idia.ac.za", "vizier.cfa.harvard.edu", "cds.unistra.fr")
RESOLVE_TIMEOUT_S = 6.0
MAX_XML_BYTES = 64_000
_RESOLVE_CACHE = _TTLCache(ttl=24 * 3600, max_items=512)

# SPHEREx DR1/QR3 observations span 2025.3 to 2026.9, so we move catalogue
# positions to the middle of that range. Without this, Barnard's Star
# (10"/yr) would be about 4' away from where SPHEREx saw it: outside a 3' cutout.
SPHEREX_EPOCH_YR = 2026.0


def parse_sesame(xml_text: str) -> dict | None:
    """Position (and proper motion, if any) from a Sesame XML answer; None if nothing found."""
    root = ET.fromstring(xml_text)
    for res in root.iter("Resolver"):
        ra, de = res.findtext("jradeg"), res.findtext("jdedeg")
        if ra is None or de is None:
            continue
        ra, de = float(ra), float(de)
        if not (0 <= ra < 360 and -90 <= de <= 90):
            continue
        pm = res.find("pm")
        pm_ra = pm_de = None
        if pm is not None and pm.findtext("pmRA") and pm.findtext("pmDE"):
            pm_ra, pm_de = float(pm.findtext("pmRA")), float(pm.findtext("pmDE"))
        return {"ra_j2000": ra, "dec_j2000": de, "oname": res.findtext("oname"),
                "otype": res.findtext("otype"), "resolver": res.get("name", "Sesame"),
                "pm_ra_masyr": pm_ra, "pm_dec_masyr": pm_de}
    return None


def propagate(ra: float, dec: float, pm_ra: float | None, pm_de: float | None,
              to_year: float = SPHEREX_EPOCH_YR, from_year: float = 2000.0) -> tuple[float, float]:
    """Linear proper-motion shift (pmRA already includes cos dec, as in SIMBAD). Good to
    well under an arcsecond over 26 years for any star, far below a 6.15" pixel."""
    if pm_ra is None or pm_de is None:
        return ra, dec
    dt = to_year - from_year
    cosd = max(math.cos(math.radians(dec)), 1e-6)
    ra2 = (ra + pm_ra * dt / 3.6e6 / cosd) % 360
    dec2 = max(-90.0, min(90.0, dec + pm_de * dt / 3.6e6))
    return ra2, dec2


@router.get("/resolve")
def resolve(name: str = Query(..., min_length=1, max_length=64)) -> dict:
    """Object name -> position, through CDS Sesame (SIMBAD, then NED and VizieR)."""
    clean = " ".join(name.split())
    if not NAME_RE.fullmatch(clean):
        raise HTTPException(422, "Names may contain letters, digits, spaces and + - _ . ' * ( ) [ ] : / only (max 64).")
    key = clean.lower()
    hit = _RESOLVE_CACHE.get(key)
    if hit is not None:
        return {**hit, "cached": True}
    last_error = None
    for base in SESAME_URLS:
        try:
            r = _fetch(base + quote(clean), RESOLVE_TIMEOUT_S)
        except httpx.TimeoutException:
            last_error = "timeout"
            continue
        except httpx.HTTPError as e:
            last_error = type(e).__name__
            continue
        host = urlparse(str(r.url)).hostname or ""
        if not host.endswith(SESAME_HOSTS):
            last_error = f"unexpected redirect to {host}"
            continue
        if r.status_code != 200:
            last_error = f"HTTP {r.status_code}"
            continue
        if len(r.content) > MAX_XML_BYTES:
            last_error = "answer too large"
            continue
        try:
            found = parse_sesame(r.text)
        except ET.ParseError:
            last_error = "unreadable answer"
            continue
        if found is None:
            raise HTTPException(404, f"Sesame found no object called “{clean}”.")
        ra, dec = propagate(found["ra_j2000"], found["dec_j2000"], found["pm_ra_masyr"], found["pm_dec_masyr"])
        out = {"query": clean, **found, "ra": round(ra, 6), "dec": round(dec, 6),
               "epoch": SPHEREX_EPOCH_YR if found["pm_ra_masyr"] is not None else 2000.0,
               "note": ("Catalogue position moved by its proper motion to " f"{SPHEREX_EPOCH_YR}, the middle of the SPHEREx observations."
                        if found["pm_ra_masyr"] is not None else
                        "No proper motion listed: this is the catalogue (J2000) position."),
               "service": base.split("?")[0], "cached": False}
        _RESOLVE_CACHE.put(key, out)
        return out
    status = 504 if last_error == "timeout" else 502
    raise HTTPException(status, f"The name resolver (CDS Sesame) could not be reached ({last_error}). "
                                "Type the RA/Dec instead, or try again later.")


# ---------------------------------------------------------------- spectrum

AID = Path(..., pattern=r"^[0-9a-f]{16}$")


def _sr_per_pixel(ep) -> float:
    # Pixel solid angle from the epoch's own WCS: MJy/sr x sr = MJy.
    area = ep.wcs.proj_plane_pixel_area()
    return float(u.Quantity(area, u.deg ** 2).to_value(u.sr))


def _num(x, nd: int = 6):
    # JSON-safe numbers: NaN/inf become null, others keep nd significant digits.
    if x is None:
        return None
    x = float(x)
    return float(f"{x:.{nd}g}") if math.isfinite(x) else None


@router.get("/spectrum/{aid}")
def spectrum(aid: str = AID) -> dict:
    """Per-epoch aperture photometry on each epoch's own pixels.

    Every point is ONE exposure: nothing is stacked or co-added. Rejected epochs
    are listed with their reasons but get no flux, as in the comparison itself.
    """
    api = _api()
    r = api._get(aid)
    if "_explore_spectrum" in r:
        return r["_explore_spectrum"]
    prov = {e["obs_id"]: e.get("provenance", {}) for e in r.get("epochs", [])}
    points = []
    for ep in r["_epochs"]:
        ph = compare.photometry(ep.image, ep.variance, ep.bad, ep.x, ep.y)
        sr = _sr_per_pixel(ep)
        ok = ep.usable and math.isfinite(ph["flux"])
        obs = prov.get(ep.obs_id, {}).get("obs", {})
        points.append({
            "obs_id": ep.obs_id, "detector": f"SPHEREx-D{ep.detector}", "mjd": _num(ep.mjd, 10),
            "date_obs": ep.date_obs, "wavelength_um": _num(ep.wavelength_um),
            "bandwidth_um": _num(ep.bandwidth_um), "wavelength_source": ep.wavelength_source,
            "usable": ep.usable, "measured": ok,
            "reasons": [i.code for i in ep.issues if i.severity == "reject"],
            "flux": _num(ph["flux"]) if ok else None, "flux_err": _num(ph["flux_err"]) if ok else None,
            "sky": _num(ph["sky"]) if ok else None, "n_pix": ph["n_pix"],
            "sr_per_pixel": _num(sr),
            "flux_mjy": _num(ph["flux"] * sr * 1e9) if ok else None,
            "flux_err_mjy": _num(ph["flux_err"] * sr * 1e9) if ok else None,
            "release": obs.get("release"), "doi": obs.get("doi"),
        })
    out = {
        "analysis_id": aid, "detector": r["detector"], "ra": r["ra"], "dec": r["dec"],
        "points": points,
        "units": {
            "native": "MJy/sr summed over the aperture pixels (zodiacal model and local sky removed)",
            "converted": "mJy inside the aperture: native value x pixel solid angle from each epoch's WCS. "
                         "No aperture correction, so this is NOT the star's total flux density.",
        },
        "aperture_radius_px": quality.APERTURE_PX,
        "sky_annulus_px": [compare.SKY_INNER, compare.SKY_OUTER],
        "max_dlambda_fraction": compare.MAX_DLAMBDA_FRACTION,
        "comparisons": [{"a": c["a"], "b": c["b"]} for c in r.get("comparisons", [])],
        "refused_pairs": r.get("refused_pairs", {}),
        "coadded": False,
    }
    r["_explore_spectrum"] = out  # "_" keys never reach the evidence file
    return out


# ---------------------------------------------------------------- native pixels

def _grid(a, nd: int = 5) -> list:
    return [[_num(v, nd) for v in row] for row in np.asarray(a, dtype=float)]


def _scale_arcsec(ep) -> float:
    s = ep.wcs.proj_plane_pixel_scales()
    vals = [float(getattr(v, "value", v)) for v in s]
    return float(np.mean(vals)) * 3600


def _epoch_meta(r: dict, ep) -> dict:
    prov = next((e.get("provenance", {}) for e in r.get("epochs", []) if e["obs_id"] == ep.obs_id), {})
    obs = prov.get("obs", {})
    return {"obs_id": ep.obs_id, "date_obs": ep.date_obs, "mjd": _num(ep.mjd, 10),
            "detector": f"SPHEREx-D{ep.detector}", "wavelength_um": _num(ep.wavelength_um),
            "bandwidth_um": _num(ep.bandwidth_um), "usable": ep.usable,
            "release": obs.get("release"), "doi": obs.get("doi"),
            "cutout_sha256": prov.get("cutout", {}).get("sha256")}


def _geometry(ep) -> dict:
    return {"x": _num(ep.x), "y": _num(ep.y), "aperture_radius_px": quality.APERTURE_PX,
            "sky_annulus_px": [compare.SKY_INNER, compare.SKY_OUTER],
            "pixel_arcsec": _num(_scale_arcsec(ep), 4), "origin": "lower"}


@router.get("/pixels/{aid}/epoch/{obs_id}")
def epoch_pixels(aid: str = AID, obs_id: str = Path(..., pattern=r"^[A-Za-z0-9_.\-]{1,80}$")) -> dict:
    """One epoch's native pixels (MJy/sr, zodiacal model removed) and its mask."""
    api = _api()
    r = api._get(aid)
    ep = next((e for e in r["_epochs"] if e.obs_id == obs_id), None)
    if ep is None:
        raise HTTPException(404, "No such epoch in this analysis.")
    img = np.where(np.isfinite(ep.image), ep.image, np.nan)
    return {"kind": "epoch", "unit": "MJy/sr", "shape": list(img.shape),
            "image": _grid(img), "masked": (ep.bad | ~np.isfinite(ep.image)).astype(int).tolist(),
            **_geometry(ep), "meta": _epoch_meta(r, ep)}


@router.get("/pixels/{aid}/pair/{pid}")
def pair_pixels(aid: str = AID, pid: int = Path(..., ge=0, le=100_000)) -> dict:
    """A pair on epoch a's grid: a, b (reprojected), difference and significance."""
    api = _api()
    r = api._get(aid)
    pairs = r["comparisons"] + r["null_tests"]
    if pid >= len(pairs):
        raise HTTPException(404, "No such pair.")
    c = pairs[pid]
    arr = c["_arrays"]
    ep_a = next(e for e in r["_epochs"] if e.obs_id == c["a"])
    ep_b = next(e for e in r["_epochs"] if e.obs_id == c["b"])
    return {"kind": "pair", "unit": "MJy/sr", "shape": list(arr["a"].shape),
            "a": _grid(arr["a"]), "b": _grid(arr["b"]), "diff": _grid(arr["diff"]), "z": _grid(arr["z"], 4),
            "masked": arr["bad"].astype(int).tolist(),
            **_geometry(ep_a),
            "meta_a": _epoch_meta(r, ep_a), "meta_b": _epoch_meta(r, ep_b),
            "significance": _num(c.get("significance")), "dt_days": _num(c.get("dt_days")),
            "note": "b is resampled onto a's pixel grid (bilinear) before subtracting; the masked "
                    "layer is the union of both epochs' flags and pixels outside b's footprint."}
